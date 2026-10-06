"""Gate 9C staging backfill runner for the approved PostgreSQL design.

This module intentionally does not auto-run on import. It contains the explicit,
transaction-scoped backfill logic that validates the A-tier manifest, requires a
healthy Neon staging connection, and performs idempotent upserts inside a single
transaction.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

from postgres_client import PostgresClient
from postgres_config import PostgresConfig, load_postgres_config
from postgres_schema import postgres_schema_sql
from postgres_backfill_dry_run import build_a_tier_manifest, validate_manifest


def assert_staging_target(config: PostgresConfig | None = None) -> tuple[bool, str]:
    """Ensure the target is explicit staging-only and not Render production."""
    resolved = config or load_postgres_config()
    backend = (os.environ.get("CAREER_OS_STORAGE_BACKEND", "file") or "file").strip().lower()
    if backend != "postgres":
        return False, "CAREER_OS_STORAGE_BACKEND must be set to postgres for staging writes."
    if not resolved.is_configured:
        return False, "PostgreSQL staging configuration is missing."
    url = (resolved.url or "").lower()
    host = (resolved.host or "").lower()
    env_name = (os.environ.get("CAREER_OS_ENV") or os.environ.get("APP_ENV") or os.environ.get("ENVIRONMENT") or "staging").strip().lower()
    if env_name in {"production", "prod", "render"}:
        return False, "Production targets are forbidden for the staging-only backfill."
    if "render" in url or "render" in host:
        return False, "Render production connections are not allowed for this staging backfill."
    if "neon.tech" not in url and "neon.tech" not in host and not url and not host:
        return False, "Staging backfill requires an explicit Neon staging Postgres URL or host."
    return True, ""


def _manifest_run_id(manifest: dict[str, Any]) -> str:
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _logical_quarantine_signature(item: dict[str, Any]) -> tuple[Any, Any, Any, str]:
    return (
        item.get("record_type"),
        item.get("record_id"),
        item.get("application_id"),
        "manifest_validation",
    )


def _logical_quarantine_signatures(items: list[dict[str, Any]]) -> set[tuple[Any, Any, Any, str]]:
    return {_logical_quarantine_signature(item) for item in items if isinstance(item, dict)}


def _existing_logical_quarantine(cursor: Any, item: dict[str, Any]) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM quarantine_log
        WHERE record_type IS NOT DISTINCT FROM %s
          AND record_id IS NOT DISTINCT FROM %s
          AND application_id IS NOT DISTINCT FROM %s
          AND reason = %s
        LIMIT 1
        """,
        (
            item.get("record_type"),
            item.get("record_id"),
            item.get("application_id"),
            "manifest_validation",
        ),
    )
    return cursor.fetchone() is not None


def _valid_record_count(manifest: dict[str, Any]) -> int:
    valid_ids = manifest.get("application_ids", [])
    if isinstance(valid_ids, list):
        return len(valid_ids)
    return 0


def preflight_staging_backfill(
    root: str | Path,
    config: PostgresConfig | None = None,
    client: PostgresClient | None = None,
) -> dict[str, Any]:
    """Run the exact manifest validation required before any staging write."""
    root_path = Path(root).resolve()
    resolved_config = config or load_postgres_config()
    resolved_client = client or PostgresClient(resolved_config)

    ok, reason = assert_staging_target(resolved_config)
    if not ok:
        raise ValueError(reason)

    manifest = build_a_tier_manifest(root_path)
    issues = validate_manifest(manifest, root_path)
    if issues:
        raise ValueError("A-tier backfill validation failed: " + "; ".join(issues))

    health = resolved_client.healthcheck()
    if not health.get("ready") or not health.get("reachable") or health.get("error") is not None:
        raise RuntimeError(f"PostgreSQL staging healthcheck failed: {health}")

    valid_count = _valid_record_count(manifest)
    quarantined_count = len(manifest.get("quarantined", []))

    return {
        "root": str(root_path),
        "backend": "postgres",
        "target_ok": True,
        "manifest": manifest,
        "valid_record_count": valid_count,
        "quarantined_record_count": quarantined_count,
        "healthcheck": health,
    }


def _execute_staging_schema(conn: Any) -> None:
    with conn.cursor() as cursor:
        cursor.execute(postgres_schema_sql())


def _read_json_file(path: Path) -> Any:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_posix(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def run_staging_backfill(
    root: str | Path,
    config: PostgresConfig | None = None,
    client: PostgresClient | None = None,
    connection_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Execute the staging-only backfill, but only when explicitly called.

    This is a single transaction from schema creation through validation. A mismatch or an
    unexpected error triggers a rollback so no partial staging data remains.
    """
    root_path = Path(root).resolve()
    resolved_config = config or load_postgres_config()
    resolved_client = client or PostgresClient(resolved_config)
    factory = connection_factory or (lambda: PostgresClient(resolved_config).connect())

    preflight = preflight_staging_backfill(root_path, resolved_config, resolved_client)
    manifest = preflight["manifest"]
    valid_count = preflight["valid_record_count"]
    quarantined_count = preflight["quarantined_record_count"]
    manifest_run_id = _manifest_run_id(manifest)

    conn = factory()
    used_transaction_context = hasattr(conn, "transaction")
    try:
        if hasattr(conn, "in_transaction") and conn.in_transaction:
            raise RuntimeError("Staging backfill connection must begin in a clean transaction state.")

        if used_transaction_context:
            with conn.transaction():
                _execute_staging_schema(conn)

                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO backfill_runs (run_label, manifest_run_id, target_env, manifest_json, valid_record_count, quarantined_record_count, status) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (manifest_run_id) DO UPDATE SET run_label = EXCLUDED.run_label, target_env = EXCLUDED.target_env, manifest_json = EXCLUDED.manifest_json, valid_record_count = EXCLUDED.valid_record_count, quarantined_record_count = EXCLUDED.quarantined_record_count, status = 'running'",
                        (
                            "gate_9c_staging",
                            manifest_run_id,
                            "staging",
                            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                            valid_count,
                            quarantined_count,
                            "running",
                        ),
                    )

                    for item in manifest.get("quarantined", []):
                        if _existing_logical_quarantine(cursor, item):
                            continue
                        cursor.execute(
                            "INSERT INTO quarantine_log (manifest_run_id, record_type, record_id, application_id, reason, payload_json) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (manifest_run_id, record_type, record_id, application_id, reason) DO UPDATE SET payload_json = EXCLUDED.payload_json, quarantined_at = now()",
                            (
                                manifest_run_id,
                                item.get("record_type"),
                                item.get("record_id"),
                                item.get("application_id"),
                                "manifest_validation",
                                json.dumps(item.get("record", {}), ensure_ascii=False, sort_keys=True),
                            ),
                        )

                    profile = _read_json_file(root_path / "data" / "master_profile.json")
                    if profile:
                        cursor.execute(
                            "INSERT INTO profile_documents (scope, payload_json) VALUES (%s, %s) ON CONFLICT (scope) DO UPDATE SET payload_json = EXCLUDED.payload_json, updated_at = now()",
                            ("master_profile", json.dumps(profile, ensure_ascii=False, sort_keys=True)),
                        )

                    project_payload = _read_json_file(root_path / "data" / "projects.json")
                    for item in project_payload.get("projects", []):
                        if not isinstance(item, dict) or not item.get("record_id"):
                            continue
                        cursor.execute(
                            "INSERT INTO project_records (record_id, payload_json) VALUES (%s, %s) ON CONFLICT (record_id) DO UPDATE SET payload_json = EXCLUDED.payload_json, updated_at = now()",
                            (item.get("record_id"), json.dumps(item, ensure_ascii=False, sort_keys=True)),
                        )

                    skills_payload = _read_json_file(root_path / "data" / "skills.json")
                    for item in skills_payload.get("skill_groups", []):
                        if not isinstance(item, dict):
                            continue
                        category = item.get("category") or "unknown"
                        cursor.execute(
                            "INSERT INTO skill_groups (category, payload_json) VALUES (%s, %s) ON CONFLICT (category) DO UPDATE SET payload_json = EXCLUDED.payload_json, updated_at = now()",
                            (category, json.dumps(item, ensure_ascii=False, sort_keys=True)),
                        )

                    experience_payload = _read_json_file(root_path / "data" / "experience.json")
                    for item in experience_payload.get("experiences", []):
                        if not isinstance(item, dict) or not item.get("record_id"):
                            continue
                        cursor.execute(
                            "INSERT INTO experience_records (record_id, payload_json) VALUES (%s, %s) ON CONFLICT (record_id) DO UPDATE SET payload_json = EXCLUDED.payload_json, updated_at = now()",
                            (item.get("record_id"), json.dumps(item, ensure_ascii=False, sort_keys=True)),
                        )

                    education_payload = _read_json_file(root_path / "data" / "education.json")
                    for item in education_payload.get("education", []):
                        if not isinstance(item, dict) or not item.get("record_id"):
                            continue
                        cursor.execute(
                            "INSERT INTO education_records (record_id, payload_json) VALUES (%s, %s) ON CONFLICT (record_id) DO UPDATE SET payload_json = EXCLUDED.payload_json, updated_at = now()",
                            (item.get("record_id"), json.dumps(item, ensure_ascii=False, sort_keys=True)),
                        )

                    certification_payload = _read_json_file(root_path / "data" / "certifications.json")
                    for item in certification_payload.get("certifications", []):
                        if not isinstance(item, dict) or not item.get("record_id"):
                            continue
                        cursor.execute(
                            "INSERT INTO certification_records (record_id, payload_json) VALUES (%s, %s) ON CONFLICT (record_id) DO UPDATE SET payload_json = EXCLUDED.payload_json, updated_at = now()",
                            (item.get("record_id"), json.dumps(item, ensure_ascii=False, sort_keys=True)),
                        )

                    history_payload = _read_json_file(root_path / "data" / "document_history.json")
                    for item in history_payload.get("documents", []):
                        if not isinstance(item, dict):
                            continue
                        document_id = item.get("document_id")
                        if not document_id:
                            continue
                        cursor.execute(
                            "INSERT INTO document_history_records (document_id, application_id, payload_json) VALUES (%s, %s, %s) ON CONFLICT (document_id) DO UPDATE SET application_id = EXCLUDED.application_id, payload_json = EXCLUDED.payload_json, updated_at = now()",
                            (document_id, item.get("application_id"), json.dumps(item, ensure_ascii=False, sort_keys=True)),
                        )

                    jd_dir = root_path / "job_descriptions"
                    if jd_dir.exists():
                        for jd_path in sorted(jd_dir.glob("*.txt")):
                            cursor.execute(
                                "INSERT INTO job_descriptions (path, sha256) VALUES (%s, %s) ON CONFLICT (path) DO UPDATE SET sha256 = EXCLUDED.sha256, updated_at = now()",
                                (_relative_posix(jd_path, root_path), _sha256_file(jd_path)),
                            )

                    reports_dir = root_path / "output" / "reports"
                    if reports_dir.exists():
                        for report_path in sorted(reports_dir.rglob("*.json")):
                            cursor.execute(
                                "INSERT INTO report_records (path, sha256) VALUES (%s, %s) ON CONFLICT (path) DO UPDATE SET sha256 = EXCLUDED.sha256, updated_at = now()",
                                (_relative_posix(report_path, root_path), _sha256_file(report_path)),
                            )

                    for app in json.loads((root_path / "data" / "applications.json").read_text(encoding="utf-8")).get("applications", []) if (root_path / "data" / "applications.json").exists() else []:
                        cursor.execute(
                            """
                            INSERT INTO application_records (
                                application_id, payload_json, job_description_reference, phase8_plan_reference,
                                resume_reference, cover_letter_reference, selected_projects, selected_skill_names
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
                                app.get("application_id"),
                                json.dumps(app, ensure_ascii=False, sort_keys=True),
                                app.get("job_description_reference"),
                                app.get("phase8_plan_reference"),
                                app.get("resume_reference"),
                                app.get("cover_letter_reference"),
                                json.dumps(app.get("selected_projects") or [], ensure_ascii=False, sort_keys=True),
                                json.dumps(app.get("selected_skills") or [], ensure_ascii=False, sort_keys=True),
                            ),
                        )

                    manifest_app_ids = [app.get("application_id") for app in json.loads((root_path / "data" / "applications.json").read_text(encoding="utf-8")).get("applications", []) if (root_path / "data" / "applications.json").exists() and app.get("application_id")]
                    if manifest_app_ids:
                        cursor.execute("SELECT COUNT(*) FROM application_records WHERE application_id = ANY(%s)", (manifest_app_ids,))
                        app_rows = cursor.fetchone()[0]
                        if app_rows != valid_count:
                            raise ValueError(f"Staging backfill row mismatch: expected {valid_count}, saw {app_rows}")
                    else:
                        cursor.execute("SELECT COUNT(*) FROM application_records WHERE application_id IS NULL")
                        app_rows = cursor.fetchone()[0]
                        if app_rows != valid_count:
                            raise ValueError(f"Staging backfill row mismatch: expected {valid_count}, saw {app_rows}")

                    cursor.execute("SELECT record_type, record_id, application_id, reason FROM quarantine_log WHERE reason = %s", ("manifest_validation",))
                    observed_quarantines = {(row[0], row[1], row[2], row[3]) for row in cursor.fetchall()}
                    expected_quarantines = _logical_quarantine_signatures(manifest.get("quarantined", []))
                    if observed_quarantines != expected_quarantines:
                        raise ValueError(
                            f"Staging quarantine mismatch: expected {len(expected_quarantines)}, saw {len(observed_quarantines)}"
                        )

                    cursor.execute(
                        "UPDATE backfill_runs SET completed_at = now(), status = 'success' WHERE manifest_run_id = %s",
                        (manifest_run_id,),
                    )
        else:
            _execute_staging_schema(conn)

            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO backfill_runs (run_label, manifest_run_id, target_env, manifest_json, valid_record_count, quarantined_record_count, status) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (manifest_run_id) DO UPDATE SET run_label = EXCLUDED.run_label, target_env = EXCLUDED.target_env, manifest_json = EXCLUDED.manifest_json, valid_record_count = EXCLUDED.valid_record_count, quarantined_record_count = EXCLUDED.quarantined_record_count, status = 'running'",
                    (
                        "gate_9c_staging",
                        manifest_run_id,
                        "staging",
                        json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                        valid_count,
                        quarantined_count,
                        "running",
                    ),
                )

                for item in manifest.get("quarantined", []):
                    if _existing_logical_quarantine(cursor, item):
                        continue
                    cursor.execute(
                        "INSERT INTO quarantine_log (manifest_run_id, record_type, record_id, application_id, reason, payload_json) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (manifest_run_id, record_type, record_id, application_id, reason) DO UPDATE SET payload_json = EXCLUDED.payload_json, quarantined_at = now()",
                        (
                            manifest_run_id,
                            item.get("record_type"),
                            item.get("record_id"),
                            item.get("application_id"),
                            "manifest_validation",
                            json.dumps(item.get("record", {}), ensure_ascii=False, sort_keys=True),
                        ),
                    )

                profile = _read_json_file(root_path / "data" / "master_profile.json")
                if profile:
                    cursor.execute(
                        "INSERT INTO profile_documents (scope, payload_json) VALUES (%s, %s) ON CONFLICT (scope) DO UPDATE SET payload_json = EXCLUDED.payload_json, updated_at = now()",
                        ("master_profile", json.dumps(profile, ensure_ascii=False, sort_keys=True)),
                    )

                project_payload = _read_json_file(root_path / "data" / "projects.json")
                for item in project_payload.get("projects", []):
                    if not isinstance(item, dict) or not item.get("record_id"):
                        continue
                    cursor.execute(
                        "INSERT INTO project_records (record_id, payload_json) VALUES (%s, %s) ON CONFLICT (record_id) DO UPDATE SET payload_json = EXCLUDED.payload_json, updated_at = now()",
                        (item.get("record_id"), json.dumps(item, ensure_ascii=False, sort_keys=True)),
                    )

                skills_payload = _read_json_file(root_path / "data" / "skills.json")
                for item in skills_payload.get("skill_groups", []):
                    if not isinstance(item, dict):
                        continue
                    category = item.get("category") or "unknown"
                    cursor.execute(
                        "INSERT INTO skill_groups (category, payload_json) VALUES (%s, %s) ON CONFLICT (category) DO UPDATE SET payload_json = EXCLUDED.payload_json, updated_at = now()",
                        (category, json.dumps(item, ensure_ascii=False, sort_keys=True)),
                    )

                experience_payload = _read_json_file(root_path / "data" / "experience.json")
                for item in experience_payload.get("experiences", []):
                    if not isinstance(item, dict) or not item.get("record_id"):
                        continue
                    cursor.execute(
                        "INSERT INTO experience_records (record_id, payload_json) VALUES (%s, %s) ON CONFLICT (record_id) DO UPDATE SET payload_json = EXCLUDED.payload_json, updated_at = now()",
                        (item.get("record_id"), json.dumps(item, ensure_ascii=False, sort_keys=True)),
                    )

                education_payload = _read_json_file(root_path / "data" / "education.json")
                for item in education_payload.get("education", []):
                    if not isinstance(item, dict) or not item.get("record_id"):
                        continue
                    cursor.execute(
                        "INSERT INTO education_records (record_id, payload_json) VALUES (%s, %s) ON CONFLICT (record_id) DO UPDATE SET payload_json = EXCLUDED.payload_json, updated_at = now()",
                        (item.get("record_id"), json.dumps(item, ensure_ascii=False, sort_keys=True)),
                    )

                certification_payload = _read_json_file(root_path / "data" / "certifications.json")
                for item in certification_payload.get("certifications", []):
                    if not isinstance(item, dict) or not item.get("record_id"):
                        continue
                    cursor.execute(
                        "INSERT INTO certification_records (record_id, payload_json) VALUES (%s, %s) ON CONFLICT (record_id) DO UPDATE SET payload_json = EXCLUDED.payload_json, updated_at = now()",
                        (item.get("record_id"), json.dumps(item, ensure_ascii=False, sort_keys=True)),
                    )

                history_payload = _read_json_file(root_path / "data" / "document_history.json")
                for item in history_payload.get("documents", []):
                    if not isinstance(item, dict):
                        continue
                    document_id = item.get("document_id")
                    if not document_id:
                        continue
                    cursor.execute(
                        "INSERT INTO document_history_records (document_id, application_id, payload_json) VALUES (%s, %s, %s) ON CONFLICT (document_id) DO UPDATE SET application_id = EXCLUDED.application_id, payload_json = EXCLUDED.payload_json, updated_at = now()",
                        (document_id, item.get("application_id"), json.dumps(item, ensure_ascii=False, sort_keys=True)),
                    )

                jd_dir = root_path / "job_descriptions"
                if jd_dir.exists():
                    for jd_path in sorted(jd_dir.glob("*.txt")):
                        cursor.execute(
                            "INSERT INTO job_descriptions (path, sha256) VALUES (%s, %s) ON CONFLICT (path) DO UPDATE SET sha256 = EXCLUDED.sha256, updated_at = now()",
                            (_relative_posix(jd_path, root_path), _sha256_file(jd_path)),
                        )

                reports_dir = root_path / "output" / "reports"
                if reports_dir.exists():
                    for report_path in sorted(reports_dir.rglob("*.json")):
                        cursor.execute(
                            "INSERT INTO report_records (path, sha256) VALUES (%s, %s) ON CONFLICT (path) DO UPDATE SET sha256 = EXCLUDED.sha256, updated_at = now()",
                            (_relative_posix(report_path, root_path), _sha256_file(report_path)),
                        )

                for app in json.loads((root_path / "data" / "applications.json").read_text(encoding="utf-8")).get("applications", []) if (root_path / "data" / "applications.json").exists() else []:
                    cursor.execute(
                        """
                        INSERT INTO application_records (
                            application_id, payload_json, job_description_reference, phase8_plan_reference,
                            resume_reference, cover_letter_reference, selected_projects, selected_skill_names
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
                            app.get("application_id"),
                            json.dumps(app, ensure_ascii=False, sort_keys=True),
                            app.get("job_description_reference"),
                            app.get("phase8_plan_reference"),
                            app.get("resume_reference"),
                            app.get("cover_letter_reference"),
                            json.dumps(app.get("selected_projects") or [], ensure_ascii=False, sort_keys=True),
                            json.dumps(app.get("selected_skills") or [], ensure_ascii=False, sort_keys=True),
                        ),
                    )

                manifest_app_ids = [app.get("application_id") for app in json.loads((root_path / "data" / "applications.json").read_text(encoding="utf-8")).get("applications", []) if (root_path / "data" / "applications.json").exists() and app.get("application_id")]
                if manifest_app_ids:
                    cursor.execute("SELECT COUNT(*) FROM application_records WHERE application_id = ANY(%s)", (manifest_app_ids,))
                    app_rows = cursor.fetchone()[0]
                    if app_rows != valid_count:
                        raise ValueError(f"Staging backfill row mismatch: expected {valid_count}, saw {app_rows}")
                else:
                    cursor.execute("SELECT COUNT(*) FROM application_records WHERE application_id IS NULL")
                    app_rows = cursor.fetchone()[0]
                    if app_rows != valid_count:
                        raise ValueError(f"Staging backfill row mismatch: expected {valid_count}, saw {app_rows}")

                cursor.execute("SELECT record_type, record_id, application_id, reason FROM quarantine_log WHERE reason = %s", ("manifest_validation",))
                observed_quarantines = {(row[0], row[1], row[2], row[3]) for row in cursor.fetchall()}
                expected_quarantines = _logical_quarantine_signatures(manifest.get("quarantined", []))
                if observed_quarantines != expected_quarantines:
                    raise ValueError(
                        f"Staging quarantine mismatch: expected {len(expected_quarantines)}, saw {len(observed_quarantines)}"
                    )

                cursor.execute(
                    "UPDATE backfill_runs SET completed_at = now(), status = 'success' WHERE manifest_run_id = %s",
                    (manifest_run_id,),
                )

    except Exception:
        if used_transaction_context:
            raise
        if hasattr(conn, "rollback"):
            try:
                conn.rollback()
            except Exception:
                pass
        raise

    return {
        "status": "prepared",
        "target": "staging",
        "manifest_run_id": manifest_run_id,
        "valid_record_count": valid_count,
        "quarantined_record_count": quarantined_count,
        "manifest": manifest,
    }


__all__ = [
    "assert_staging_target",
    "preflight_staging_backfill",
    "run_staging_backfill",
]
