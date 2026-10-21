import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from postgres_backfill_staging import assert_staging_target, preflight_staging_backfill, run_staging_backfill


class ProgrammingError(RuntimeError):
    pass


class FakeTransaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.in_transaction = True
        self.connection._before_tx = copy.deepcopy(self.connection.data)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.connection.in_transaction = False
        if exc_type is None:
            self.connection.commits += 1
        else:
            self.connection.rollbacks += 1
            self.connection.data = copy.deepcopy(self.connection._before_tx)
            self.connection.schema_created = False
        return False


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def execute(self, sql, params=None):
        sql_text = (sql or "").upper()
        if "CREATE TABLE" in sql_text:
            self.connection.schema_created = True
            return None
        if "INSERT INTO BACKFILL_RUNS" in sql_text:
            manifest_run_id = params[1]
            self.connection.data["backfill_runs"][manifest_run_id] = {
                "run_label": params[0],
                "manifest_run_id": params[1],
                "target_env": params[2],
                "manifest_json": params[3],
                "valid_record_count": params[4],
                "quarantined_record_count": params[5],
                "status": params[6],
            }
            return None
        if "INSERT INTO QUARANTINE_LOG" in sql_text:
            key = (params[0], params[1], params[2], params[3], params[4])
            self.connection.data["quarantine_log"][key] = {
                "manifest_run_id": params[0],
                "record_type": params[1],
                "record_id": params[2],
                "application_id": params[3],
                "reason": params[4],
                "payload_json": params[5],
            }
            return None
        if "INSERT INTO PROFILE_DOCUMENTS" in sql_text:
            self.connection.data["profile_documents"][params[0]] = params[1]
            return None
        if "SELECT PG_ADVISORY_XACT_LOCK" in sql_text:
            self.result = None
            return None
        if "SELECT SOURCE_SHA256 FROM DOCUMENT_HISTORY_MIGRATIONS" in sql_text:
            marker = self.connection.data["document_history_migrations"].get(params[0])
            self.result = (marker["source_sha256"],) if marker else None
            return None
        if "SELECT COUNT(*) FROM DOCUMENT_HISTORY_RECORDS" in sql_text:
            self.result = (len(self.connection.data["document_history_records"]),)
            return None
        if "INSERT INTO DOCUMENT_HISTORY_RECORDS" in sql_text:
            document_id, application_id, payload_json = params
            if document_id in self.connection.data["document_history_records"]:
                raise RuntimeError(f"duplicate document history ID: {document_id}")
            if self.connection.fail_on_document_history_insert:
                raise RuntimeError("forced document history insert failure")
            self.connection.data["document_history_records"][document_id] = {
                "application_id": application_id,
                "payload_json": json.loads(payload_json),
            }
            return None
        if "INSERT INTO DOCUMENT_HISTORY_MIGRATIONS" in sql_text:
            migration_id, source_hash, imported_count = params
            self.connection.data["document_history_migrations"][migration_id] = {
                "source_sha256": source_hash,
                "imported_count": imported_count,
            }
            return None
        if "INSERT INTO APPLICATION_RECORDS" in sql_text:
            app_id = params[0]
            self.connection.data["application_records"][app_id] = params[1]
            return None
        if "UPDATE BACKFILL_RUNS SET COMPLETED_AT" in sql_text:
            run_id = params[0]
            if run_id in self.connection.data["backfill_runs"]:
                self.connection.data["backfill_runs"][run_id]["status"] = "success"
            return None
        if "SELECT COUNT(*) FROM APPLICATION_RECORDS" in sql_text:
            if "WHERE APPLICATION_ID = ANY" in sql_text:
                target_ids = set(params[0]) if isinstance(params[0], (list, tuple, set)) else set()
                self.result = (len(target_ids & set(self.connection.data["application_records"].keys())),)
            else:
                self.result = (len(self.connection.data["application_records"]),)
            if self.connection.fail_on_validation:
                raise RuntimeError("forced validation failure")
            return None
        if "SELECT COUNT(*) FROM QUARANTINE_LOG" in sql_text:
            self.result = (len(self.connection.data["quarantine_log"]),)
            return None
        if "SELECT 1" in sql_text and "FROM QUARANTINE_LOG" in sql_text and "IS NOT DISTINCT FROM" in sql_text:
            target = params
            for value in self.connection.data["quarantine_log"].values():
                if (
                    value["record_type"] == target[0]
                    and value["record_id"] == target[1]
                    and value["application_id"] == target[2]
                    and value["reason"] == target[3]
                ):
                    self.result = (1,)
                    return None
            self.result = None
            return None
        if "SELECT RECORD_TYPE, RECORD_ID, APPLICATION_ID, REASON FROM QUARANTINE_LOG" in sql_text:
            rows = [
                (value["record_type"], value["record_id"], value["application_id"], value["reason"])
                for value in self.connection.data["quarantine_log"].values()
            ]
            self.result = rows
            return None
        return None

    def fetchone(self):
        if self.result is None:
            return None
        value = self.result
        self.result = None
        return value

    def fetchall(self):
        if self.result is None:
            return []
        value = self.result
        self.result = None
        return value


class FakeConnection:
    def __init__(self):
        self.data = {
            "backfill_runs": {},
            "quarantine_log": {},
            "profile_documents": {},
            "application_records": {},
            "document_history_records": {},
            "document_history_migrations": {},
        }
        self._before_tx = copy.deepcopy(self.data)
        self.schema_created = False
        self.commits = 0
        self.rollbacks = 0
        self.fail_on_validation = False
        self.fail_on_document_history_insert = False
        self.in_transaction = False
        self._autocommit = True
        self.cursor_obj = FakeCursor(self)

    @property
    def autocommit(self):
        return self._autocommit

    @autocommit.setter
    def autocommit(self, value):
        if self.in_transaction and value is False:
            raise ProgrammingError("can't change 'autocommit' now: connection in transaction status INTRANS")
        self._autocommit = bool(value)

    def cursor(self):
        return self.cursor_obj

    def transaction(self):
        return FakeTransaction(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1
        self.data = copy.deepcopy(self._before_tx)
        self.schema_created = False

    def begin(self):
        self._before_tx = copy.deepcopy(self.data)


class PostgresStagingBackfillTests(unittest.TestCase):
    def setUp(self):
        self.staging_host_patch = patch.dict(
            os.environ,
            {"CAREER_OS_POSTGRES_STAGING_HOST": "ep-neon-staging.neon.tech"},
            clear=False,
        )
        self.staging_host_patch.start()
        self.addCleanup(self.staging_host_patch.stop)

    def _write_minimal_valid_manifest(self, root: Path) -> None:
        data_dir = root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "master_profile.json").write_text(
            json.dumps({"profile": {"name": "Jane Doe"}, "source_documents": [], "record_indexes": {"project_ids": ["project_1"]}, "conflicts_requiring_review": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        (data_dir / "projects.json").write_text(json.dumps({"projects": [{"record_id": "project_1", "name": "Demo"}]}, ensure_ascii=False), encoding="utf-8")
        (data_dir / "skills.json").write_text(json.dumps({"skill_groups": [{"category": "programming_languages", "skills": [{"name": "Python"}]}]}, ensure_ascii=False), encoding="utf-8")
        (data_dir / "experience.json").write_text(json.dumps({"experiences": [{"record_id": "exp_1", "organization": "Acme"}]}, ensure_ascii=False), encoding="utf-8")
        (data_dir / "education.json").write_text(json.dumps({"education": [{"record_id": "edu_1", "institution": "University"}]}, ensure_ascii=False), encoding="utf-8")
        (data_dir / "certifications.json").write_text(json.dumps({"certifications": [{"record_id": "cert_1", "name": "Cert"}]}, ensure_ascii=False), encoding="utf-8")
        (data_dir / "applications.json").write_text(
            json.dumps({"applications": [{"application_id": "app_1", "job_description_reference": "job_descriptions/app_1.txt", "phase8_plan_reference": "output/reports/report_1.json", "resume_reference": "data/master_profile.json", "cover_letter_reference": "output/cover_letters/cover_1.txt", "selected_projects": ["project_1"], "selected_skills": ["Python"]}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        (data_dir / "document_history.json").write_text(json.dumps({"documents": [{"document_id": "doc_1", "application_id": "app_1", "record_type": "resume"}]}, ensure_ascii=False), encoding="utf-8")
        jd_dir = root / "job_descriptions"
        jd_dir.mkdir(parents=True, exist_ok=True)
        (jd_dir / "app_1.txt").write_text("JD text", encoding="utf-8")
        reports_dir = root / "output" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "report_1.json").write_text("{}", encoding="utf-8")

    def test_staging_target_guard_rejects_render_targets(self):
        with patch.dict(os.environ, {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_ENV": "production", "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@dpg-example.render.com/postgres"}, clear=False):
            ok, message = assert_staging_target()
            self.assertFalse(ok)
            self.assertIn("staging", message)

    def test_staging_target_guard_rejects_arbitrary_postgres_hosts(self):
        with patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_ENV": "staging",
                "CAREER_OS_POSTGRES_URL": "postgresql://user:secret@db.example.com/app",
            },
            clear=False,
        ):
            ok, message = assert_staging_target()
        self.assertFalse(ok)
        self.assertIn("allow-listed staging host", message)

    def test_staging_target_guard_rejects_production_neon_url(self):
        with patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_ENV": "staging",
                "CAREER_OS_POSTGRES_URL": "postgresql://user:secret@ep-prod.neon.tech/neondb",
            },
            clear=False,
        ):
            ok, message = assert_staging_target()
        self.assertFalse(ok)
        self.assertIn("allow-listed staging host", message)

    def test_staging_target_guard_rejects_conflicting_environment_labels(self):
        with patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_ENV": "staging",
                "APP_ENV": "production",
                "CAREER_OS_POSTGRES_URL": "postgresql://user:secret@ep-neon-staging.neon.tech/neondb",
            },
            clear=False,
        ):
            ok, message = assert_staging_target()
        self.assertFalse(ok)
        self.assertIn("conflicting", message)

    def test_staging_target_guard_requires_explicit_environment_and_host_identity(self):
        with patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_POSTGRES_URL": "postgresql://user:secret@ep-neon-staging.neon.tech/neondb",
            },
            clear=True,
        ):
            ok, message = assert_staging_target()
        self.assertFalse(ok)
        self.assertIn("CAREER_OS_ENV", message)

        with patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_ENV": "staging",
                "CAREER_OS_POSTGRES_URL": "postgresql://user:secret@ep-neon-staging.neon.tech/neondb",
            },
            clear=True,
        ):
            ok, message = assert_staging_target()
        self.assertFalse(ok)
        self.assertIn("allow-list", message)

    def test_staging_target_guard_accepts_exact_allow_listed_staging_target(self):
        with patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_ENV": "staging",
                "CAREER_OS_POSTGRES_STAGING_HOST": "ep-neon-staging.neon.tech",
                "CAREER_OS_POSTGRES_URL": "postgresql://user:secret@ep-neon-staging.neon.tech/neondb",
            },
            clear=False,
        ):
            ok, message = assert_staging_target()
        self.assertTrue(ok, message)

    def test_staging_target_guard_rejects_url_host_override(self):
        with patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_ENV": "staging",
                "CAREER_OS_POSTGRES_STAGING_HOST": "ep-neon-staging.neon.tech",
                "CAREER_OS_POSTGRES_URL": "postgresql://user:secret@ep-neon-staging.neon.tech/neondb?host=prod.example.com",
            },
            clear=False,
        ):
            ok, message = assert_staging_target()
        self.assertFalse(ok)
        self.assertIn("override target identity", message)

    def test_rejected_target_does_not_healthcheck_or_open_backfill_connection(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_ENV": "staging",
                "CAREER_OS_POSTGRES_URL": "postgresql://user:secret@db.example.com/app",
            },
            clear=False,
        ):
            client = Mock()
            connection_factory = Mock()
            with self.assertRaisesRegex(ValueError, "allow-listed staging host"):
                run_staging_backfill(
                    tmpdir,
                    client=client,
                    connection_factory=connection_factory,
                )
            client.healthcheck.assert_not_called()
            connection_factory.assert_not_called()

    def test_preflight_accepts_valid_manifest_and_healthy_stage(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_ENV": "staging", "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@ep-neon-staging.neon.tech/neondb"}, clear=False):
            root = Path(tmpdir)
            self._write_minimal_valid_manifest(root)
            client = Mock()
            client.healthcheck.return_value = {"backend": "postgres", "configured": True, "ready": True, "reachable": True, "error": None}
            result = preflight_staging_backfill(root, client=client)
            self.assertTrue(result["target_ok"])
            self.assertEqual(result["quarantined_record_count"], 0)
            self.assertGreaterEqual(result["valid_record_count"], 1)

    def test_preflight_rejects_unhealthy_postgres_stage(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_ENV": "staging", "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@ep-neon-staging.neon.tech/neondb"}, clear=False):
            root = Path(tmpdir)
            self._write_minimal_valid_manifest(root)
            client = Mock()
            client.healthcheck.return_value = {"backend": "postgres", "configured": True, "ready": False, "reachable": False, "error": "timeout"}
            with self.assertRaises(RuntimeError):
                preflight_staging_backfill(root, client=client)

    def test_staging_backfill_is_one_atomic_transaction(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_ENV": "staging", "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@ep-neon-staging.neon.tech/neondb"}, clear=False):
            root = Path(tmpdir)
            self._write_minimal_valid_manifest(root)
            conn = FakeConnection()
            conn.fail_on_validation = True
            client = Mock()
            client.healthcheck.return_value = {"backend": "postgres", "configured": True, "ready": True, "reachable": True, "error": None}
            with self.assertRaises(RuntimeError):
                run_staging_backfill(root, client=client, connection_factory=lambda: conn)
            self.assertEqual(conn.rollbacks, 1)
            self.assertEqual(conn.commits, 0)
            self.assertEqual(conn.data["application_records"], {})
            self.assertFalse(conn.schema_created)
            self.assertEqual(conn.data["document_history_records"], {})
            self.assertEqual(conn.data["document_history_migrations"], {})

    def test_staging_history_import_refuses_existing_conflicting_id_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_ENV": "staging",
                "CAREER_OS_POSTGRES_URL": "postgresql://user:password@ep-neon-staging.neon.tech/neondb",
            },
            clear=False,
        ):
            root = Path(tmpdir)
            self._write_minimal_valid_manifest(root)
            conn = FakeConnection()
            original = {
                "application_id": "app_1",
                "payload_json": {
                    "document_id": "doc_1",
                    "application_id": "app_1",
                    "record_type": "original",
                },
            }
            conn.data["document_history_records"]["doc_1"] = copy.deepcopy(original)
            client = Mock()
            client.healthcheck.return_value = {
                "backend": "postgres", "configured": True, "ready": True,
                "reachable": True, "error": None,
            }

            with self.assertRaisesRegex(RuntimeError, "without a migration record"):
                run_staging_backfill(root, client=client, connection_factory=lambda: conn)

            self.assertEqual(conn.rollbacks, 1)
            self.assertEqual(conn.commits, 0)
            self.assertEqual(conn.data["document_history_records"], {"doc_1": original})
            self.assertEqual(conn.data["document_history_migrations"], {})
            self.assertEqual(conn.data["application_records"], {})

    def test_staging_history_import_failure_rolls_back_rows_and_marker(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_ENV": "staging",
                "CAREER_OS_POSTGRES_URL": "postgresql://user:password@ep-neon-staging.neon.tech/neondb",
            },
            clear=False,
        ):
            root = Path(tmpdir)
            self._write_minimal_valid_manifest(root)
            conn = FakeConnection()
            conn.fail_on_document_history_insert = True
            client = Mock()
            client.healthcheck.return_value = {
                "backend": "postgres", "configured": True, "ready": True,
                "reachable": True, "error": None,
            }

            with self.assertRaisesRegex(RuntimeError, "forced document history insert failure"):
                run_staging_backfill(root, client=client, connection_factory=lambda: conn)

            self.assertEqual(conn.rollbacks, 1)
            self.assertEqual(conn.commits, 0)
            self.assertEqual(conn.data["document_history_records"], {})
            self.assertEqual(conn.data["document_history_migrations"], {})
            self.assertEqual(conn.data["application_records"], {})

    def test_runner_rejects_dirty_connection_before_entering_transaction(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_ENV": "staging", "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@ep-neon-staging.neon.tech/neondb"}, clear=False):
            root = Path(tmpdir)
            self._write_minimal_valid_manifest(root)
            conn = FakeConnection()
            conn.in_transaction = True
            conn._autocommit = False
            client = Mock()
            client.healthcheck.return_value = {"backend": "postgres", "configured": True, "ready": True, "reachable": True, "error": None}

            with self.assertRaises(RuntimeError) as exc:
                run_staging_backfill(root, client=client, connection_factory=lambda: conn)

            self.assertIn("clean transaction state", str(exc.exception))
            self.assertFalse(conn._autocommit)

    def test_same_manifest_can_be_run_twice_without_duplicate_audit_or_quarantine_records(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_ENV": "staging", "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@ep-neon-staging.neon.tech/neondb"}, clear=False):
            root = Path(tmpdir)
            self._write_minimal_valid_manifest(root)
            conn = FakeConnection()
            client = Mock()
            client.healthcheck.return_value = {"backend": "postgres", "configured": True, "ready": True, "reachable": True, "error": None}
            run_staging_backfill(root, client=client, connection_factory=lambda: conn)
            run_staging_backfill(root, client=client, connection_factory=lambda: conn)
            self.assertEqual(len(conn.data["backfill_runs"]), 1)
            self.assertEqual(len(conn.data["quarantine_log"]), 0)
            self.assertEqual(len(conn.data["document_history_records"]), 1)
            self.assertEqual(
                conn.data["document_history_migrations"]["legacy_document_history_v1"],
                {
                    "source_sha256": hashlib.sha256(
                        (root / "data" / "document_history.json").read_bytes()
                    ).hexdigest(),
                    "imported_count": 1,
                },
            )
            self.assertEqual(conn.commits, 2)

    def test_same_logical_quarantine_set_is_idempotent_across_different_manifest_runs(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_ENV": "staging", "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@ep-neon-staging.neon.tech/neondb"}, clear=False):
            root = Path(tmpdir)
            self._write_minimal_valid_manifest(root)
            conn = FakeConnection()
            client = Mock()
            client.healthcheck.return_value = {"backend": "postgres", "configured": True, "ready": True, "reachable": True, "error": None}
            manifest_a = {
                "application_ids": ["app_1"],
                "datasets": {"applications": 1},
                "quarantined": [
                    {"record_type": "document_history", "record_id": "doc_q1", "application_id": "missing_app", "record": {"doc": "a"}},
                    {"record_type": "document_history", "record_id": "doc_q2", "application_id": "missing_app_2", "record": {"doc": "b"}},
                    {"record_type": "profile_conflict", "record_id": "conflict_1", "application_id": None, "record": {"conflict": "c"}},
                ],
                "run_label": "first",
            }
            manifest_b = {**manifest_a, "run_label": "second", "datasets": {"applications": 2}}
            with patch("postgres_backfill_staging.build_a_tier_manifest", side_effect=[manifest_a, manifest_b]), patch("postgres_backfill_staging.validate_manifest", return_value=[]):
                run_staging_backfill(root, client=client, connection_factory=lambda: conn)
                run_staging_backfill(root, client=client, connection_factory=lambda: conn)
            self.assertEqual(len(conn.data["quarantine_log"]), 3)
            self.assertEqual(len(conn.data["backfill_runs"]), 2)
            self.assertEqual(conn.commits, 2)

    def test_different_manifests_keep_separate_audit_records(self):
        with tempfile.TemporaryDirectory() as tmpdir_a, tempfile.TemporaryDirectory() as tmpdir_b, patch.dict(os.environ, {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_ENV": "staging", "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@ep-neon-staging.neon.tech/neondb"}, clear=False):
            root_a = Path(tmpdir_a)
            root_b = Path(tmpdir_b)
            self._write_minimal_valid_manifest(root_a)
            self._write_minimal_valid_manifest(root_b)
            (root_b / "data" / "applications.json").write_text(json.dumps({"applications": [{"application_id": "app_2", "job_description_reference": "job_descriptions/app_2.txt", "phase8_plan_reference": "output/reports/report_2.json", "resume_reference": "data/master_profile.json", "cover_letter_reference": "output/cover_letters/cover_2.txt", "selected_projects": ["project_1"], "selected_skills": ["Python"]}]}, ensure_ascii=False), encoding="utf-8")
            (root_b / "job_descriptions" / "app_2.txt").write_text("JD 2", encoding="utf-8")
            reports_dir = root_b / "output" / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            (reports_dir / "report_2.json").write_text("{}", encoding="utf-8")
            conn = FakeConnection()
            client = Mock()
            client.healthcheck.return_value = {"backend": "postgres", "configured": True, "ready": True, "reachable": True, "error": None}
            run_staging_backfill(root_a, client=client, connection_factory=lambda: conn)
            run_staging_backfill(root_b, client=client, connection_factory=lambda: conn)
            self.assertEqual(len(conn.data["backfill_runs"]), 2)

    def test_manifest_validation_keeps_123_valid_and_3_quarantined_semantics(self):
        with patch.dict(os.environ, {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_ENV": "staging", "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@ep-neon-staging.neon.tech/neondb"}, clear=False):
            manifest = {
                "application_ids": [f"app_{index}" for index in range(123)],
                "document_history": [{"application_id": f"app_{index}"} for index in range(123)],
                "datasets": {"projects": 50, "skills": 20, "experience": 15, "education": 10, "certifications": 8, "applications": 123, "document_history": 123, "job_descriptions": 30, "reports": 60},
                "quarantined": [{"record_type": "document_history", "record_id": "doc_q1", "application_id": "missing_app"}, {"record_type": "document_history", "record_id": "doc_q2", "application_id": "missing_app_2"}, {"record_type": "profile_conflict", "record_id": "conflict_1", "application_id": None}],
            }
            with patch("postgres_backfill_staging.build_a_tier_manifest", return_value=manifest), patch("postgres_backfill_staging.validate_manifest", return_value=[]):
                result = preflight_staging_backfill(Path("."), client=Mock(healthcheck=Mock(return_value={"backend": "postgres", "configured": True, "ready": True, "reachable": True, "error": None})))
                self.assertEqual(result["valid_record_count"], 123)
                self.assertEqual(result["quarantined_record_count"], 3)


if __name__ == "__main__":
    unittest.main()
