"""Schema-only migration for the approved disposable local PostgreSQL target."""
from __future__ import annotations

import argparse
import re
from typing import Any

from postgres_client import PostgresClient
from postgres_config import PostgresConfig, load_postgres_config
from postgres_schema import postgres_schema_sql

APPROVED_HOST = "127.0.0.1"
APPROVED_PORT = 55432
APPROVED_DATABASE = "career_test"
APPROVED_USER = "career_test"
POSTGRES_MAJOR_VERSION = 16

EXPECTED_TABLES = {
    "profile_documents",
    "project_records",
    "skill_groups",
    "experience_records",
    "education_records",
    "certification_records",
    "application_records",
    "document_history_records",
    "document_history_migrations",
    "job_descriptions",
    "report_records",
    "quarantine_log",
    "backfill_runs",
}

REQUIRED_COLUMNS = {
    "profile_documents": {"scope", "payload_json", "updated_at", "source_hash"},
    "project_records": {"record_id", "payload_json", "updated_at"},
    "skill_groups": {"category", "payload_json", "updated_at"},
    "experience_records": {"record_id", "payload_json", "updated_at"},
    "education_records": {"record_id", "payload_json", "updated_at"},
    "certification_records": {"record_id", "payload_json", "updated_at"},
    "application_records": {
        "application_id", "payload_json", "job_description_reference",
        "phase8_plan_reference", "resume_reference", "cover_letter_reference",
        "selected_projects", "selected_skill_names", "updated_at",
    },
    "document_history_records": {
        "document_id", "application_id", "payload_json", "history_position",
        "created_at", "updated_at",
    },
    "document_history_migrations": {
        "migration_id", "source_sha256", "imported_count", "migrated_at",
    },
    "job_descriptions": {"path", "sha256", "updated_at"},
    "report_records": {"path", "sha256", "updated_at"},
    "quarantine_log": {
        "quarantine_id", "manifest_run_id", "record_type", "record_id",
        "application_id", "reason", "payload_json", "quarantined_at",
    },
    "backfill_runs": {
        "run_id", "run_label", "manifest_run_id", "target_env", "manifest_json",
        "valid_record_count", "quarantined_record_count", "started_at",
        "completed_at", "status",
    },
}

REQUIRED_TYPES = {
    ("profile_documents", "scope"): "text",
    ("profile_documents", "payload_json"): "jsonb",
    ("profile_documents", "updated_at"): "timestamp with time zone",
    ("profile_documents", "source_hash"): "character",
    ("project_records", "record_id"): "text",
    ("project_records", "payload_json"): "jsonb",
    ("project_records", "updated_at"): "timestamp with time zone",
    ("skill_groups", "category"): "text",
    ("skill_groups", "payload_json"): "jsonb",
    ("skill_groups", "updated_at"): "timestamp with time zone",
    ("experience_records", "record_id"): "text",
    ("experience_records", "payload_json"): "jsonb",
    ("experience_records", "updated_at"): "timestamp with time zone",
    ("education_records", "record_id"): "text",
    ("education_records", "payload_json"): "jsonb",
    ("education_records", "updated_at"): "timestamp with time zone",
    ("certification_records", "record_id"): "text",
    ("certification_records", "payload_json"): "jsonb",
    ("certification_records", "updated_at"): "timestamp with time zone",
    ("application_records", "application_id"): "text",
    ("application_records", "payload_json"): "jsonb",
    ("application_records", "job_description_reference"): "text",
    ("application_records", "phase8_plan_reference"): "text",
    ("application_records", "resume_reference"): "text",
    ("application_records", "cover_letter_reference"): "text",
    ("application_records", "selected_projects"): "jsonb",
    ("application_records", "selected_skill_names"): "jsonb",
    ("application_records", "updated_at"): "timestamp with time zone",
    ("document_history_records", "document_id"): "text",
    ("document_history_records", "application_id"): "text",
    ("document_history_records", "payload_json"): "jsonb",
    ("document_history_records", "history_position"): "bigint",
    ("document_history_records", "created_at"): "timestamp with time zone",
    ("document_history_records", "updated_at"): "timestamp with time zone",
    ("document_history_migrations", "migration_id"): "text",
    ("document_history_migrations", "source_sha256"): "character",
    ("document_history_migrations", "imported_count"): "integer",
    ("document_history_migrations", "migrated_at"): "timestamp with time zone",
    ("job_descriptions", "path"): "text",
    ("job_descriptions", "sha256"): "character",
    ("job_descriptions", "updated_at"): "timestamp with time zone",
    ("report_records", "path"): "text",
    ("report_records", "sha256"): "character",
    ("report_records", "updated_at"): "timestamp with time zone",
    ("quarantine_log", "quarantine_id"): "bigint",
    ("quarantine_log", "manifest_run_id"): "text",
    ("quarantine_log", "record_type"): "text",
    ("quarantine_log", "record_id"): "text",
    ("quarantine_log", "application_id"): "text",
    ("quarantine_log", "reason"): "text",
    ("quarantine_log", "payload_json"): "jsonb",
    ("quarantine_log", "quarantined_at"): "timestamp with time zone",
    ("backfill_runs", "run_id"): "bigint",
    ("backfill_runs", "run_label"): "text",
    ("backfill_runs", "manifest_run_id"): "text",
    ("backfill_runs", "target_env"): "text",
    ("backfill_runs", "manifest_json"): "jsonb",
    ("backfill_runs", "valid_record_count"): "integer",
    ("backfill_runs", "quarantined_record_count"): "integer",
    ("backfill_runs", "started_at"): "timestamp with time zone",
    ("backfill_runs", "completed_at"): "timestamp with time zone",
    ("backfill_runs", "status"): "text",
}

REQUIRED_PRIMARY_KEYS = {
    "profile_documents": ("scope",),
    "project_records": ("record_id",),
    "skill_groups": ("category",),
    "experience_records": ("record_id",),
    "education_records": ("record_id",),
    "certification_records": ("record_id",),
    "application_records": ("application_id",),
    "document_history_records": ("document_id",),
    "document_history_migrations": ("migration_id",),
    "job_descriptions": ("path",),
    "report_records": ("path",),
    "quarantine_log": ("quarantine_id",),
    "backfill_runs": ("run_id",),
}

REQUIRED_UNIQUE_KEYS = {
    "quarantine_log": {
        ("manifest_run_id", "record_type", "record_id", "application_id", "reason"),
    },
    "backfill_runs": {("manifest_run_id",)},
}

REQUIRED_NOT_NULL_COLUMNS = {
    "profile_documents": {"scope", "payload_json", "updated_at"},
    "project_records": {"record_id", "payload_json", "updated_at"},
    "skill_groups": {"category", "payload_json", "updated_at"},
    "experience_records": {"record_id", "payload_json", "updated_at"},
    "education_records": {"record_id", "payload_json", "updated_at"},
    "certification_records": {"record_id", "payload_json", "updated_at"},
    "application_records": {"application_id", "payload_json", "updated_at"},
    "document_history_records": {
        "document_id", "application_id", "payload_json", "history_position",
        "created_at", "updated_at",
    },
    "document_history_migrations": {
        "migration_id", "source_sha256", "imported_count", "migrated_at",
    },
    "job_descriptions": {"path", "sha256", "updated_at"},
    "report_records": {"path", "sha256", "updated_at"},
    "quarantine_log": {
        "quarantine_id", "manifest_run_id", "record_type", "reason", "quarantined_at",
    },
    "backfill_runs": {
        "run_id", "run_label", "manifest_run_id", "target_env", "manifest_json",
        "valid_record_count", "quarantined_record_count", "started_at", "status",
    },
}

REQUIRED_CHECK_CONSTRAINTS = {
    "backfill_runs": {
        "backfill_runs_status_check":
            "CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, "
            "'success'::text, 'failed'::text, 'rolled_back'::text])))",
    },
}


class SchemaMigrationError(RuntimeError):
    """Raised when the target or existing schema is not safe for migration."""


def validate_approved_target(
    config: PostgresConfig,
    *,
    confirmed_disposable: bool,
    expected_host: str,
    expected_port: int,
    expected_database: str,
    expected_user: str,
) -> None:
    if not confirmed_disposable:
        raise SchemaMigrationError("Explicit disposable-target confirmation is required.")
    if config.backend.casefold() != "postgres":
        raise SchemaMigrationError("CAREER_OS_STORAGE_BACKEND must be postgres.")
    if config.url:
        raise SchemaMigrationError("Connection URLs are forbidden; use explicit local connection fields.")
    actual = (config.host, config.port, config.database, config.user)
    expected = (expected_host, expected_port, expected_database, expected_user)
    approved = (APPROVED_HOST, APPROVED_PORT, APPROVED_DATABASE, APPROVED_USER)
    if actual != expected or expected != approved:
        raise SchemaMigrationError(
            "Configured and confirmed target must exactly match the approved disposable local database."
        )


def _validate_existing_relations(cursor: Any) -> set[str]:
    cursor.execute(
        """
        SELECT c.relname, c.relkind
        FROM pg_class AS c
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = ANY(%s)
        """,
        (sorted(EXPECTED_TABLES),),
    )
    relations = cursor.fetchall()
    incompatible = [
        name for name, kind in relations
        if kind not in {"r", "p"}
    ]
    if incompatible:
        raise SchemaMigrationError(
            "Expected table names are occupied by incompatible PostgreSQL objects: "
            + ", ".join(sorted(incompatible))
        )
    return {name for name, _ in relations}


def _normalize_check_definition(definition: str) -> str:
    return re.sub(r"\s+", "", definition.casefold()).replace("::text", "")


def _validate_schema(
    cursor: Any,
    table_names: set[str],
    *,
    allow_missing_columns: set[tuple[str, str]] | None = None,
) -> None:
    if not table_names:
        return
    allowed_missing = allow_missing_columns or set()
    cursor.execute(
        """
        SELECT table_name, column_name, data_type, is_identity, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = ANY(%s)
        """,
        (sorted(table_names),),
    )
    observed: dict[str, dict[str, tuple[str, str, str]]] = {}
    for table_name, column_name, data_type, is_identity, is_nullable in cursor.fetchall():
        observed.setdefault(table_name, {})[column_name] = (
            data_type, is_identity, is_nullable,
        )

    missing = {
        table: columns_missing
        for table, columns_missing in {
            table: sorted(
                (columns - set(observed.get(table, {})))
                - {column for target, column in allowed_missing if target == table}
            )
            for table, columns in REQUIRED_COLUMNS.items()
            if table in table_names
        }.items()
        if columns_missing
    }
    if missing:
        raise SchemaMigrationError(f"Schema is missing required columns: {missing}")

    incompatible = {
        f"{table}.{column}": observed[table][column][0]
        for (table, column), expected_type in REQUIRED_TYPES.items()
        if table in table_names
        if column in observed.get(table, {})
        if observed[table][column][0] != expected_type
    }
    if incompatible:
        raise SchemaMigrationError(f"Schema columns have incompatible types: {incompatible}")
    invalid_nullability = {
        f"{table}.{column}": observed[table][column][2]
        for table in table_names
        for column in REQUIRED_COLUMNS[table]
        if column in observed.get(table, {})
        if observed[table][column][2]
        != ("NO" if column in REQUIRED_NOT_NULL_COLUMNS[table] else "YES")
    }
    if invalid_nullability:
        raise SchemaMigrationError(
            f"Schema columns have incompatible nullability: {invalid_nullability}"
        )
    if (
        "document_history_records" in table_names
        and "history_position" in observed.get("document_history_records", {})
        and observed["document_history_records"]["history_position"][1] != "YES"
    ):
        raise SchemaMigrationError(
            "document_history_records.history_position must be an identity column."
        )
    cursor.execute(
        """
        SELECT tc.table_name, tc.constraint_type,
               string_agg(kcu.column_name, ',' ORDER BY kcu.ordinal_position)
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
         AND tc.table_name = kcu.table_name
        WHERE tc.table_schema = 'public'
          AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE')
          AND tc.table_name = ANY(%s)
        GROUP BY tc.table_name, tc.constraint_type
        """,
        (sorted(table_names),),
    )
    keys: dict[str, set[tuple[str, ...]]] = {}
    primary_keys: dict[str, tuple[str, ...]] = {}
    for table, constraint_type, columns in cursor.fetchall():
        column_tuple = tuple(columns.split(","))
        keys.setdefault(table, set()).add(column_tuple)
        if constraint_type == "PRIMARY KEY":
            primary_keys[table] = column_tuple
    invalid_keys = {
        table: primary_keys.get(table)
        for table, expected in REQUIRED_PRIMARY_KEYS.items()
        if table in table_names
        if primary_keys.get(table, ()) != expected
    }
    if invalid_keys:
        raise SchemaMigrationError(f"Schema has missing or incompatible primary keys: {invalid_keys}")
    invalid_unique_keys = {
        table: sorted(expected - keys.get(table, set()))
        for table, expected in REQUIRED_UNIQUE_KEYS.items()
        if table in table_names
        if expected - keys.get(table, set())
    }
    if invalid_unique_keys:
        raise SchemaMigrationError(
            f"Schema has missing required unique constraints: {invalid_unique_keys}"
        )
    cursor.execute(
        """
        SELECT c.relname, con.conname, pg_get_constraintdef(con.oid)
        FROM pg_constraint AS con
        JOIN pg_class AS c ON c.oid = con.conrelid
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND con.contype = 'c'
          AND c.relname = ANY(%s)
        """,
        (sorted(table_names),),
    )
    observed_checks: dict[str, dict[str, str]] = {}
    for table, name, definition in cursor.fetchall():
        observed_checks.setdefault(table, {})[name] = _normalize_check_definition(definition)
    invalid_checks = {
        f"{table}.{name}": observed_checks.get(table, {}).get(name)
        for table, constraints in REQUIRED_CHECK_CONSTRAINTS.items()
        if table in table_names
        for name, definition in constraints.items()
        if observed_checks.get(table, {}).get(name) != _normalize_check_definition(definition)
    }
    if invalid_checks:
        raise SchemaMigrationError(
            f"Schema has missing or incompatible check constraints: {invalid_checks}"
        )


def _validate_created_schema(cursor: Any) -> None:
    _validate_schema(cursor, EXPECTED_TABLES)


def apply_schema_only(
    client: PostgresClient,
    *,
    confirmed_disposable: bool,
    expected_host: str = APPROVED_HOST,
    expected_port: int = APPROVED_PORT,
    expected_database: str = APPROVED_DATABASE,
    expected_user: str = APPROVED_USER,
) -> None:
    """Apply additive schema only, verifying the exact local target before DDL."""
    validate_approved_target(
        client.config,
        confirmed_disposable=confirmed_disposable,
        expected_host=expected_host,
        expected_port=expected_port,
        expected_database=expected_database,
        expected_user=expected_user,
    )
    connection_kwargs = client._connection_kwargs()
    if (
        connection_kwargs.get("host") != APPROVED_HOST
        or connection_kwargs.get("port") != APPROVED_PORT
        or connection_kwargs.get("dbname") != APPROVED_DATABASE
        or connection_kwargs.get("user") != APPROVED_USER
        or "conninfo" in connection_kwargs
    ):
        raise SchemaMigrationError("PostgreSQL connection arguments are not the approved local target.")

    connection = client.connect()
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT current_database(), current_user,
                       current_setting('server_version_num')::integer
                """
            )
            identity = cursor.fetchone()
            if identity is None:
                raise SchemaMigrationError("Could not verify connected PostgreSQL identity.")
            database, user, version_number = identity
            if (database, user) != (APPROVED_DATABASE, APPROVED_USER):
                raise SchemaMigrationError("Connected database identity does not match the approved target.")
            if version_number // 10000 != POSTGRES_MAJOR_VERSION:
                raise SchemaMigrationError("The approved target must be PostgreSQL 16.")

            existing_tables = _validate_existing_relations(cursor)
            _validate_schema(
                cursor,
                existing_tables,
                allow_missing_columns={
                    ("document_history_records", "created_at"),
                    ("document_history_records", "history_position"),
                },
            )
            cursor.execute(postgres_schema_sql())
            _validate_created_schema(cursor)


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply schema only to the approved disposable local PostgreSQL database.")
    parser.add_argument("--confirm-disposable", action="store_true", required=True)
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--expected-port", required=True, type=int)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--expected-user", required=True)
    args = parser.parse_args()
    config = load_postgres_config()
    client = PostgresClient(config)
    try:
        apply_schema_only(
            client,
            confirmed_disposable=args.confirm_disposable,
            expected_host=args.expected_host,
            expected_port=args.expected_port,
            expected_database=args.expected_database,
            expected_user=args.expected_user,
        )
    finally:
        client.close()
    print("Schema-only migration completed and verified for the approved local disposable database.")


if __name__ == "__main__":
    main()
