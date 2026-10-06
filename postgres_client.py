"""PostgreSQL connection wrapper used only for readiness and health checks.

This module intentionally does not create schema, table, or application data.
It is a connection abstraction for the durable-storage phase and performs no
application persistence operations.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Any

from postgres_config import PostgresConfig, load_postgres_config, validate_postgres_config

try:  # pragma: no cover - optional dependency for runtime-only integration.
    import psycopg
except ModuleNotFoundError:  # pragma: no cover
    psycopg = None


class PostgresConfigurationError(ValueError):
    """Raised when the PostgreSQL backend is configured incorrectly."""


class PostgresUnavailableError(RuntimeError):
    """Raised when PostgreSQL is configured but not reachable or dependencies are missing."""


class PostgresClient:
    """Very small client abstraction for readiness checks during startup.

    This is intentionally limited to connection, ping, healthcheck, and transaction
    wrappers. The storage adapter is not yet wired into persistent profile or
    application writes.
    """

    def __init__(self, config: PostgresConfig | None = None):
        self.config = config or load_postgres_config()
        self._connection: Any | None = None

    @property
    def backend_name(self) -> str:
        return self.config.backend.casefold() if self.config.backend else "file"

    @property
    def is_configured(self) -> bool:
        return self.config.backend.casefold() == "postgres" and self.config.is_configured

    def _require_configured_backend(self) -> None:
        if self.config.backend.casefold() != "postgres":
            raise PostgresConfigurationError("CAREER_OS_STORAGE_BACKEND must be set to postgres")
        if not self.config.is_configured and not self.config.url:
            raise PostgresConfigurationError("PostgreSQL connection settings are missing")

    def _connection_kwargs(self) -> dict[str, Any]:
        if self.config.url:
            return {"conninfo": self.config.url}
        kwargs = dict(self.config.connection_kwargs)
        kwargs.pop("sslmode", None)
        return kwargs

    def connect(self):
        """Create and cache a PostgreSQL connection when valid config is present."""
        self._require_configured_backend()
        if psycopg is None:
            raise PostgresUnavailableError("psycopg is not installed")
        if self._connection is not None:
            return self._connection
        try:
            self._connection = psycopg.connect(**self._connection_kwargs())
            return self._connection
        except Exception as exc:  # pragma: no cover - exercised via unit tests with mocks
            raise PostgresUnavailableError(str(exc)) from exc

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

    def ping(self) -> bool:
        """Return True if a simple database query succeeds."""
        if not self.is_configured:
            return False
        try:
            if psycopg is None:
                raise PostgresUnavailableError("psycopg is not installed")
            with psycopg.connect(**self._connection_kwargs()) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
            return True
        except Exception:
            return False

    def healthcheck(self) -> dict[str, Any]:
        """Return a deterministic readiness snapshot for startup verification.

        The output intentionally stays plain and stable for tests and safe startup logic.
        """
        if self.config.backend.casefold() != "postgres":
            return {
                "backend": "file",
                "configured": False,
                "ready": False,
                "reachable": False,
                "error": None,
            }
        if not self.config.is_configured and not self.config.url:
            return {
                "backend": "postgres",
                "configured": False,
                "ready": False,
                "reachable": False,
                "error": "PostgreSQL connection settings are missing",
            }
        try:
            if psycopg is None:
                raise PostgresUnavailableError("psycopg is not installed")
            with psycopg.connect(**self._connection_kwargs()) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
            return {
                "backend": "postgres",
                "configured": True,
                "ready": True,
                "reachable": True,
                "error": None,
            }
        except Exception as exc:
            return {
                "backend": "postgres",
                "configured": True,
                "ready": False,
                "reachable": False,
                "error": str(exc),
            }

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """Yield a live connection within a transaction context if a DB is available."""
        connection = self.connect()
        try:
            if hasattr(connection, "transaction"):
                with connection.transaction():
                    yield connection
            else:
                yield connection
        finally:
            if connection is not self._connection:
                try:
                    connection.close()
                except Exception:
                    pass


def build_postgres_client(config: PostgresConfig | None = None) -> PostgresClient:
    return PostgresClient(config=config or load_postgres_config())


def postgres_healthcheck(config: PostgresConfig | None = None) -> dict[str, Any]:
    client = build_postgres_client(config)
    return client.healthcheck()


def postgres_is_ready(config: PostgresConfig | None = None) -> bool:
    ready, _ = validate_postgres_config(config or load_postgres_config())
    return ready and build_postgres_client(config or load_postgres_config()).ping()
