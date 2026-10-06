from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any


A_TIER_DATASETS = (
    "master_profile",
    "projects",
    "skills",
    "experience",
    "education",
    "certifications",
    "applications",
    "document_history",
    "job_descriptions",
    "reports",
)


def _as_posix(path: str | Path) -> str:
    return str(path).replace("\\", "/")


def _normalize_ref(ref: Any) -> str | None:
    if ref is None:
        return None
    if not isinstance(ref, str):
        return str(ref)
    return ref.replace("\\", "/")


def _read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_a_tier_manifest(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    data_dir = root_path / "data"
    if not data_dir.exists():
        raise FileNotFoundError(f"Missing durable data directory: {data_dir}")

    profile_path = data_dir / "master_profile.json"
    projects_path = data_dir / "projects.json"
    skills_path = data_dir / "skills.json"
    experience_path = data_dir / "experience.json"
    education_path = data_dir / "education.json"
    certifications_path = data_dir / "certifications.json"
    applications_path = data_dir / "applications.json"
    history_path = data_dir / "document_history.json"
    jd_dir = root_path / "job_descriptions"
    reports_dir = root_path / "output" / "reports"

    master_profile = _read_json(profile_path) if profile_path.exists() else {}
    project_payload = _read_json(projects_path) if projects_path.exists() else {"projects": []}
    skills_payload = _read_json(skills_path) if skills_path.exists() else {"skill_groups": []}
    experience_payload = _read_json(experience_path) if experience_path.exists() else {"experiences": []}
    education_payload = _read_json(education_path) if education_path.exists() else {"education": []}
    certification_payload = _read_json(certifications_path) if certifications_path.exists() else {"certifications": []}
    application_payload = _read_json(applications_path) if applications_path.exists() else {"applications": []}
    history_payload = _read_json(history_path) if history_path.exists() else {"documents": []}

    project_ids = [item.get("record_id") for item in project_payload.get("projects", []) if isinstance(item, dict) and item.get("record_id")]
    application_ids = [item.get("application_id") for item in application_payload.get("applications", []) if isinstance(item, dict) and item.get("application_id")]

    application_refs: dict[str, dict[str, Any]] = {}
    for item in application_payload.get("applications", []):
        if not isinstance(item, dict):
            continue
        app_id = item.get("application_id")
        if not app_id:
            continue
        application_refs[app_id] = {
            "job_description_reference": _normalize_ref(item.get("job_description_reference")),
            "phase8_plan_reference": _normalize_ref(item.get("phase8_plan_reference")),
            "resume_reference": _normalize_ref(item.get("resume_reference")),
            "cover_letter_reference": _normalize_ref(item.get("cover_letter_reference")),
            "selected_projects": item.get("selected_projects", []),
            "selected_skill_names": item.get("selected_skills", []),
        }

    quarantined: list[dict[str, Any]] = []
    for doc in history_payload.get("documents", []):
        if not isinstance(doc, dict):
            continue
        app_id = doc.get("application_id")
        if app_id and app_id not in set(application_ids):
            quarantined.append({"record_type": "document_history", "application_id": app_id, "record": doc})

    for item in master_profile.get("conflicts_requiring_review", []):
        if isinstance(item, dict) and item.get("record_id"):
            record_id = item.get("record_id")
            if record_id not in set(project_ids):
                quarantined.append({"record_type": "profile_conflict", "record_id": record_id, "record": item})

    manifest: dict[str, Any] = {
        "root": _as_posix(root_path),
        "datasets": {
            "master_profile": 1 if master_profile else 0,
            "projects": len(project_payload.get("projects", [])),
            "skills": len(skills_payload.get("skill_groups", [])),
            "experience": len(experience_payload.get("experiences", [])),
            "education": len(education_payload.get("education", [])),
            "certifications": len(certification_payload.get("certifications", [])),
            "applications": len(application_payload.get("applications", [])),
            "document_history": len(history_payload.get("documents", [])),
            "job_descriptions": len(list(jd_dir.glob("*.txt"))) if jd_dir.exists() else 0,
            "reports": len(list(reports_dir.glob("**/*.json"))) if reports_dir.exists() else 0,
        },
        "project_ids": project_ids,
        "application_ids": application_ids,
        "application_refs": application_refs,
        "document_history": history_payload.get("documents", []),
        "profile_conflicts": master_profile.get("conflicts_requiring_review", []),
        "quarantined": quarantined,
        "duplicate_conflicts": [],
        "records_inserted": 0,
    }
    return manifest


def validate_manifest(manifest: dict[str, Any], root: str | Path) -> list[str]:
    root_path = Path(root).resolve()
    issues: list[str] = []

    app_ids = manifest.get("application_ids", [])
    project_ids = manifest.get("project_ids", [])

    if len(app_ids) != len(set(app_ids)):
        duplicates = sorted({item for item in app_ids if app_ids.count(item) > 1})
        issues.append(f"Duplicate application IDs: {duplicates}")

    if len(project_ids) != len(set(project_ids)):
        duplicates = sorted({item for item in project_ids if project_ids.count(item) > 1})
        issues.append(f"Duplicate project IDs: {duplicates}")

    for app_id, refs in manifest.get("application_refs", {}).items():
        jd_ref = _normalize_ref(refs.get("job_description_reference"))
        if jd_ref is None:
            issues.append(f"Application {app_id} is missing a job_description_reference.")
        elif not str(jd_ref).startswith("job_descriptions/"):
            issues.append(f"Application {app_id} references a non-JD path: {jd_ref}")
        elif not (root_path / jd_ref).exists():
            issues.append(f"Application {app_id} JD reference missing: {jd_ref}")

        plan_ref = _normalize_ref(refs.get("phase8_plan_reference"))
        if plan_ref and not str(plan_ref).startswith("output/reports/"):
            issues.append(f"Application {app_id} plan reference is not under output/reports: {plan_ref}")
        if plan_ref and not (root_path / plan_ref).exists():
            issues.append(f"Application {app_id} plan reference missing: {plan_ref}")

    profile_index = {}
    master_path = root_path / "data" / "master_profile.json"
    if master_path.exists():
        profile_index = _read_json(master_path).get("record_indexes", {})
    for project_id in profile_index.get("project_ids", []):
        if project_id not in set(project_ids):
            issues.append(f"Master profile references project absent from project snapshot: {project_id}")

    for doc in manifest.get("quarantined", []):
        if doc.get("record_type") in {"document_history", "profile_conflict"}:
            continue

    return issues


def _build_sqlite_dry_run(root: str | Path, staging_root: str | Path | None = None) -> tuple[sqlite3.Connection, dict[str, Any]]:
    root_path = Path(root).resolve()
    temp_root = Path(staging_root).resolve() if staging_root else Path(tempfile.mkdtemp(prefix="career_os_dryrun_"))
    temp_root.mkdir(parents=True, exist_ok=True)
    db_path = temp_root / "backfill_dryrun.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS backfill_manifest (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS profile_documents (scope TEXT, payload_json TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS project_records (record_id TEXT PRIMARY KEY, payload_json TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS skill_groups (category TEXT, payload_json TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS experience_records (record_id TEXT PRIMARY KEY, payload_json TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS education_records (record_id TEXT PRIMARY KEY, payload_json TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS certification_records (record_id TEXT PRIMARY KEY, payload_json TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS application_records (application_id TEXT PRIMARY KEY, payload_json TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS document_history_records (application_id TEXT, payload_json TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS job_descriptions (path TEXT PRIMARY KEY, sha256 TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS report_records (path TEXT PRIMARY KEY, sha256 TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS quarantine_log (reason TEXT, record_id TEXT)")

    manifest = build_a_tier_manifest(root_path)
    conn.execute(
        "INSERT OR REPLACE INTO backfill_manifest(key, value) VALUES (?, ?)",
        ("manifest", json.dumps(manifest, ensure_ascii=False, sort_keys=True)),
    )

    profile = _read_json(root_path / "data" / "master_profile.json")
    if profile:
        conn.execute(
            "INSERT OR REPLACE INTO profile_documents(scope, payload_json) VALUES (?, ?)",
            ("master_profile", json.dumps(profile, ensure_ascii=False, sort_keys=True)),
        )

    project_payload = _read_json(root_path / "data" / "projects.json")
    for item in project_payload.get("projects", []):
        conn.execute(
            "INSERT OR REPLACE INTO project_records(record_id, payload_json) VALUES (?, ?)",
            (item.get("record_id"), json.dumps(item, ensure_ascii=False, sort_keys=True)),
        )

    skills_payload = _read_json(root_path / "data" / "skills.json")
    for item in skills_payload.get("skill_groups", []):
        conn.execute(
            "INSERT OR REPLACE INTO skill_groups(category, payload_json) VALUES (?, ?)",
            (item.get("category", "unknown"), json.dumps(item, ensure_ascii=False, sort_keys=True)),
        )

    experience_payload = _read_json(root_path / "data" / "experience.json")
    for item in experience_payload.get("experiences", []):
        conn.execute(
            "INSERT OR REPLACE INTO experience_records(record_id, payload_json) VALUES (?, ?)",
            (item.get("record_id"), json.dumps(item, ensure_ascii=False, sort_keys=True)),
        )

    education_payload = _read_json(root_path / "data" / "education.json")
    for item in education_payload.get("education", []):
        conn.execute(
            "INSERT OR REPLACE INTO education_records(record_id, payload_json) VALUES (?, ?)",
            (item.get("record_id"), json.dumps(item, ensure_ascii=False, sort_keys=True)),
        )

    certification_payload = _read_json(root_path / "data" / "certifications.json")
    for item in certification_payload.get("certifications", []):
        conn.execute(
            "INSERT OR REPLACE INTO certification_records(record_id, payload_json) VALUES (?, ?)",
            (item.get("record_id"), json.dumps(item, ensure_ascii=False, sort_keys=True)),
        )

    app_payload = _read_json(root_path / "data" / "applications.json")
    for item in app_payload.get("applications", []):
        conn.execute(
            "INSERT OR REPLACE INTO application_records(application_id, payload_json) VALUES (?, ?)",
            (item.get("application_id"), json.dumps(item, ensure_ascii=False, sort_keys=True)),
        )

    history_payload = _read_json(root_path / "data" / "document_history.json")
    for item in history_payload.get("documents", []):
        app_id = item.get("application_id")
        if app_id and app_id in set(manifest["application_ids"]):
            conn.execute(
                "INSERT OR REPLACE INTO document_history_records(application_id, payload_json) VALUES (?, ?)",
                (app_id, json.dumps(item, ensure_ascii=False, sort_keys=True)),
            )

    for path in sorted((root_path / "job_descriptions").glob("*.txt")):
        conn.execute(
            "INSERT OR REPLACE INTO job_descriptions(path, sha256) VALUES (?, ?)",
            (_as_posix(path.relative_to(root_path)), _sha256(path)),
        )

    for path in sorted((root_path / "output" / "reports").glob("**/*.json")):
        conn.execute(
            "INSERT OR REPLACE INTO report_records(path, sha256) VALUES (?, ?)",
            (_as_posix(path.relative_to(root_path)), _sha256(path)),
        )

    conn.commit()
    return conn, manifest


def run_isolated_dry_run(root: str | Path, staging_root: str | Path | None = None) -> dict[str, Any]:
    root_path = Path(root).resolve()
    manifest = build_a_tier_manifest(root_path)
    validation_issues = validate_manifest(manifest, root_path)
    if validation_issues:
        raise ValueError("A-tier backfill validation failed: " + "; ".join(validation_issues))

    conn, manifest = _build_sqlite_dry_run(root_path, staging_root)

    valid_history = [
        item for item in manifest["document_history"] if item.get("application_id") in set(manifest["application_ids"])
    ]
    expected_rows = {
        "profile_documents": 1,
        "project_records": manifest["datasets"]["projects"],
        "skill_groups": manifest["datasets"]["skills"],
        "experience_records": manifest["datasets"]["experience"],
        "education_records": manifest["datasets"]["education"],
        "certification_records": manifest["datasets"]["certifications"],
        "application_records": manifest["datasets"]["applications"],
        "document_history_records": len(valid_history),
        "job_descriptions": manifest["datasets"]["job_descriptions"],
        "report_records": manifest["datasets"]["reports"],
    }

    round_trip_ok = True
    for table_name, expected_count in expected_rows.items():
        row_count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        if row_count != expected_count:
            round_trip_ok = False

    total_records = sum(expected_rows.values()) - expected_rows["profile_documents"]
    backfill_summary = {
        "dry_run_ok": True,
        "staging_target": f"sqlite:///{conn.execute('PRAGMA database_list').fetchall()[0][2]}",
        "dataset_count": len(A_TIER_DATASETS),
        "records_inserted": total_records,
        "quarantined_records": manifest["quarantined"],
        "document_history_entries": len(valid_history),
        "duplicate_conflicts": [],
        "round_trip_ok": round_trip_ok,
        "conflicts_found": manifest["profile_conflicts"],
        "manifest": manifest,
    }

    conn.close()
    return backfill_summary
