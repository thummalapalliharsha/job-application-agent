import os
import unittest
from unittest.mock import patch

from postgres_client import PostgresClient, PostgresConfigurationError, PostgresUnavailableError, postgres_healthcheck
from postgres_config import PostgresConfig


class PostgresClientTests(unittest.TestCase):
    def test_valid_postgres_config_is_accepted(self):
        config = PostgresConfig(
            backend="postgres",
            host="db.example.internal",
            port=5432,
            database="career_os",
            user="app_user",
            password="s3cret",
            url="",
        )
        client = PostgresClient(config)
        self.assertTrue(client.is_configured)
        self.assertEqual(client.backend_name, "postgres")

    def test_missing_required_configuration_raises_clean_error(self):
        config = PostgresConfig(backend="postgres", host="", port=5432, database="", user="", password="", url="")
        client = PostgresClient(config)
        with self.assertRaises(PostgresConfigurationError):
            client.connect()

    def test_healthcheck_returns_ready_for_valid_configuration_when_connection_succeeds(self):
        config = PostgresConfig(
            backend="postgres",
            host="db.example.internal",
            port=5432,
            database="career_os",
            user="app_user",
            password="s3cret",
            url="",
        )

        class DummyCursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, query):
                self.query = query

        class DummyConnection:
            def cursor(self):
                return DummyCursor()

        client = PostgresClient(config)
        with patch("postgres_client.psycopg", create=True) as fake_psycopg:
            fake_psycopg.connect.return_value = DummyConnection()
            self.assertEqual(client.healthcheck()["ready"], True)
            self.assertEqual(client.healthcheck()["reachable"], True)
            self.assertIsNone(client.healthcheck()["error"])

    def test_healthcheck_returns_unreachable_when_backend_is_unavailable(self):
        config = PostgresConfig(
            backend="postgres",
            host="db.example.internal",
            port=5432,
            database="career_os",
            user="app_user",
            password="s3cret",
            url="",
        )
        client = PostgresClient(config)
        with patch("postgres_client.psycopg", None):
            result = client.healthcheck()
            self.assertFalse(result["ready"])
            self.assertFalse(result["reachable"])
            self.assertIn("installed", str(result["error"]))

    def test_non_postgres_backend_is_not_ready(self):
        config = PostgresConfig(backend="file")
        client = PostgresClient(config)
        self.assertEqual(client.healthcheck()["backend"], "file")
        self.assertFalse(client.healthcheck()["ready"])

    def test_production_readiness_fails_safely_when_db_unavailable(self):
        config = PostgresConfig(backend="postgres", host="db.example.internal", port=5432, database="career_os", user="app_user", password="s3cret")
        with patch("postgres_client.psycopg", None):
            result = postgres_healthcheck(config)
            self.assertFalse(result["ready"])
            self.assertFalse(result["reachable"])
            self.assertIn("installed", str(result["error"]))


if __name__ == "__main__":
    unittest.main()
