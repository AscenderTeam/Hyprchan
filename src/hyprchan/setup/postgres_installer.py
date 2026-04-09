from __future__ import annotations

import subprocess
import time
from typing import Optional
from pathlib import Path

from .utils.docker import is_docker_available


class PostgresInstaller:
    """
    Helper class for installing and configuring PostgreSQL with PGVector.
    """

    def __init__(self, env_path: Path):
        self.env_path = env_path

    def set_database_url(self, db_url: str):
        """Updates the DATABASE_URL in the .env file."""
        env_lines = []
        if self.env_path.exists():
            env_lines = self.env_path.read_text(encoding="utf-8").splitlines()

        target_key = "DATABASE_URL"
        new_env_lines = []
        found = False

        for line in env_lines:
            stripped = line.strip()
            if "=" in line and not stripped.startswith("#"):
                key = line.split("=", 1)[0].strip()
                if key == target_key:
                    new_env_lines.append(f"{target_key}={db_url}")
                    found = True
                    continue
            new_env_lines.append(line)

        if not found:
            new_env_lines.append(f"{target_key}={db_url}")

        self.env_path.write_text("\n".join(new_env_lines) + "\n", encoding="utf-8")

    def configure_manual(self, db_string: str):
        """Configures the database using a full connection string."""
        self.set_database_url(db_string)

    def configure_manual_parts(
        self,
        host: str = "localhost",
        port: int = 5432,
        user: str = "postgres",
        password: str = "",
        dbname: str = "hyprchan",
        driver: str = "asyncpg"
    ):
        """Assembles and saves a database URL from individual parts."""
        db_url = f"postgresql+{driver}://{user}:{password}@{host}:{port}/{dbname}"
        self.set_database_url(db_url)

    def install_docker(
        self,
        password: str = "mysecretpassword",
        port: int = 5432,
        container_name: str = "hyprchan-postgres",
        dbname: str = "hyprchan"
    ) -> bool:
        """
        Attempts to start a PostgreSQL container with pgvector using Docker.
        Returns True if successful.
        """
        if not is_docker_available():
            return False

        # Use an image that already includes pgvector for convenience
        image = "ankane/pgvector:latest"

        try:
            # Check if container already exists
            result = subprocess.run(
                ["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
                capture_output=True, text=True, check=True
            )

            if container_name in result.stdout:
                # If it exists, try to start it
                subprocess.run(["docker", "start", container_name], check=True)
            else:
                # Pull and run new container
                subprocess.run([
                    "docker", "run", "--name", container_name,
                    "-e", f"POSTGRES_PASSWORD={password}",
                    "-e", f"POSTGRES_DB={dbname}",
                    "-p", f"{port}:5432",
                    "-d", image
                ], check=True)

            # Wait a bit for PG to wake up
            time.sleep(3)

            # Save to config
            self.configure_manual_parts(password=password, port=port, dbname=dbname)

            # Try to enable pgvector automatically
            self.enable_pgvector_docker(container_name, dbname)

            return True
        except subprocess.CalledProcessError:
            return False

    def enable_pgvector_docker(self, container_name: str, dbname: str):
        """Runs the CREATE EXTENSION command inside a docker container."""
        try:
            subprocess.run([
                "docker", "exec", "-it", container_name,
                "psql", "-U", "postgres", "-d", dbname,
                "-c", "CREATE EXTENSION IF NOT EXISTS vector;"
            ], check=True)
        except subprocess.CalledProcessError:
            # Might fail if we're not postgres user or extension missing in image
            pass

    def enable_pgvector_local(self, dbname: str, user: str = "postgres"):
        """Attempts to enable pgvector using local psql command."""
        try:
            subprocess.run([
                "psql", "-U", user, "-d", dbname,
                "-c", "CREATE EXTENSION IF NOT EXISTS vector;"
            ], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
