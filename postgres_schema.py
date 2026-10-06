"""Minimal PostgreSQL staging schema for the approved Gate 9C durable-storage layer.

This schema is intentionally limited to the exact data needed for the file-compatible
application payloads. It does not migrate any production data and is safe to apply to
Neon staging only.
"""
from __future__ import annotations

POSTGRES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS profile_documents (
    scope TEXT PRIMARY KEY,
    payload_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_hash CHAR(64)
);

CREATE TABLE IF NOT EXISTS project_records (
    record_id TEXT PRIMARY KEY,
    payload_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS skill_groups (
    category TEXT PRIMARY KEY,
    payload_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS experience_records (
    record_id TEXT PRIMARY KEY,
    payload_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS education_records (
    record_id TEXT PRIMARY KEY,
    payload_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS certification_records (
    record_id TEXT PRIMARY KEY,
    payload_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS application_records (
    application_id TEXT PRIMARY KEY,
    payload_json JSONB NOT NULL,
    job_description_reference TEXT,
    phase8_plan_reference TEXT,
    resume_reference TEXT,
    cover_letter_reference TEXT,
    selected_projects JSONB,
    selected_skill_names JSONB,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_history_records (
    document_id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job_descriptions (
    path TEXT PRIMARY KEY,
    sha256 CHAR(64) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS report_records (
    path TEXT PRIMARY KEY,
    sha256 CHAR(64) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quarantine_log (
    quarantine_id BIGSERIAL PRIMARY KEY,
    manifest_run_id TEXT NOT NULL,
    record_type TEXT NOT NULL,
    record_id TEXT,
    application_id TEXT,
    reason TEXT NOT NULL,
    payload_json JSONB,
    quarantined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (manifest_run_id, record_type, record_id, application_id, reason)
);

CREATE TABLE IF NOT EXISTS backfill_runs (
    run_id BIGSERIAL PRIMARY KEY,
    run_label TEXT NOT NULL,
    manifest_run_id TEXT NOT NULL UNIQUE,
    target_env TEXT NOT NULL,
    manifest_json JSONB NOT NULL,
    valid_record_count INT NOT NULL,
    quarantined_record_count INT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'success', 'failed', 'rolled_back'))
);
"""


def postgres_schema_sql() -> str:
    return POSTGRES_SCHEMA_SQL


__all__ = ["POSTGRES_SCHEMA_SQL", "postgres_schema_sql"]
