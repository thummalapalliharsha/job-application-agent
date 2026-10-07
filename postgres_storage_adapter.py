from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from postgres_client import PostgresClient
from postgres_config import PostgresConfig, load_postgres_config
from storage_adapter import EMPTY_APPLICATION_STORE, EMPTY_PROFILE_DOCUMENTS, PROFILE_DOCUMENT_CATEGORIES, StorageAdapter

try:  # pragma: no cover - optional runtime dependency for staging only.
    import psycopg
except ModuleNotFoundError:  # pragma: no cover
    psycopg = None


class PostgresStorageAdapter(StorageAdapter):
    """Minimal PostgreSQL-backed implementation for the approved stage-only adapter.

    In postgres mode, this adapter must fail closed instead of silently falling back to the
    local JSON files. The app-facing payloads stay compatible with the StorageAdapter contract,
    while durable staging reads and writes use the same canonical dict shapes the file adapter
    already exposes.
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
        self.config = config or load_postgres_config()
        self.client = PostgresClient(self.config)

    def _require_postgres_backend(self) -> None:
        backend = (os.environ.get("CAREER_OS_STORAGE_BACKEND", "file") or "file").strip().lower()
        if backend != "postgres":
            raise RuntimeError("CAREER_OS_STORAGE_BACKEND must be set to postgres for PostgresStorageAdapter use.")
        if self.config is None or not self.config.is_configured:
            raise RuntimeError("PostgreSQL staging configuration is missing or incomplete.")
        if psycopg is None:
            raise RuntimeError("psycopg is not installed for PostgreSQL staging storage.")

    def _ensure_ready(self) -> None:
        self._require_postgres_backend()
        health = self.client.healthcheck()
        if not health.get("ready") or not health.get("reachable") or health.get("error") is not None:
            raise RuntimeError(f"PostgreSQL staging backend is not ready: {health}")

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
        result: dict[str, Any] = {}
        with connection.transaction():
            with connection.cursor() as cursor:
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
                for scope in ("master_profile", "achievements"):
                    cursor.execute(
                        "INSERT INTO profile_documents (scope, payload_json, updated_at) VALUES (%s, %s, now()) ON CONFLICT (scope) DO UPDATE SET payload_json = EXCLUDED.payload_json, updated_at = now()",
                        (scope, json.dumps(payload[scope], ensure_ascii=False, sort_keys=True)),
                    )

                for category, collection, table, key_column in self._NORMALIZED_PROFILE_TABLES:
                    for record in payload[category].get(collection, []):
                        if not isinstance(record, dict):
                            continue
                        record_key = record.get(key_column)
                        if not record_key:
                            continue
                        cursor.execute(
                            f"INSERT INTO {table} ({key_column}, payload_json, updated_at) VALUES (%s, %s, now()) ON CONFLICT ({key_column}) DO UPDATE SET payload_json = EXCLUDED.payload_json, updated_at = now()",
                            (record_key, json.dumps(record, ensure_ascii=False, sort_keys=True)),
                        )

    def _fetch_application_rows(self) -> list[dict[str, Any]]:
        self._ensure_ready()
        connection = self.client.connect()
        with connection.cursor() as cursor:
            cursor.execute("SELECT application_id, payload_json FROM application_records ORDER BY application_id")
            rows = cursor.fetchall()
        return [
            json.loads(record_json) if isinstance(record_json, str) else record_json
            for _, record_json in rows
        ]

    def load_application_store(self) -> dict[str, Any]:
        return self.translate_application_store({"applications": self._fetch_application_rows()})

    def save_application_store(self, store: dict[str, Any]) -> None:
        payload = self.translate_application_store(store)
        self._ensure_ready()
        connection = self.client.connect()
        with connection.cursor() as cursor:
            for item in payload.get("applications", []):
                if not isinstance(item, dict):
                    continue
                app_id = item.get("application_id")
                if not app_id:
                    continue
                cursor.execute(
                    """
                    INSERT INTO application_records (
                        application_id,
                        payload_json,
                        job_description_reference,
                        phase8_plan_reference,
                        resume_reference,
                        cover_letter_reference,
                        selected_projects,
                        selected_skill_names,
                        updated_at
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
        connection.commit()


__all__ = ["PostgresStorageAdapter"]
