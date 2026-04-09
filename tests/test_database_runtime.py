import subprocess

from shared import database_runtime


def _base_connection() -> dict[str, object]:
    return {
        "type": "dbstring",
        "content": "postgresql+asyncpg://postgres:mysecretpassword@localhost:5432/hyprchan",
        "entities": [],
        "pool_options": {},
    }


def test_explicit_database_url_is_used(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:9999/db")
    resolved = database_runtime.resolve_database_connection(_base_connection())
    assert resolved["content"] == "postgresql+asyncpg://u:p@localhost:9999/db"


def test_sqlite_fallback_is_used_when_docker_is_unavailable(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("HYPRMEMORY_ENABLED", "1")
    monkeypatch.setattr(database_runtime, "_should_auto_manage_database", lambda: True)
    monkeypatch.setattr(database_runtime.shutil, "which", lambda _name: None)

    resolved = database_runtime.resolve_database_connection(_base_connection())

    assert str(resolved["content"]).startswith("sqlite+aiosqlite:///")
    assert str(resolved["content"]).endswith("database.db")
    assert database_runtime.os.environ.get("HYPRMEMORY_ENABLED") == "0"


def test_embedded_postgres_is_used_when_docker_path_is_healthy(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(database_runtime, "_should_auto_manage_database", lambda: True)
    monkeypatch.setattr(
        database_runtime.shutil, "which", lambda _name: "/usr/bin/docker"
    )

    def fake_run_command(args, *, timeout_sec=8.0):
        cmd = list(args)
        if cmd[:2] == ["docker", "info"]:
            return subprocess.CompletedProcess(cmd, 0, "ok", "")
        if cmd[:3] == ["docker", "inspect", "-f"]:
            return subprocess.CompletedProcess(cmd, 1, "", "no container")
        if cmd[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(cmd, 0, "container-id", "")
        if cmd[:2] == ["docker", "exec"] and "pg_isready" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "accepting connections", "")
        if cmd[:2] == ["docker", "exec"] and "psql" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "CREATE EXTENSION", "")
        return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")

    monkeypatch.setattr(database_runtime, "_run_command", fake_run_command)

    resolved = database_runtime.resolve_database_connection(_base_connection())
    assert (
        resolved["content"]
        == "postgresql+asyncpg://postgres:mysecretpassword@127.0.0.1:55432/hyprchan"
    )


def test_no_automanage_leaves_connection_unchanged(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(database_runtime, "_should_auto_manage_database", lambda: False)
    base = _base_connection()
    resolved = database_runtime.resolve_database_connection(base)
    assert resolved["content"] == base["content"]


def test_embedded_postgres_run_uses_local_bind_mount(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(database_runtime, "_should_auto_manage_database", lambda: True)
    monkeypatch.setattr(
        database_runtime.shutil, "which", lambda _name: "/usr/bin/docker"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HYPRCHAN_PG_DATA_DIR", "./runtime/postgres_data")

    run_cmd: list[str] | None = None

    def fake_run_command(args, *, timeout_sec=8.0):
        nonlocal run_cmd
        cmd = list(args)
        if cmd[:2] == ["docker", "info"]:
            return subprocess.CompletedProcess(cmd, 0, "ok", "")
        if cmd[:3] == ["docker", "inspect", "-f"]:
            return subprocess.CompletedProcess(cmd, 1, "", "no container")
        if cmd[:2] == ["docker", "run"]:
            run_cmd = cmd
            return subprocess.CompletedProcess(cmd, 0, "container-id", "")
        if cmd[:2] == ["docker", "exec"] and "pg_isready" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "accepting connections", "")
        if cmd[:2] == ["docker", "exec"] and "psql" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "CREATE EXTENSION", "")
        return subprocess.CompletedProcess(cmd, 1, "", "unexpected command")

    monkeypatch.setattr(database_runtime, "_run_command", fake_run_command)

    resolved = database_runtime.resolve_database_connection(_base_connection())
    assert str(resolved["content"]).startswith("postgresql+asyncpg://")
    assert run_cmd is not None
    assert "-v" in run_cmd
    mount_arg = run_cmd[run_cmd.index("-v") + 1]
    assert mount_arg.endswith(":/var/lib/postgresql/data")
    assert str(tmp_path / "runtime" / "postgres_data") in mount_arg
    assert (tmp_path / "runtime" / "postgres_data").exists()
