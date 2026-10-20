"""Unit tests for the temporary PostgreSQL diagnostic; no live database is used."""
from __future__ import annotations

import http.client
import json
import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch

import career_os_api as api
from postgres_config import PostgresConfig
from postgres_storage_adapter import (
    PostgresApplicationTableMissingError,
    PostgresStorageAdapter,
)


class FakeReadOnlyCursor:
    def __init__(self):
        self.statements = []
        self.params = None
        self.query_error = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, params=None):
        normalized = " ".join(statement.split()).casefold()
        self.statements.append(normalized)
        if params is not None:
            self.params = params
        if self.query_error is not None and normalized.startswith("select current_database()"):
            raise self.query_error

    def fetchone(self):
        return (
            "career_os_test",
            "diagnostic_user",
            "public",
            "PostgreSQL test version",
            8,
            True,
        )


class FakeReadOnlyConnection:
    def __init__(self):
        self.info = SimpleNamespace(host="db.example.test")
        self.cursor_instance = FakeReadOnlyCursor()

    @contextmanager
    def transaction(self):
        yield self

    def cursor(self):
        return self.cursor_instance


class FakeUndefinedTableError(RuntimeError):
    sqlstate = "42P01"


class PostgresDiagnosticApiTests(unittest.TestCase):
    token = "test-diagnostic-token"

    def request_diagnostic(self, headers=None):
        server = ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
        host = f"127.0.0.1:{server.server_port}"
        original_hosts = set(api._ALLOWED_HOSTS)
        api._ALLOWED_HOSTS.add(host)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            connection.request(
                "GET",
                api._POSTGRES_DIAGNOSTIC_PATH,
                headers=headers or {},
            )
            response = connection.getresponse()
            result = json.loads(response.read().decode("utf-8"))
            connection.close()
            return response.status, result
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            api._ALLOWED_HOSTS.clear()
            api._ALLOWED_HOSTS.update(original_hosts)

    def test_endpoint_requires_existing_bearer_token(self):
        with (
            patch.object(api, "_API_TOKEN", self.token),
            patch.dict(
                "os.environ",
                {api._POSTGRES_DIAGNOSTIC_ENABLED_ENV: "1"},
            ),
            patch.object(api.aa, "_application_store_adapter") as adapter_factory,
        ):
            status, result = self.request_diagnostic()

        self.assertEqual(status, 401)
        self.assertEqual(result, {"error": "authentication required"})
        adapter_factory.assert_not_called()

    def test_endpoint_rejects_incorrect_bearer_token(self):
        with (
            patch.object(api, "_API_TOKEN", self.token),
            patch.dict(
                "os.environ",
                {api._POSTGRES_DIAGNOSTIC_ENABLED_ENV: "1"},
            ),
            patch.object(api.aa, "_application_store_adapter") as adapter_factory,
        ):
            status, result = self.request_diagnostic(
                {"Authorization": "Bearer incorrect-token"}
            )

        self.assertEqual(status, 401)
        self.assertEqual(result, {"error": "authentication required"})
        adapter_factory.assert_not_called()

    def test_endpoint_rejects_requests_when_api_token_is_unconfigured(self):
        with (
            patch.object(api, "_API_TOKEN", ""),
            patch.dict(
                "os.environ",
                {api._POSTGRES_DIAGNOSTIC_ENABLED_ENV: "1"},
            ),
            patch.object(api.aa, "_application_store_adapter") as adapter_factory,
        ):
            status, result = self.request_diagnostic(
                {"Authorization": "Bearer supplied-token"}
            )

        self.assertEqual(status, 401)
        self.assertEqual(result, {"error": "authentication required"})
        adapter_factory.assert_not_called()

    def test_endpoint_is_disabled_by_default(self):
        with (
            patch.object(api, "_API_TOKEN", self.token),
            patch.dict("os.environ") as environment,
            patch.object(api.aa, "_application_store_adapter") as adapter_factory,
        ):
            environment.pop(api._POSTGRES_DIAGNOSTIC_ENABLED_ENV, None)
            status, result = self.request_diagnostic(
                {"Authorization": f"Bearer {self.token}"}
            )

        self.assertEqual(status, 404)
        self.assertEqual(result, {"error": "not found"})
        adapter_factory.assert_not_called()

    def test_disabled_endpoint_returns_not_found_without_authentication(self):
        with (
            patch.object(api, "_API_TOKEN", self.token),
            patch.dict("os.environ") as environment,
            patch.object(api.aa, "_application_store_adapter") as adapter_factory,
        ):
            environment.pop(api._POSTGRES_DIAGNOSTIC_ENABLED_ENV, None)
            status, result = self.request_diagnostic()

        self.assertEqual(status, 404)
        self.assertEqual(result, {"error": "not found"})
        adapter_factory.assert_not_called()

    def test_endpoint_does_not_fall_back_to_file_storage(self):
        adapter = Mock()
        adapter.backend_name = "file"
        with (
            patch.object(api, "_API_TOKEN", self.token),
            patch.dict(
                "os.environ",
                {api._POSTGRES_DIAGNOSTIC_ENABLED_ENV: "1"},
            ),
            patch.object(api.aa, "_application_store_adapter", return_value=adapter),
        ):
            status, result = self.request_diagnostic(
                {"Authorization": f"Bearer {self.token}"}
            )

        self.assertEqual(status, 503)
        self.assertEqual(
            result,
            {"error": "PostgreSQL application storage is not selected."},
        )
        adapter.diagnostic_application_store.assert_not_called()

    def test_success_returns_only_read_only_database_facts(self):
        connection = FakeReadOnlyConnection()
        adapter = PostgresStorageAdapter(
            config=PostgresConfig(
                backend="postgres",
                url="postgresql://db.example.test/career_os_test",
            )
        )
        with (
            patch.object(api, "_API_TOKEN", self.token),
            patch.dict(
                "os.environ",
                {
                    api._POSTGRES_DIAGNOSTIC_ENABLED_ENV: "1",
                    "CAREER_OS_STORAGE_BACKEND": "postgres",
                },
            ),
            patch("postgres_storage_adapter.psycopg", object()),
            patch.object(adapter.client, "connect", return_value=connection),
            patch.object(adapter.client, "close") as close,
            patch.object(api.aa, "_application_store_adapter", return_value=adapter),
        ):
            status, result = self.request_diagnostic(
                {"Authorization": f"Bearer {self.token}"}
            )

        self.assertEqual(status, 200)
        self.assertEqual(
            result,
            {
                "host": "db.example.test",
                "database": "career_os_test",
                "user": "diagnostic_user",
                "schema": "public",
                "server_version": "PostgreSQL test version",
                "application_record_count": 8,
                "target_application_exists": True,
            },
        )
        statements = connection.cursor_instance.statements
        self.assertEqual(statements[0], "set transaction read only")
        self.assertIn("count(*) from public.application_records", statements[1])
        self.assertIn("from public.application_records", statements[1])
        self.assertEqual(
            connection.cursor_instance.params,
            ("app_16cd654e68f9",),
        )
        close.assert_called_once_with()

    def test_adapter_classifies_missing_application_table(self):
        connection = FakeReadOnlyConnection()
        connection.cursor_instance.query_error = FakeUndefinedTableError()
        adapter = PostgresStorageAdapter(
            config=PostgresConfig(
                backend="postgres",
                url="postgresql://db.example.test/career_os_test",
            )
        )
        with (
            patch.dict(
                "os.environ",
                {"CAREER_OS_STORAGE_BACKEND": "postgres"},
            ),
            patch("postgres_storage_adapter.psycopg", object()),
            patch.object(adapter.client, "connect", return_value=connection),
            patch.object(adapter.client, "close") as close,
        ):
            with self.assertRaisesRegex(
                PostgresApplicationTableMissingError,
                "public.application_records is missing",
            ):
                adapter.diagnostic_application_store("app_16cd654e68f9")

        close.assert_called_once_with()

    def test_missing_table_returns_clear_error_without_database_details(self):
        adapter = Mock()
        adapter.backend_name = "postgres"
        adapter.diagnostic_application_store.side_effect = (
            PostgresApplicationTableMissingError(
                "Expected table public.application_records is missing."
            )
        )
        with (
            patch.object(api, "_API_TOKEN", self.token),
            patch.dict(
                "os.environ",
                {api._POSTGRES_DIAGNOSTIC_ENABLED_ENV: "1"},
            ),
            patch.object(api.aa, "_application_store_adapter", return_value=adapter),
        ):
            status, result = self.request_diagnostic(
                {"Authorization": f"Bearer {self.token}"}
            )

        self.assertEqual(status, 503)
        self.assertEqual(
            result,
            {"error": "Expected table public.application_records is missing."},
        )

    def test_database_error_is_sanitized(self):
        adapter = Mock()
        adapter.backend_name = "postgres"
        adapter.diagnostic_application_store.side_effect = RuntimeError(
            "connection password must not be returned"
        )
        with (
            patch.object(api, "_API_TOKEN", self.token),
            patch.dict(
                "os.environ",
                {api._POSTGRES_DIAGNOSTIC_ENABLED_ENV: "1"},
            ),
            patch.object(api.aa, "_application_store_adapter", return_value=adapter),
        ):
            status, result = self.request_diagnostic(
                {"Authorization": f"Bearer {self.token}"}
            )

        self.assertEqual(status, 503)
        self.assertEqual(
            result,
            {
                "error": (
                    "PostgreSQL diagnostic query failed or the database is unavailable."
                )
            },
        )
        self.assertNotIn("password", json.dumps(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)
