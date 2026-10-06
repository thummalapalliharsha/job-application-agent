"""Database configuration container and validation for the durable-storage adapter phase."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class PostgresConfig:
    """Environment-backed PostgreSQL configuration for a future storage adapter.

    This class intentionally validates configuration values only; it does not open a
    database connection or execute SQL.
    """

    backend: str = "file"
    host: str = ""
    port: int | None = None
    database: str = ""
    user: str = ""
    password: str = ""
    url: str = ""
    sslmode: str = "require"

    @property
    def is_configured(self) -> bool:
        return bool(self.url) or all(
            [self.host, self.database, self.user, self.password]
        )

    @property
    def is_postgres_backend(self) -> bool:
        return self.backend.casefold() == "postgres"

    @property
    def connection_kwargs(self) -> dict[str, object]:
        return {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "user": self.user,
            "password": self.password,
            "sslmode": self.sslmode,
        }


def _as_int(value: str | None, default: int | None = None) -> int | None:
    if value is None or value.strip() == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed


def load_postgres_config() -> PostgresConfig:
    backend = os.environ.get("CAREER_OS_STORAGE_BACKEND", "file").strip() or "file"
    url = (
        os.environ.get("POSTGRES_URL")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("CAREER_OS_POSTGRES_URL", "")
    ).strip()
    host = (
        os.environ.get("POSTGRES_HOST")
        or os.environ.get("PGHOST")
        or os.environ.get("CAREER_OS_POSTGRES_HOST", "")
    ).strip()
    database = (
        os.environ.get("POSTGRES_DB")
        or os.environ.get("PGDATABASE")
        or os.environ.get("CAREER_OS_POSTGRES_DB", "")
    ).strip()
    user = (
        os.environ.get("POSTGRES_USER")
        or os.environ.get("PGUSER")
        or os.environ.get("CAREER_OS_POSTGRES_USER", "")
    ).strip()
    password = (
        os.environ.get("POSTGRES_PASSWORD")
        or os.environ.get("PGPASSWORD")
        or os.environ.get("CAREER_OS_POSTGRES_PASSWORD", "")
    ).strip()
    port = _as_int(
        os.environ.get("POSTGRES_PORT")
        or os.environ.get("PGPORT")
        or os.environ.get("CAREER_OS_POSTGRES_PORT"),
        default=5432,
    )
    sslmode = (
        os.environ.get("POSTGRES_SSLMODE")
        or os.environ.get("PGSSLMODE")
        or os.environ.get("CAREER_OS_POSTGRES_SSLMODE", "require")
    ).strip() or "require"
    return PostgresConfig(
        backend=backend,
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        url=url,
        sslmode=sslmode,
    )


def validate_postgres_config(config: PostgresConfig | None = None) -> tuple[bool, list[str]]:
    """Return whether the env-backed config is valid enough to be used by a DB adapter.

    This is a configuration validation only; there is no connection attempt here.
    """
    resolved = config or load_postgres_config()
    missing: list[str] = []
    if resolved.backend.casefold() != "postgres":
        return False, []
    if resolved.url:
        return True, []
    if not resolved.host:
        missing.append("POSTGRES_HOST")
    if not resolved.database:
        missing.append("POSTGRES_DB")
    if not resolved.user:
        missing.append("POSTGRES_USER")
    if not resolved.password:
        missing.append("POSTGRES_PASSWORD")
    if resolved.port is None or not 1 <= resolved.port <= 65535:
        missing.append("POSTGRES_PORT")
    return not missing, missing


def postgres_storage_ready(config: PostgresConfig | None = None) -> bool:
    """Return True only when the PostgreSQL storage backend is configured and valid.

    This does not attempt database connectivity and is intentionally a readiness check
    for the adapter wiring phase.
    """
    ready, _ = validate_postgres_config(config)
    return ready


def storage_backend_mode() -> str:
    return (os.environ.get("CAREER_OS_STORAGE_BACKEND", "file") or "file").strip().lower() or "file"
