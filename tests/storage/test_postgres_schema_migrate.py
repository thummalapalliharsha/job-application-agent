from __future__ import annotations

import unittest
from unittest.mock import Mock

from postgres_config import PostgresConfig
from postgres_schema_migrate import (
    APPROVED_DATABASE,
    APPROVED_HOST,
    APPROVED_PORT,
    APPROVED_USER,
    REQUIRED_COLUMNS,
    REQUIRED_PRIMARY_KEYS,
    REQUIRED_UNIQUE_KEYS,
    REQUIRED_CHECK_CONSTRAINTS,
    REQUIRED_NOT_NULL_COLUMNS,
    REQUIRED_TYPES,
    SchemaMigrationError,
    apply_schema_only,
)


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.one = None
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, sql, params=None):
        statement = " ".join(sql.split()).casefold()
        self.one = None
        self.rows = []
        if statement.startswith("select current_database()"):
            self.one = (APPROVED_DATABASE, APPROVED_USER, 160015)
        elif statement.startswith("select c.relname, c.relkind"):
            self.rows = list(self.connection.relations)
        elif statement.startswith("select table_name, column_name, data_type, is_identity"):
            selected_tables = set(params[0])
            self.rows = [
                (
                    table,
                    column,
                    REQUIRED_TYPES.get((table, column), "text"),
                    "YES" if (table, column) == ("document_history_records", "history_position") else "NO",
                    "NO" if column in REQUIRED_NOT_NULL_COLUMNS[table] else "YES",
                )
                for table, columns in REQUIRED_COLUMNS.items()
                if table in selected_tables
                for column in columns
            ]
            if self.connection.incompatible:
                self.rows = [
                    (table, column, "integer" if (table, column) == ("document_history_records", "document_id") else data_type, identity, nullable)
                    for table, column, data_type, identity, nullable in self.rows
                ]
            if self.connection.nullable_column:
                target_table, target_column = self.connection.nullable_column
                self.rows = [
                    (
                        table, column, data_type, identity,
                        "YES" if (table, column) == (target_table, target_column) else nullable,
                    )
                    for table, column, data_type, identity, nullable in self.rows
                ]
        elif statement.startswith("select tc.table_name, tc.constraint_type"):
            selected_tables = set(params[0])
            self.rows = [
                (table, "PRIMARY KEY", ",".join(columns))
                for table, columns in REQUIRED_PRIMARY_KEYS.items()
                if table in selected_tables
            ]
            self.rows.extend(
                (table, "UNIQUE", ",".join(columns))
                for table, constraints in REQUIRED_UNIQUE_KEYS.items()
                if table in selected_tables
                for columns in constraints
            )
        elif statement.startswith("select c.relname, con.conname"):
            selected_tables = set(params[0])
            self.rows = [
                (table, name, definition)
                for table, constraints in REQUIRED_CHECK_CONSTRAINTS.items()
                if table in selected_tables and not self.connection.missing_status_check
                for name, definition in constraints.items()
            ]
        elif statement.startswith("create table if not exists"):
            if self.connection.fail_schema:
                raise RuntimeError("injected schema DDL failure")
            self.connection.schema_applications += 1
            self.connection.schema_present = True
        else:
            raise AssertionError(f"Unexpected SQL: {statement}")

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.rows


class FakeTransaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.snapshot = (
            self.connection.schema_present,
            self.connection.schema_applications,
        )
        return self.connection

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self.connection.commits += 1
        else:
            self.connection.rollbacks += 1
            (
                self.connection.schema_present,
                self.connection.schema_applications,
            ) = self.connection.snapshot
        return False


class FakeConnection:
    def __init__(
        self,
        *,
        relations=(),
        fail_schema=False,
        incompatible=False,
        nullable_column=None,
        missing_status_check=False,
    ):
        self.relations = relations
        self.fail_schema = fail_schema
        self.incompatible = incompatible
        self.nullable_column = nullable_column
        self.missing_status_check = missing_status_check
        self.schema_present = False
        self.schema_applications = 0
        self.commits = 0
        self.rollbacks = 0
        self.snapshot = None

    def transaction(self):
        return FakeTransaction(self)

    def cursor(self):
        return FakeCursor(self)


def make_client(connection):
    client = Mock()
    client.config = PostgresConfig(
        backend="postgres",
        host=APPROVED_HOST,
        port=APPROVED_PORT,
        database=APPROVED_DATABASE,
        user=APPROVED_USER,
        password="test-only",
        url="",
        sslmode="disable",
    )
    client._connection_kwargs.return_value = {
        "host": APPROVED_HOST,
        "port": APPROVED_PORT,
        "dbname": APPROVED_DATABASE,
        "user": APPROVED_USER,
        "password": "test-only",
    }
    client.connect.return_value = connection
    return client


class PostgresSchemaMigrationTests(unittest.TestCase):
    def test_schema_application_is_repeatable(self):
        connection = FakeConnection()
        client = make_client(connection)

        apply_schema_only(client, confirmed_disposable=True)
        apply_schema_only(client, confirmed_disposable=True)

        self.assertEqual(connection.schema_applications, 2)
        self.assertEqual(connection.commits, 2)
        self.assertEqual(connection.rollbacks, 0)

    def test_schema_ddl_failure_rolls_back(self):
        connection = FakeConnection(fail_schema=True)
        client = make_client(connection)

        with self.assertRaisesRegex(RuntimeError, "injected schema DDL failure"):
            apply_schema_only(client, confirmed_disposable=True)

        self.assertFalse(connection.schema_present)
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)

    def test_incompatible_existing_schema_rolls_back(self):
        connection = FakeConnection(incompatible=True)
        client = make_client(connection)

        with self.assertRaisesRegex(SchemaMigrationError, "incompatible types"):
            apply_schema_only(client, confirmed_disposable=True)

        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)

    def test_incompatible_existing_relation_is_rejected_before_ddl(self):
        connection = FakeConnection(relations=[("application_records", "v")])
        client = make_client(connection)

        with self.assertRaisesRegex(SchemaMigrationError, "incompatible PostgreSQL objects"):
            apply_schema_only(client, confirmed_disposable=True)

        self.assertEqual(connection.schema_applications, 0)
        self.assertEqual(connection.rollbacks, 1)

    def test_missing_existing_check_constraint_is_rejected_before_ddl(self):
        connection = FakeConnection(
            relations=[("backfill_runs", "r")],
            missing_status_check=True,
        )
        client = make_client(connection)

        with self.assertRaisesRegex(SchemaMigrationError, "check constraints"):
            apply_schema_only(client, confirmed_disposable=True)

        self.assertEqual(connection.schema_applications, 0)
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)

    def test_incorrect_existing_nullability_is_rejected_before_ddl(self):
        connection = FakeConnection(
            relations=[("backfill_runs", "r")],
            nullable_column=("backfill_runs", "status"),
        )
        client = make_client(connection)

        with self.assertRaisesRegex(SchemaMigrationError, "nullability"):
            apply_schema_only(client, confirmed_disposable=True)

        self.assertEqual(connection.schema_applications, 0)
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)

    def test_compatible_existing_schema_remains_valid(self):
        connection = FakeConnection(relations=[("backfill_runs", "r")])
        client = make_client(connection)

        apply_schema_only(client, confirmed_disposable=True)

        self.assertEqual(connection.schema_applications, 1)
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)

    def test_remote_target_is_rejected_without_connecting(self):
        connection = FakeConnection()
        client = make_client(connection)
        client.config = PostgresConfig(
            backend="postgres",
            host="db.example.invalid",
            port=55432,
            database=APPROVED_DATABASE,
            user=APPROVED_USER,
            password="test-only",
            url="",
            sslmode="disable",
        )

        with self.assertRaisesRegex(SchemaMigrationError, "exactly match"):
            apply_schema_only(client, confirmed_disposable=True)

        client.connect.assert_not_called()

    def test_disposable_confirmation_is_required(self):
        client = make_client(FakeConnection())

        with self.assertRaisesRegex(SchemaMigrationError, "confirmation is required"):
            apply_schema_only(client, confirmed_disposable=False)

        client.connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
