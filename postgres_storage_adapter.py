from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable
import uuid

from postgres_client import PostgresClient
from postgres_config import PostgresConfig, load_postgres_config
from storage_adapter import (
    EMPTY_APPLICATION_STORE,
    EMPTY_PROFILE_DOCUMENTS,
    PROFILE_DOCUMENT_CATEGORIES,
    DocumentHistoryConflictError,
    DocumentHistoryError,
    DocumentHistoryMigrationError,
    StorageAdapter,
    _normalize_document_history,
    profile_documents_revision,
)


class PostgresApplicationTableMissingError(RuntimeError):
    """Raised when the diagnostic's expected public application table is absent."""


LEGACY_DOCUMENT_HISTORY_MIGRATION_ID = "legacy_document_history_v1"


def import_legacy_document_history(cursor: Any, data_dir: str | Path) -> None:
    path = Path(data_dir) / "document_history.json"
    try:
        source_bytes = path.read_bytes()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise DocumentHistoryMigrationError(
            f"Legacy document history could not be read safely: {exc}"
        ) from exc

    source_hash = hashlib.sha256(source_bytes).hexdigest()
    cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", (184123, 1))
    cursor.execute(
        "SELECT source_sha256 FROM document_history_migrations WHERE migration_id = %s FOR UPDATE",
        (LEGACY_DOCUMENT_HISTORY_MIGRATION_ID,),
    )
    migration = cursor.fetchone()
    if migration is not None:
        recorded_hash = migration[0].strip() if isinstance(migration[0], str) else migration[0]
        if recorded_hash != source_hash:
            raise DocumentHistoryMigrationError(
                "Legacy document history changed after import; reconcile it explicitly before continuing."
            )
        return

    try:
        parsed = json.loads(source_bytes.decode("utf-8"))
        if not isinstance(parsed, dict) or set(parsed) != {"documents"}:
            raise DocumentHistoryMigrationError(
                "Legacy document history must contain only the documents collection."
            )
        history = _normalize_document_history(parsed, require_application_id=True)
    except (UnicodeError, json.JSONDecodeError, DocumentHistoryError) as exc:
        raise DocumentHistoryMigrationError(
            f"Legacy document history is malformed or invalid; it was not imported: {exc}"
        ) from exc

    cursor.execute("LOCK TABLE document_history_records IN SHARE ROW EXCLUSIVE MODE")
    cursor.execute("SELECT COUNT(*) FROM document_history_records")
    if cursor.fetchone()[0]:
        raise DocumentHistoryConflictError(
            "PostgreSQL already contains document history without a migration record; "
            "refusing to merge or overwrite it."
        )

    for item in history["documents"]:
        _insert_document_history_entry(cursor, item)
    cursor.execute(
        """
        INSERT INTO document_history_migrations
            (migration_id, source_sha256, imported_count)
        VALUES (%s, %s, %s)
        """,
        (
            LEGACY_DOCUMENT_HISTORY_MIGRATION_ID,
            source_hash,
            len(history["documents"]),
        ),
    )


def _insert_document_history_entry(cursor: Any, entry: dict[str, Any]) -> None:
    application_id = entry.get("application_id")
    document_id = entry.get("document_id")
    if not isinstance(application_id, str) or not application_id:
        raise DocumentHistoryError("Document-history entries require an application_id.")
    if not isinstance(document_id, str) or not document_id:
        raise DocumentHistoryError("Document-history entries require a document_id.")
    cursor.execute(
        """
        INSERT INTO document_history_records
            (document_id, application_id, payload_json, created_at, updated_at)
        VALUES (%s, %s, %s, now(), now())
        """,
        (
            document_id,
            application_id,
            json.dumps(entry, ensure_ascii=False, sort_keys=True, allow_nan=False),
        ),
    )


try:  # pragma: no cover - optional runtime dependency for staging only.
    import psycopg
except ModuleNotFoundError:  # pragma: no cover
    psycopg = None


class PostgresStorageAdapter(StorageAdapter):
    """PostgreSQL metadata adapter with row-scoped application mutations.

    PostgreSQL selection fails closed; application records are read and mutated through
    transactional per-record operations rather than replaying full application snapshots.
    """

    backend_name = "postgres"
    _NORMALIZED_PROFILE_TABLES = (
        ("projects", "projects", "project_records", "record_id"),
        ("skills", "skill_groups", "skill_groups", "category"),
        ("experience", "experiences", "experience_records", "record_id"),
        ("education", "education", "education_records", "record_id"),
        ("certifications", "certifications", "certification_records", "record_id"),
    )

    def __init__(self, root: str | Path | None = None, config: PostgresConfig | None = None):
        super().__init__(root=root)
        self.data_dir = self.root / "data"
        self.config = config or load_postgres_config()
        self.client = PostgresClient(self.config)

    def _require_postgres_backend(self) -> None:
        backend = (os.environ.get("CAREER_OS_STORAGE_BACKEND", "file") or "file").strip().lower()
        if backend != "postgres":
            raise RuntimeError("CAREER_OS_STORAGE_BACKEND must be set to postgres for PostgresStorageAdapter use.")
        if self.config is None or not self.config.is_configured:
            raise RuntimeError("PostgreSQL configuration is missing or incomplete.")
        if psycopg is None:
            raise RuntimeError("psycopg is not installed for PostgreSQL storage.")

    def _ensure_ready(self) -> None:
        self._require_postgres_backend()
        health = self.client.healthcheck()
        if not health.get("ready") or not health.get("reachable") or health.get("error") is not None:
            raise RuntimeError("PostgreSQL application storage is unavailable.")

    def is_ready(self) -> bool:
        backend = (os.environ.get("CAREER_OS_STORAGE_BACKEND", "file") or "file").strip().lower()
        if backend != "postgres":
            return False
        if self.config is None or not self.config.is_configured:
            return False
        if psycopg is None:
            return False
        try:
            health = self.client.healthcheck()
        except Exception:
            return False
        return bool(health.get("ready")) and bool(health.get("reachable")) and health.get("error") is None

    def validate(self) -> list[str]:
        backend = (os.environ.get("CAREER_OS_STORAGE_BACKEND", "file") or "file").strip().lower()
        if backend != "postgres":
            return ["CAREER_OS_STORAGE_BACKEND is not configured for PostgreSQL."]
        if self.config is None or not self.config.is_configured:
            return ["PostgreSQL staging configuration is missing or incomplete."]
        if psycopg is None:
            return ["psycopg is not installed."]
        try:
            health = self.client.healthcheck()
        except Exception as exc:  # pragma: no cover - runtime-only integration path
            return [f"PostgreSQL healthcheck failed: {exc}"]
        if not health.get("ready") or not health.get("reachable") or health.get("error") is not None:
            return [f"PostgreSQL staging healthcheck failed: {health}"]
        return []

    def _fetch_json_rows(self, scope: str) -> dict[str, Any]:
        self._ensure_ready()
        with self.client.connect().cursor() as cursor:
            cursor.execute(
                "SELECT payload_json FROM profile_documents WHERE scope = %s ORDER BY scope LIMIT 1",
                (scope,),
            )
            row = cursor.fetchone()
        if row is None:
            return copy.deepcopy(EMPTY_PROFILE_DOCUMENTS.get(scope, {}))
        return json.loads(row[0]) if isinstance(row[0], str) else row[0]

    @staticmethod
    def _decode_payload(payload: Any) -> dict[str, Any] | None:
        decoded = json.loads(payload) if isinstance(payload, str) else payload
        return decoded if isinstance(decoded, dict) else None

    def load_profile_documents(self) -> dict[str, Any]:
        self._ensure_ready()
        connection = self.client.connect()
        with connection.transaction():
            with connection.cursor() as cursor:
                return self._load_profile_documents(cursor)

    def _load_profile_documents(self, cursor: Any) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for scope in ("master_profile", "achievements"):
            cursor.execute(
                "SELECT payload_json FROM profile_documents WHERE scope = %s",
                (scope,),
            )
            row = cursor.fetchone()
            result[scope] = self._decode_payload(row[0]) if row else None

        for category, collection, table, key_column in self._NORMALIZED_PROFILE_TABLES:
            cursor.execute(
                f"SELECT {key_column}, payload_json FROM {table} ORDER BY {key_column}"
            )
            records = []
            for record_key, raw_payload in cursor.fetchall():
                record = self._decode_payload(raw_payload)
                if record is None:
                    continue
                record.setdefault(key_column, record_key)
                records.append(record)
            result[category] = {collection: records}
        return self.normalize_profile_documents(result)

    def save_profile_documents(self, documents: dict[str, Any]) -> None:
        payload = self.normalize_profile_documents(documents)
        self._ensure_ready()
        connection = self.client.connect()
        with connection.transaction():
            with connection.cursor() as cursor:
                self._write_profile_documents(cursor, payload)

    def _write_profile_documents(self, cursor: Any, payload: dict[str, Any]) -> None:
        for scope in ("master_profile", "achievements"):
            cursor.execute(
                "INSERT INTO profile_documents (scope, payload_json, updated_at) VALUES (%s, %s, now()) ON CONFLICT (scope) DO UPDATE SET payload_json = EXCLUDED.payload_json, updated_at = now()",
                (scope, json.dumps(payload[scope], ensure_ascii=False, sort_keys=True)),
            )

        for category, collection, table, key_column in self._NORMALIZED_PROFILE_TABLES:
            records = payload[category].get(collection, [])
            record_keys = [
                record[key_column]
                for record in records
                if isinstance(record, dict) and record.get(key_column)
            ]
            cursor.execute(
                f"DELETE FROM {table} WHERE {key_column} <> ALL (%s)",
                (record_keys,),
            )
            for record in records:
                if not isinstance(record, dict):
                    continue
                record_key = record.get(key_column)
                if not record_key:
                    continue
                cursor.execute(
                    f"INSERT INTO {table} ({key_column}, payload_json, updated_at) VALUES (%s, %s, now()) ON CONFLICT ({key_column}) DO UPDATE SET payload_json = EXCLUDED.payload_json, updated_at = now()",
                    (record_key, json.dumps(record, ensure_ascii=False, sort_keys=True)),
                )

    def save_profile_documents_and_update_applications(
        self,
        documents: dict[str, Any],
        expected_profile_revision: str,
        expected_applications: list[dict[str, Any]],
        update_applications: Callable[[list[dict[str, Any]]], Any],
    ) -> Any:
        payload = self.normalize_profile_documents(documents)
        self._ensure_ready()
        try:
            connection = self.client.connect()
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "LOCK TABLE application_records IN SHARE ROW EXCLUSIVE MODE"
                    )
                    for table in ("profile_documents", *(item[2] for item in self._NORMALIZED_PROFILE_TABLES)):
                        cursor.execute(
                            f"LOCK TABLE {table} IN SHARE ROW EXCLUSIVE MODE"
                        )
                    current_profile = self._load_profile_documents(cursor)
                    if profile_documents_revision(current_profile) != expected_profile_revision:
                        raise RuntimeError(
                            "Profile data changed during profile update. Reload and retry."
                        )
                    cursor.execute(
                        "SELECT application_id, payload_json FROM application_records ORDER BY application_id FOR UPDATE"
                    )
                    applications = [
                        self._decode_payload(raw_payload)
                        for _, raw_payload in cursor.fetchall()
                    ]
                    if any(application is None for application in applications):
                        raise ValueError("An application record is invalid.")
                    applications = [application for application in applications if application is not None]
                    expected = sorted(
                        expected_applications,
                        key=lambda item: item.get("application_id", ""),
                    )
                    current = sorted(
                        applications,
                        key=lambda item: item.get("application_id", ""),
                    )
                    if current != expected:
                        raise RuntimeError(
                            "Application data changed during profile update. Reload and retry."
                        )

                    self._write_profile_documents(cursor, payload)
                    before = copy.deepcopy(applications)
                    result = update_applications(applications)
                    before_by_id = {
                        item.get("application_id"): item for item in before
                    }
                    application_ids = [
                        item.get("application_id") for item in applications
                    ]
                    if (
                        len(applications) != len(before)
                        or len(application_ids) != len(set(application_ids))
                        or set(application_ids) != set(before_by_id)
                    ):
                        raise ValueError("Applications cannot be added or removed during profile invalidation.")
                    for application in applications:
                        application_id = application.get("application_id")
                        if not application_id or application_id not in before_by_id:
                            raise ValueError("Application IDs cannot be changed.")
                        if application != before_by_id[application_id]:
                            self._write_application_row(cursor, application)
                    return result
        finally:
            self.client.close()

    def _fetch_application_rows(self) -> list[dict[str, Any]]:
        self._ensure_ready()
        try:
            connection = self.client.connect()
            with connection.cursor() as cursor:
                cursor.execute("SELECT application_id, payload_json FROM application_records ORDER BY application_id")
                rows = cursor.fetchall()
            return [
                json.loads(record_json) if isinstance(record_json, str) else record_json
                for _, record_json in rows
            ]
        finally:
            self.client.close()

    def _ensure_legacy_document_history(self, cursor: Any) -> None:
        import_legacy_document_history(cursor, self.data_dir)

    @staticmethod
    def _insert_document_history_entry(cursor: Any, entry: dict[str, Any]) -> None:
        _insert_document_history_entry(cursor, entry)

    @staticmethod
    def _decode_history_rows(rows: list[tuple[Any, Any, Any]]) -> dict[str, Any]:
        documents = []
        for document_id, application_id, raw_payload in rows:
            payload = PostgresStorageAdapter._decode_payload(raw_payload)
            if payload is None:
                raise DocumentHistoryError(f"Stored document-history entry is invalid: {document_id}")
            if payload.get("document_id", document_id) != document_id:
                raise DocumentHistoryConflictError(
                    f"Stored document-history ID conflicts with its payload: {document_id}"
                )
            if payload.get("application_id", application_id) != application_id:
                raise DocumentHistoryConflictError(
                    f"Stored document-history application conflicts with its payload: {document_id}"
                )
            payload["document_id"] = document_id
            payload["application_id"] = application_id
            documents.append(payload)
        return {"documents": documents}

    def load_document_history(self) -> dict[str, Any]:
        self._ensure_ready()
        try:
            connection = self.client.connect()
            with connection.transaction():
                with connection.cursor() as cursor:
                    self._ensure_legacy_document_history(cursor)
                    cursor.execute(
                        """
                        SELECT document_id, application_id, payload_json
                        FROM document_history_records
                        ORDER BY history_position, document_id
                        """
                    )
                    return self._decode_history_rows(cursor.fetchall())
        finally:
            self.client.close()

    def save_document_history(self, history: dict[str, Any]) -> None:
        if not isinstance(history, dict) or set(history) != {"documents"}:
            raise DocumentHistoryError(
                "PostgreSQL document history supports the documents collection only."
            )
        normalized = _normalize_document_history(history, require_application_id=True)
        self._ensure_ready()
        try:
            connection = self.client.connect()
            with connection.transaction():
                with connection.cursor() as cursor:
                    self._ensure_legacy_document_history(cursor)
                    cursor.execute("LOCK TABLE document_history_records IN SHARE ROW EXCLUSIVE MODE")
                    cursor.execute("DELETE FROM document_history_records")
                    for item in normalized["documents"]:
                        self._insert_document_history_entry(cursor, item)
        finally:
            self.client.close()

    def append_document_history(self, entry: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(entry, dict):
            raise DocumentHistoryError("A document-history entry must be an object.")
        item = copy.deepcopy(entry)
        item.setdefault("document_id", uuid.uuid4().hex)
        normalized = _normalize_document_history(
            {"documents": [item]},
            require_application_id=True,
        )["documents"][0]
        self._ensure_ready()
        try:
            connection = self.client.connect()
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM application_records WHERE application_id = %s FOR KEY SHARE",
                        (normalized["application_id"],),
                    )
                    if cursor.fetchone() is None:
                        raise DocumentHistoryError(
                            f"Application does not exist for document history: {normalized['application_id']}"
                        )
                    self._ensure_legacy_document_history(cursor)
                    cursor.execute(
                        "SELECT 1 FROM document_history_records WHERE document_id = %s",
                        (normalized["document_id"],),
                    )
                    if cursor.fetchone() is not None:
                        raise DocumentHistoryConflictError(
                            f"Document-history ID already exists: {normalized['document_id']}"
                        )
                    self._insert_document_history_entry(cursor, normalized)
            return copy.deepcopy(normalized)
        finally:
            self.client.close()

    def replace_document_history_entry(
        self, document_id: str, entry: dict[str, Any]
    ) -> dict[str, Any] | None:
        if not isinstance(entry, dict):
            raise DocumentHistoryError("A document-history entry must be an object.")
        if entry.get("document_id") not in (None, document_id):
            raise DocumentHistoryConflictError(
                "A document-history replacement cannot change its document_id."
            )
        replacement = copy.deepcopy(entry)
        replacement["document_id"] = document_id
        normalized = _normalize_document_history(
            {"documents": [replacement]},
            require_application_id=True,
        )["documents"][0]
        self._ensure_ready()
        try:
            connection = self.client.connect()
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM application_records WHERE application_id = %s FOR KEY SHARE",
                        (normalized["application_id"],),
                    )
                    if cursor.fetchone() is None:
                        raise DocumentHistoryError(
                            f"Application does not exist for document history: {normalized['application_id']}"
                        )
                    self._ensure_legacy_document_history(cursor)
                    cursor.execute(
                        "SELECT application_id FROM document_history_records WHERE document_id = %s FOR UPDATE",
                        (document_id,),
                    )
                    if cursor.fetchone() is None:
                        return None
                    cursor.execute(
                        """
                        UPDATE document_history_records
                        SET application_id = %s, payload_json = %s, updated_at = now()
                        WHERE document_id = %s
                        """,
                        (
                            normalized["application_id"],
                            json.dumps(normalized, ensure_ascii=False, sort_keys=True, allow_nan=False),
                            document_id,
                        ),
                    )
            return copy.deepcopy(normalized)
        finally:
            self.client.close()

    def delete_document_history_entry(self, document_id: str) -> dict[str, Any] | None:
        self._ensure_ready()
        try:
            connection = self.client.connect()
            with connection.transaction():
                with connection.cursor() as cursor:
                    self._ensure_legacy_document_history(cursor)
                    cursor.execute(
                        """
                        DELETE FROM document_history_records
                        WHERE document_id = %s
                        RETURNING document_id, application_id, payload_json
                        """,
                        (document_id,),
                    )
                    deleted = cursor.fetchone()
                    if deleted is None:
                        return None
                    return self._decode_history_rows([deleted])["documents"][0]
        finally:
            self.client.close()

    def diagnostic_application_store(self, application_id: str) -> dict[str, Any]:
        self._require_postgres_backend()
        try:
            connection = self.client.connect()
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION READ ONLY")
                    cursor.execute(
                        """
                        SELECT current_database(),
                               current_user,
                               current_schema(),
                               version(),
                               (SELECT COUNT(*) FROM public.application_records),
                               EXISTS (
                                   SELECT 1
                                   FROM public.application_records
                                   WHERE application_id = %s
                               )
                        """,
                        (application_id,),
                    )
                    database, user, schema, server_version, record_count, application_exists = cursor.fetchone()
            return {
                "host": connection.info.host,
                "database": database,
                "user": user,
                "schema": schema,
                "server_version": server_version,
                "application_record_count": record_count,
                "target_application_exists": application_exists,
            }
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "42P01" or getattr(exc, "pgcode", None) == "42P01":
                raise PostgresApplicationTableMissingError(
                    "Expected table public.application_records is missing."
                ) from exc
            raise
        finally:
            self.client.close()

    def load_application_store(self) -> dict[str, Any]:
        return self.translate_application_store({"applications": self._fetch_application_rows()})

    def save_application_store(self, store: dict[str, Any]) -> None:
        raise RuntimeError(
            "Full application-store snapshots cannot be saved in PostgreSQL mode; "
            "use per-application operations."
        )

    @staticmethod
    def _write_application_row(cursor: Any, item: dict[str, Any]) -> None:
        app_id = item.get("application_id")
        if not app_id:
            raise ValueError("Application ID is required.")
        cursor.execute(
            """
            INSERT INTO application_records (
                application_id, payload_json, job_description_reference,
                phase8_plan_reference, resume_reference, cover_letter_reference,
                selected_projects, selected_skill_names, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (application_id) DO UPDATE SET
                payload_json = EXCLUDED.payload_json,
                job_description_reference = EXCLUDED.job_description_reference,
                phase8_plan_reference = EXCLUDED.phase8_plan_reference,
                resume_reference = EXCLUDED.resume_reference,
                cover_letter_reference = EXCLUDED.cover_letter_reference,
                selected_projects = EXCLUDED.selected_projects,
                selected_skill_names = EXCLUDED.selected_skill_names,
                updated_at = now()
            """,
            (
                app_id,
                json.dumps(item, ensure_ascii=False, sort_keys=True),
                item.get("job_description_reference"),
                item.get("phase8_plan_reference"),
                item.get("resume_reference"),
                item.get("cover_letter_reference"),
                json.dumps(item.get("selected_projects") or [], ensure_ascii=False, sort_keys=True),
                json.dumps(item.get("selected_skills") or [], ensure_ascii=False, sort_keys=True),
            ),
        )

    def insert_application(self, application: dict[str, Any]) -> None:
        self._ensure_ready()
        item = self.translate_application_record(application)
        if not item.get("application_id"):
            raise ValueError("Application ID is required.")
        try:
            connection = self.client.connect()
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO application_records (
                            application_id, payload_json, job_description_reference,
                            phase8_plan_reference, resume_reference, cover_letter_reference,
                            selected_projects, selected_skill_names, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                        """,
                        (
                            item["application_id"],
                            json.dumps(item, ensure_ascii=False, sort_keys=True),
                            item.get("job_description_reference"),
                            item.get("phase8_plan_reference"),
                            item.get("resume_reference"),
                            item.get("cover_letter_reference"),
                            json.dumps(item.get("selected_projects") or [], ensure_ascii=False, sort_keys=True),
                            json.dumps(item.get("selected_skills") or [], ensure_ascii=False, sort_keys=True),
                        ),
                    )
        finally:
            self.client.close()

    def mutate_application(
        self,
        application_id: str,
        mutation: Callable[[dict[str, Any]], bool | None],
    ) -> dict[str, Any] | None:
        self._ensure_ready()
        try:
            connection = self.client.connect()
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT payload_json FROM application_records WHERE application_id = %s FOR UPDATE",
                        (application_id,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        return None
                    application = self._decode_payload(row[0])
                    if application is None:
                        raise ValueError(f"Application record is invalid: {application_id}")
                    if mutation(application) is False:
                        return None
                    if application.get("application_id") != application_id:
                        raise ValueError("Application ID cannot be changed.")
                    self._write_application_row(cursor, application)
                    return copy.deepcopy(application)
        finally:
            self.client.close()

    def delete_application(
        self,
        application_id: str,
        expected: dict[str, Any] | None = None,
        before_delete: Callable[[], None] | None = None,
    ) -> dict[str, Any] | None:
        self._ensure_ready()
        try:
            connection = self.client.connect()
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT payload_json FROM application_records WHERE application_id = %s FOR UPDATE",
                        (application_id,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        return None
                    application = self._decode_payload(row[0])
                    if application is None:
                        raise ValueError(f"Application record is invalid: {application_id}")
                    if expected is not None and application != expected:
                        return None
                    self._ensure_legacy_document_history(cursor)
                    if before_delete is not None:
                        before_delete()
                    cursor.execute(
                        "DELETE FROM document_history_records WHERE application_id = %s",
                        (application_id,),
                    )
                    cursor.execute(
                        "DELETE FROM application_records WHERE application_id = %s",
                        (application_id,),
                    )
                    return application
        finally:
            self.client.close()


__all__ = ["PostgresStorageAdapter"]
