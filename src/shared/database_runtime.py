from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


def resolve_database_connection(base_connection: dict[str, Any]) -> dict[str, Any]:
    resolved = dict(base_connection)
    logger.debug("Resolving runtime database connection")

    explicit_url = str(os.getenv("DATABASE_URL", "")).strip()
    if explicit_url:
        resolved["content"] = explicit_url
        logger.info("Using DATABASE_URL override for runtime database connection")
        return resolved

    if not _should_auto_manage_database():
        logger.debug("Database auto-management disabled for current command")
        return resolved

    postgres_url = _ensure_embedded_postgres_url()
    if postgres_url:
        resolved["content"] = postgres_url
        logger.info("Using embedded Postgres runtime database connection")
        return resolved

    sqlite_url = _sqlite_fallback_url()
    resolved["content"] = sqlite_url
    os.environ["HYPRMEMORY_ENABLED"] = "0"
    logger.warning(
        "Docker Postgres unavailable; using SQLite fallback at %s and disabling HyprMemory.",
        sqlite_url,
    )
    return resolved


def _should_auto_manage_database() -> bool:
    if not _env_flag("HYPRCHAN_DB_AUTOSTART", True):
        return False

    argv_tokens = [token.strip().lower() for token in sys.argv if token.strip()]
    logger.debug("Process argv tokens for db autostart=%s", argv_tokens)
    return "serve" in argv_tokens


def _env_flag(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _sqlite_fallback_url() -> str:
    raw_path = str(os.getenv("HYPRCHAN_SQLITE_PATH", "database.db")).strip()
    db_path = Path(raw_path)
    if db_path.is_absolute():
        return f"sqlite+aiosqlite:///{db_path}"
    return f"sqlite+aiosqlite:///./{db_path.as_posix()}"


def _ensure_embedded_postgres_url() -> str | None:
    if shutil.which("docker") is None:
        logger.debug("Docker executable not found; embedded Postgres unavailable")
        return None

    info = _run_command(["docker", "info"], timeout_sec=6.0)
    if info.returncode != 0:
        logger.debug("Docker daemon unavailable; cannot auto-start Postgres")
        return None

    container_name = os.getenv(
        "HYPRCHAN_PG_CONTAINER", "hyprchan-embedded-postgres"
    ).strip()
    image = os.getenv("HYPRCHAN_PG_IMAGE", "pgvector/pgvector:pg16").strip()
    user = os.getenv("HYPRCHAN_PG_USER", "postgres").strip() or "postgres"
    password = os.getenv("HYPRCHAN_PG_PASSWORD", "mysecretpassword").strip()
    database = os.getenv("HYPRCHAN_PG_DB", "hyprchan").strip() or "hyprchan"
    host = os.getenv("HYPRCHAN_PG_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("HYPRCHAN_PG_PORT", "55432"))
    host_data_dir = _resolve_local_postgres_data_dir()

    inspect_running = _run_command(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
        timeout_sec=5.0,
    )

    if inspect_running.returncode != 0:
        logger.info("Embedded Postgres container missing; creating %s", container_name)
        run_args = [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "--restart",
            "unless-stopped",
        ]
        if host_data_dir is not None:
            run_args.extend(
                ["-v", f"{host_data_dir.as_posix()}:/var/lib/postgresql/data"]
            )

        run_args.extend(
            [
                "-e",
                f"POSTGRES_USER={user}",
                "-e",
                f"POSTGRES_PASSWORD={password}",
                "-e",
                f"POSTGRES_DB={database}",
                "-p",
                f"{port}:5432",
                image,
            ]
        )
        run_result = _run_command(
            run_args,
            timeout_sec=20.0,
        )
        if run_result.returncode != 0:
            logger.warning(
                "Failed to start embedded postgres container: %s", run_result
            )
            return None
    else:
        if host_data_dir is not None:
            mount_info = _run_command(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{range .Mounts}}{{.Source}}=>{{.Destination}};{{end}}",
                    container_name,
                ],
                timeout_sec=5.0,
            )
            if mount_info.returncode == 0:
                expected_mount = f"{host_data_dir.as_posix()}=>/var/lib/postgresql/data"
                if expected_mount not in mount_info.stdout:
                    logger.warning(
                        "Embedded Postgres container '%s' is not using HYPRCHAN_PG_DATA_DIR=%s. "
                        "Recreate the container to switch to local bind mount.",
                        container_name,
                        host_data_dir.as_posix(),
                    )

        if inspect_running.stdout.strip().lower() != "true":
            logger.info(
                "Embedded Postgres container exists but stopped; starting %s",
                container_name,
            )
            start_result = _run_command(
                ["docker", "start", container_name], timeout_sec=10.0
            )
            if start_result.returncode != 0:
                logger.warning(
                    "Failed to start existing postgres container '%s': %s",
                    container_name,
                    start_result,
                )
                return None

    if not _wait_postgres_ready(
        container_name=container_name, user=user, database=database
    ):
        return None

    _run_command(
        [
            "docker",
            "exec",
            container_name,
            "psql",
            "-U",
            user,
            "-d",
            database,
            "-c",
            "CREATE EXTENSION IF NOT EXISTS vector;",
        ],
        timeout_sec=10.0,
    )

    encoded_password = quote_plus(password)
    return f"postgresql+asyncpg://{user}:{encoded_password}@{host}:{port}/{database}"


def _wait_postgres_ready(*, container_name: str, user: str, database: str) -> bool:
    for _ in range(25):
        result = _run_command(
            [
                "docker",
                "exec",
                container_name,
                "pg_isready",
                "-U",
                user,
                "-d",
                database,
            ],
            timeout_sec=4.0,
        )
        if result.returncode == 0:
            return True
        time.sleep(1.0)

    logger.warning(
        "Embedded postgres container '%s' did not become ready.", container_name
    )
    return False


def _run_command(
    args: Sequence[str], *, timeout_sec: float = 8.0
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(args),
            check=False,
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout_sec)),
        )
    except Exception as exc:
        return subprocess.CompletedProcess(
            args=list(args),
            returncode=1,
            stdout="",
            stderr=f"{type(exc).__name__}: {exc}",
        )


def _resolve_local_postgres_data_dir() -> Path | None:
    raw = str(os.getenv("HYPRCHAN_PG_DATA_DIR", "./runtime/postgres_data")).strip()
    if not raw:
        return None

    lowered = raw.lower()
    if lowered in {"none", "off", "false", "0", "disabled"}:
        return None

    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()

    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(
            "Could not prepare HYPRCHAN_PG_DATA_DIR '%s': %s", path.as_posix(), exc
        )
        return None

    return path
