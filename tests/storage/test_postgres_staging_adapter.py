import copy
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import career_os_api as api
import profile_update_agent as pua
from postgres_storage_adapter import PostgresStorageAdapter
from profile_security import hash_profile_pin


TABLE_KEYS = {
    "project_records": "record_id",
    "skill_groups": "category",
    "experience_records": "record_id",
    "education_records": "record_id",
    "certification_records": "record_id",
}

PROFILE_COLLECTIONS = {
    "projects": ("projects", "project_records", "record_id"),
    "skills": ("skill_groups", "skill_groups", "category"),
    "experience": ("experiences", "experience_records", "record_id"),
    "education": ("education", "education_records", "record_id"),
    "certifications": ("certifications", "certification_records", "record_id"),
}


def empty_database():
    return {
        "application_records": {},
        "document_history_records": {},
        "profile_documents": {},
        "tables": {table: {} for table in TABLE_KEYS},
    }


class DummyCursor:
    def __init__(self, connection):
        self.connection = connection
        self._one = None
        self._all = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        statement = " ".join(sql.split()).casefold()
        self._one = None
        self._all = []
        self.connection.executed.append((statement, params, self.connection.active_transaction))

        if statement.startswith("lock table "):
            return

        if statement.startswith("select payload_json from profile_documents"):
            payload = self.connection.database["profile_documents"].get(params[0])
            self._one = (copy.deepcopy(payload),) if payload is not None else None
            return

        if statement.startswith("select application_id, payload_json from application_records"):
            rows = self.connection.database["application_records"]
            self._all = [(key, copy.deepcopy(rows[key])) for key in sorted(rows)]
            return

        if statement.startswith("select payload_json from application_records where application_id = %s"):
            payload = self.connection.database["application_records"].get(params[0])
            self._one = (copy.deepcopy(payload),) if payload is not None else None
            return

        if statement.startswith("insert into application_records "):
            application_id = params[0]
            if self.connection.fail_on_application_write_id == application_id:
                raise RuntimeError("simulated post-invalidation failure")
            if "on conflict" not in statement and application_id in self.connection.database["application_records"]:
                raise RuntimeError("duplicate application ID")
            self.connection.database["application_records"][application_id] = json.loads(params[1])
            return

        if statement.startswith("delete from application_records where application_id = %s"):
            self.connection.database["application_records"].pop(params[0], None)
            return

        if statement.startswith("delete from document_history_records where application_id = %s"):
            rows = self.connection.database["document_history_records"]
            self.connection.database["document_history_records"] = {
                key: value
                for key, value in rows.items()
                if value.get("application_id") != params[0]
            }
            return

        for table, key_column in TABLE_KEYS.items():
            if statement.startswith(f"delete from {table} where {key_column} <> all"):
                if self.connection.fail_on_reconcile_table == table:
                    raise RuntimeError("simulated profile reconciliation failure")
                retained_keys = set(params[0])
                rows = self.connection.database["tables"][table]
                self.connection.database["tables"][table] = {
                    key: value for key, value in rows.items() if key in retained_keys
                }
                return

            if statement.startswith(f"select {key_column}, payload_json from {table} "):
                rows = self.connection.database["tables"][table]
                self._all = [(key, copy.deepcopy(rows[key])) for key in sorted(rows)]
                return

        if statement.startswith("insert into profile_documents "):
            scope, raw_payload = params
            self.connection.database["profile_documents"][scope] = json.loads(raw_payload)
            return

        for table, key_column in TABLE_KEYS.items():
            if statement.startswith(f"insert into {table} "):
                if self.connection.fail_on_table == table:
                    raise RuntimeError("simulated database write failure")
                key, raw_payload = params
                self.connection.database["tables"][table][key] = json.loads(raw_payload)
                return

        raise AssertionError(f"Unexpected SQL in adapter test: {statement}")

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


class DummyConnection:
    def __init__(self, database=None):
        self.database = database or empty_database()
        self.executed = []
        self.transaction_count = 0
        self.active_transaction = None
        self._snapshot = None
        self.fail_on_table = None
        self.fail_on_reconcile_table = None
        self.fail_on_application_write_id = None
        self._transaction_lock = threading.RLock()

    def cursor(self):
        return DummyCursor(self)

    def commit(self):
        return None

    def rollback(self):
        return None

    def transaction(self):
        return self

    def __enter__(self):
        self._transaction_lock.acquire()
        self.transaction_count += 1
        self.active_transaction = self.transaction_count
        self._snapshot = copy.deepcopy(self.database)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is not None:
                self.database.clear()
                self.database.update(self._snapshot)
            self.active_transaction = None
            self._snapshot = None
        finally:
            self._transaction_lock.release()
        return False


class PostgresStorageAdapterTests(unittest.TestCase):
    @staticmethod
    def _profile_fixture():
        return {
            "master_profile": {
                "profile": {"name": "Test Candidate", "headline": "Data engineer", "location": "Remote"},
                "source_documents": [],
                "record_indexes": {},
                "conflicts_requiring_review": [],
            },
            "projects": {"projects": [
                {
                    "record_id": f"project_{index:02d}",
                    "name": "AI Radar" if index == 0 else f"Project {index:02d}",
                    "status": "verified" if index % 2 == 0 else "candidate_provided",
                    "project_status": "completed" if index % 2 == 0 else "in_progress",
                    "github_availability": "github_verified" if index % 2 == 0 else "github_pending",
                    "purpose": f"Project purpose {index:02d}",
                    "technologies": ["Python"],
                }
                for index in range(13)
            ]},
            "skills": {"skill_groups": [
                {"category": f"category_{index:02d}", "skills": [{"name": f"Skill {index:02d}", "status": "candidate_provided"}]}
                for index in range(8)
            ]},
            "experience": {"experiences": [
                {"record_id": f"experience_{index:02d}", "organization": f"Organization {index:02d}", "title": "Engineer"}
                for index in range(2)
            ]},
            "education": {"education": [
                {"record_id": f"education_{index:02d}", "institution": f"University {index:02d}", "degree": "BSc"}
                for index in range(3)
            ]},
            "certifications": {"certifications": [
                {"record_id": f"certification_{index:02d}", "name": f"Certification {index:02d}"}
                for index in range(6)
            ]},
            "achievements": {"achievements": []},
        }

    @staticmethod
    def _database_for(profile):
        database = empty_database()
        database["profile_documents"]["master_profile"] = copy.deepcopy(profile["master_profile"])
        if "achievements" in profile:
            database["profile_documents"]["achievements"] = copy.deepcopy(profile["achievements"])
        for category, (collection, table, key_column) in PROFILE_COLLECTIONS.items():
            database["tables"][table] = {
                record[key_column]: copy.deepcopy(record)
                for record in profile[category][collection]
            }
        return database

    @staticmethod
    def _adapter(tmpdir, database=None):
        adapter = PostgresStorageAdapter(root=tmpdir)
        connection = DummyConnection(database)
        adapter.client = Mock()
        adapter.client.healthcheck.return_value = {
            "backend": "postgres", "configured": True, "ready": True,
            "reachable": True, "error": None,
        }
        adapter.client.ping.return_value = True
        adapter.client.connect.return_value = connection
        return adapter, connection

    def test_application_mutations_lock_and_preserve_current_record(self):
        initial = {
            "application_id": "app_one",
            "current_status": "saved",
            "application_notes": [],
        }
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_POSTGRES_URL": "postgresql://test"},
            clear=False,
        ), patch("postgres_storage_adapter.psycopg", object()):
            adapter, connection = self._adapter(tmpdir)
            adapter.insert_application(initial)
            stale_record = adapter.load_application_store()["applications"][0]
            updated = adapter.mutate_application(
                "app_one",
                lambda current: current.update({"current_status": "interview"}),
            )
            self.assertEqual(updated["current_status"], "interview")
            self.assertIsNone(adapter.delete_application("app_one", expected=stale_record))
            current = adapter.mutate_application(
                "app_one",
                lambda record: record["application_notes"].append({"note": "kept"}),
            )
            self.assertEqual(current["current_status"], "interview")
            self.assertEqual(current["application_notes"], [{"note": "kept"}])
            self.assertIsNone(adapter.delete_application("app_one", expected=stale_record))
            self.assertEqual(adapter.load_application_store()["applications"], [current])
            self.assertGreaterEqual(connection.transaction_count, 4)
            with self.assertRaisesRegex(RuntimeError, "snapshots cannot be saved"):
                adapter.save_application_store({"applications": [stale_record]})

    def test_profile_and_application_update_roll_back_if_invalidation_fails_before_any_change(self):
        profile = self._profile_fixture()
        database = self._database_for(profile)
        database["application_records"]["app_one"] = {
            "application_id": "app_one",
            "resume_generation_allowed": True,
            "current_status": "approved",
        }
        original = copy.deepcopy(database)

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_POSTGRES_URL": "postgresql://test"},
            clear=False,
        ), patch("postgres_storage_adapter.psycopg", object()):
            adapter, connection = self._adapter(tmpdir, database)
            expected = adapter.load_application_store()["applications"]
            replacement = copy.deepcopy(profile)
            replacement["master_profile"]["profile"]["location"] = "Changed"

            def fail_before_invalidation(_applications):
                raise RuntimeError("simulated pre-invalidation failure")

            with self.assertRaisesRegex(RuntimeError, "pre-invalidation"):
                adapter.save_profile_documents_and_update_applications(
                    replacement, pua._profile_revision(profile), expected, fail_before_invalidation
                )

        self.assertEqual(connection.database, original)

    def test_profile_and_application_update_roll_back_after_partial_invalidation(self):
        profile = self._profile_fixture()
        database = self._database_for(profile)
        database["application_records"]["app_one"] = {
            "application_id": "app_one",
            "resume_generation_allowed": True,
            "current_status": "approved",
        }
        database["application_records"]["app_two"] = {
            "application_id": "app_two",
            "resume_generation_allowed": True,
            "current_status": "approved",
        }
        original = copy.deepcopy(database)

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_POSTGRES_URL": "postgresql://test"},
            clear=False,
        ), patch("postgres_storage_adapter.psycopg", object()):
            adapter, connection = self._adapter(tmpdir, database)
            expected = adapter.load_application_store()["applications"]
            replacement = copy.deepcopy(profile)
            replacement["master_profile"]["profile"]["location"] = "Changed"

            connection.fail_on_application_write_id = "app_two"

            with self.assertRaisesRegex(RuntimeError, "post-invalidation"):
                adapter.save_profile_documents_and_update_applications(
                    replacement,
                    pua._profile_revision(profile),
                    expected,
                    lambda applications: [
                        application.update({"resume_generation_allowed": False})
                        for application in applications
                    ],
                )

        self.assertEqual(connection.database, original)

    def test_profile_update_aborts_on_application_revision_conflict(self):
        profile = self._profile_fixture()
        database = self._database_for(profile)
        database["application_records"]["app_one"] = {
            "application_id": "app_one",
            "resume_generation_allowed": True,
            "current_status": "approved",
        }

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_POSTGRES_URL": "postgresql://test"},
            clear=False,
        ), patch("postgres_storage_adapter.psycopg", object()):
            adapter, connection = self._adapter(tmpdir, database)
            expected = adapter.load_application_store()["applications"]
            connection.database["application_records"]["app_one"]["application_notes"] = "concurrent change"
            state_at_conflict = copy.deepcopy(connection.database)
            replacement = copy.deepcopy(profile)
            replacement["master_profile"]["profile"]["location"] = "Changed"

            with self.assertRaisesRegex(RuntimeError, "changed during profile update"):
                adapter.save_profile_documents_and_update_applications(
                    replacement,
                    pua._profile_revision(profile),
                    expected,
                    lambda _applications: self.fail("invalidation must not run after a conflict"),
                )

        self.assertEqual(connection.database, state_at_conflict)
        self.assertEqual(
            connection.database["profile_documents"]["master_profile"],
            profile["master_profile"],
        )

    def test_profile_edit_rejects_stale_profile_revision_inside_transaction(self):
        profile = self._profile_fixture()
        database = self._database_for(profile)
        database["application_records"]["app_one"] = {
            "application_id": "app_one",
            "resume_generation_allowed": True,
            "current_status": "approved",
        }

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_POSTGRES_URL": "postgresql://test",
                "CAREER_OS_PROFILE_PIN_HASH": hash_profile_pin("123456"),
            },
            clear=False,
        ), patch("postgres_storage_adapter.psycopg", object()):
            adapter, connection = self._adapter(tmpdir, database)
            with patch.object(pua, "_storage_adapter", return_value=adapter), patch.object(
                pua, "all_data", return_value=copy.deepcopy(profile)
            ), patch.object(api, "_profile_action_affects_application", return_value=True):
                plan = pua.plan_profile_edit(
                    updates={"projects": [{
                        "record_id": "project_00",
                        "fields": {"purpose": "Stale profile edit"},
                    }]},
                    root=tmpdir,
                )
                self.assertEqual(plan["decision"], "planned", plan)

                connection.database["tables"]["project_records"]["project_00"]["purpose"] = (
                    "Concurrent profile edit"
                )
                state_at_conflict = copy.deepcopy(connection.database)
                with self.assertRaisesRegex(RuntimeError, "Profile data changed"):
                    pua.apply_profile_edit_plan(
                        plan,
                        root=tmpdir,
                        confirm=True,
                        pin="123456",
                    )

        self.assertEqual(connection.database, state_at_conflict)
        self.assertEqual(
            connection.database["tables"]["project_records"]["project_00"]["purpose"],
            "Concurrent profile edit",
        )
        self.assertTrue(any(
            statement.startswith("lock table profile_documents")
            and transaction_id is not None
            for statement, _, transaction_id in connection.executed
        ))
        self.assertFalse(any(
            statement.startswith("insert into application_records")
            for statement, _, _ in connection.executed
        ))

    def test_profile_edit_updates_profile_and_invalidates_approval_in_one_transaction(self):
        profile = self._profile_fixture()
        database = self._database_for(profile)
        database["application_records"]["app_one"] = {
            "application_id": "app_one",
            "resume_generation_allowed": True,
            "current_status": "approved",
        }

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_POSTGRES_URL": "postgresql://test",
                "CAREER_OS_PROFILE_PIN_HASH": hash_profile_pin("123456"),
            },
            clear=False,
        ), patch("postgres_storage_adapter.psycopg", object()):
            adapter, connection = self._adapter(tmpdir, database)
            self.assertFalse((Path(tmpdir) / "data").exists())
            with patch.object(pua, "_storage_adapter", return_value=adapter), patch.object(
                pua, "all_data", return_value=copy.deepcopy(profile)
            ), patch.object(api, "_profile_action_affects_application", return_value=True):
                plan = pua.plan_profile_edit(
                    updates={"projects": [{
                        "record_id": "project_00",
                        "fields": {"purpose": "Updated profile edit"},
                    }]},
                    root=tmpdir,
                )
                result = pua.apply_profile_edit_plan(
                    plan,
                    root=tmpdir,
                    confirm=True,
                    pin="123456",
                )

        self.assertFalse((Path(tmpdir) / "data").exists())
        self.assertEqual(result["decision"], "profile_updated", result)
        self.assertTrue(result["validation"]["valid"])
        self.assertFalse(
            connection.database["application_records"]["app_one"]["resume_generation_allowed"]
        )
        self.assertEqual(
            connection.database["tables"]["project_records"]["project_00"]["purpose"],
            "Updated profile edit",
        )
        relevant_writes = [
            entry for entry in connection.executed
            if entry[0].startswith("insert into profile_documents")
            or entry[0].startswith("insert into application_records")
        ]
        self.assertEqual(
            {entry[2] for entry in relevant_writes},
            {connection.transaction_count},
        )

    def test_application_delete_cleanup_runs_after_lock_and_rolls_back_on_failure(self):
        initial = {"application_id": "app_one", "current_status": "saved"}
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_POSTGRES_URL": "postgresql://test"},
            clear=False,
        ), patch("postgres_storage_adapter.psycopg", object()):
            adapter, connection = self._adapter(tmpdir)
            adapter.insert_application(initial)
            expected = adapter.load_application_store()["applications"][0]
            artifact = Path(tmpdir) / "artifact.docx"
            artifact.write_text("target artifact", encoding="utf-8")
            callback_transactions = []

            def cleanup_then_fail():
                callback_transactions.append(connection.active_transaction)
                callback_transactions.append(
                    [statement for statement, _, _ in connection.executed]
                )
                artifact.unlink()
                raise OSError("simulated history cleanup failure")

            with self.assertRaisesRegex(OSError, "simulated history cleanup failure"):
                adapter.delete_application("app_one", expected=expected, before_delete=cleanup_then_fail)

            self.assertEqual(connection.database["application_records"]["app_one"], initial)
            self.assertFalse(artifact.exists())
            self.assertIsNotNone(callback_transactions[0])
            self.assertTrue(
                any("for update" in statement for statement in callback_transactions[1])
            )
            self.assertEqual(
                [statement for statement, _, _ in connection.executed if statement.startswith("delete from application_records")],
                [],
            )

    def test_application_mutation_rolls_back_when_update_fails(self):
        initial = {"application_id": "app_one", "current_status": "saved"}
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_POSTGRES_URL": "postgresql://test"},
            clear=False,
        ), patch("postgres_storage_adapter.psycopg", object()):
            adapter, connection = self._adapter(tmpdir)
            adapter.insert_application(initial)

            def fail_after_change(current):
                current["current_status"] = "interview"
                raise RuntimeError("simulated mutation failure")

            with self.assertRaisesRegex(RuntimeError, "simulated mutation failure"):
                adapter.mutate_application("app_one", fail_after_change)
            self.assertEqual(connection.database["application_records"]["app_one"], initial)

    def test_postgres_create_does_not_replay_deleted_or_updated_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_POSTGRES_URL": "postgresql://test"},
            clear=False,
        ), patch("postgres_storage_adapter.psycopg", object()):
            adapter, _ = self._adapter(tmpdir)
            adapter.insert_application({"application_id": "app_removed", "current_status": "saved"})
            adapter.insert_application({"application_id": "app_kept", "current_status": "saved"})
            initial_read_done = threading.Event()
            resume_create = threading.Event()
            errors = []

            def create():
                initial_read_done.set()
                if not resume_create.wait(timeout=5):
                    errors.append(TimeoutError("Test did not resume creation."))
                    return
                try:
                    adapter.insert_application({"application_id": "app_created", "current_status": "saved"})
                except Exception as exc:
                    errors.append(exc)

            worker = threading.Thread(target=create)
            worker.start()
            try:
                self.assertTrue(initial_read_done.wait(timeout=5))
                self.assertIsNotNone(adapter.delete_application("app_removed"))
                updated = adapter.mutate_application(
                    "app_kept",
                    lambda current: current.update({"current_status": "interview"}),
                )
                self.assertEqual(updated["current_status"], "interview")
            finally:
                resume_create.set()
                worker.join(timeout=5)

            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            records = {
                item["application_id"]: item
                for item in adapter.load_application_store()["applications"]
            }
            self.assertNotIn("app_removed", records)
            self.assertEqual(records["app_kept"]["current_status"], "interview")
            self.assertIn("app_created", records)

    def test_normalized_rows_reconstruct_complete_profile_and_summary_shape(self):
        profile = self._profile_fixture()
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@ep-neon-staging.neon.tech/neondb"},
            clear=False,
        ):
            adapter, _ = self._adapter(tmpdir, self._database_for(profile))
            loaded = adapter.load_profile_documents()

            self.assertEqual(loaded["master_profile"], profile["master_profile"])
            for category, (collection, _, _) in PROFILE_COLLECTIONS.items():
                self.assertEqual(loaded[category][collection], profile[category][collection])
            self.assertEqual(loaded["achievements"], {"achievements": []})
            self.assertEqual([len(loaded[category][collection]) for category, (collection, _, _) in PROFILE_COLLECTIONS.items()], [13, 8, 2, 3, 6])

            with patch.object(api.pua, "all_data", return_value=loaded):
                summary = api.profile_summary()
            self.assertEqual(summary["name"], "Test Candidate")
            self.assertEqual(summary["location"], "Remote")
            self.assertEqual(len(summary["projects"]), 13)
            self.assertEqual(len(summary["skills"]), 8)
            self.assertEqual(len(summary["experience"]), 2)
            self.assertEqual(len(summary["education"]), 3)
            self.assertEqual(len(summary["certifications"]), 6)
            self.assertEqual(summary["achievements"], [])
            self.assertTrue(all(isinstance(record, dict) for record in summary["projects"]))

    def test_profile_edit_add_write_reload_round_trip_uses_one_transaction(self):
        profile = self._profile_fixture()
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@ep-neon-staging.neon.tech/neondb",
                "CAREER_OS_PROFILE_PIN_HASH": hash_profile_pin("123456"),
            },
            clear=False,
        ):
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir(parents=True)
            for category, document in profile.items():
                (data_dir / f"{category}.json").write_text(json.dumps(document), encoding="utf-8")

            adapter, connection = self._adapter(tmpdir, self._database_for(profile))
            with patch.object(pua, "_storage_adapter", return_value=adapter), patch.object(
                pua, "invalidate_approved_applications", return_value=[]
            ):
                plan = pua.plan_profile_edit(
                    updates={"projects": [{"record_id": "project_00", "fields": {"purpose": "Edited through profile workflow"}}]},
                    additions={"projects": [{"fields": {
                        "name": "Added Through Workflow",
                        "project_status": "completed",
                        "purpose": "Added via profile edit test",
                        "functionality": ["Stores a canonical profile record."],
                        "technologies": ["Python"],
                    }}]},
                    root=tmpdir,
                )
                result = pua.apply_profile_edit_plan(plan, root=tmpdir, confirm=True, pin="123456")
                self.assertEqual(result["decision"], "profile_updated", result)
                loaded = pua.all_data(tmpdir)

            projects = loaded["projects"]["projects"]
            original_ids = {item["record_id"] for item in profile["projects"]["projects"]}
            loaded_ids = {item["record_id"] for item in projects}
            self.assertTrue(original_ids.issubset(loaded_ids))
            self.assertEqual(len(loaded_ids), 14)
            updated = next(item for item in projects if item["record_id"] == "project_00")
            self.assertEqual(updated["purpose"], "Edited through profile workflow")
            self.assertEqual(updated["status"], "candidate_provided")
            self.assertEqual(updated["project_status"], profile["projects"]["projects"][0]["project_status"])
            added = next(item for item in projects if item["record_id"] == "project_added_through_workflow")
            self.assertEqual(added["status"], "candidate_provided")
            self.assertEqual(added["project_status"], "completed")
            writes = [entry for entry in connection.executed if entry[0].startswith("insert into ")]
            self.assertTrue(writes)
            self.assertEqual(len({entry[2] for entry in writes}), 1)

    def test_profile_write_rolls_back_all_upserts_on_mid_transaction_failure(self):
        profile = self._profile_fixture()
        database = self._database_for(profile)
        original = copy.deepcopy(database)
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@ep-neon-staging.neon.tech/neondb"},
            clear=False,
        ):
            adapter, connection = self._adapter(tmpdir, database)
            connection.fail_on_table = "education_records"
            profile["master_profile"]["profile"]["location"] = "Updated location"
            with self.assertRaisesRegex(RuntimeError, "simulated database write failure"):
                adapter.save_profile_documents(profile)
            self.assertEqual(connection.database, original)

    def test_profile_snapshot_replacement_deletes_omitted_rows_by_category(self):
        profile = self._profile_fixture()
        database = self._database_for(profile)
        omitted_project_id = profile["projects"]["projects"][-1]["record_id"]
        omitted_skill_category = profile["skills"]["skill_groups"][-1]["category"]
        replacement = copy.deepcopy(profile)
        replacement["projects"]["projects"] = replacement["projects"]["projects"][:-1]
        replacement["skills"]["skill_groups"] = replacement["skills"]["skill_groups"][:-1]

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_POSTGRES_URL": "postgresql://test",
            },
            clear=False,
        ), patch("postgres_storage_adapter.psycopg", object()):
            adapter, connection = self._adapter(tmpdir, database)
            adapter.save_profile_documents(replacement)
            loaded = adapter.load_profile_documents()

        self.assertNotIn(
            omitted_project_id,
            {item["record_id"] for item in loaded["projects"]["projects"]},
        )
        self.assertNotIn(
            omitted_skill_category,
            {item["category"] for item in loaded["skills"]["skill_groups"]},
        )
        self.assertEqual(
            loaded["experience"],
            profile["experience"],
            "Reconciling projects and skills must preserve other categories.",
        )
        reconciliation = [
            entry for entry in connection.executed
            if entry[0].startswith("delete from ")
        ]
        self.assertEqual(
            len({entry[2] for entry in reconciliation}),
            1,
            "All category reconciliation must share one transaction.",
        )

    def test_empty_profile_collection_replaces_that_category_with_empty(self):
        profile = self._profile_fixture()
        database = self._database_for(profile)
        profile["projects"]["projects"] = []

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_POSTGRES_URL": "postgresql://test",
            },
            clear=False,
        ), patch("postgres_storage_adapter.psycopg", object()):
            adapter, _ = self._adapter(tmpdir, database)
            adapter.save_profile_documents(profile)
            loaded = adapter.load_profile_documents()

        self.assertEqual(loaded["projects"], {"projects": []})
        self.assertEqual(
            len(loaded["skills"]["skill_groups"]),
            len(self._profile_fixture()["skills"]["skill_groups"]),
        )

    def test_profile_snapshot_reconciliation_failure_rolls_back_all_changes(self):
        profile = self._profile_fixture()
        database = self._database_for(profile)
        original = copy.deepcopy(database)
        replacement = copy.deepcopy(profile)
        replacement["projects"]["projects"] = replacement["projects"]["projects"][:-1]
        replacement["master_profile"]["profile"]["location"] = "Updated location"

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_POSTGRES_URL": "postgresql://test",
            },
            clear=False,
        ), patch("postgres_storage_adapter.psycopg", object()):
            adapter, connection = self._adapter(tmpdir, database)
            connection.fail_on_reconcile_table = "skill_groups"
            with self.assertRaisesRegex(
                RuntimeError,
                "simulated profile reconciliation failure",
            ):
                adapter.save_profile_documents(replacement)

        self.assertEqual(connection.database, original)

    def test_empty_normalized_tables_return_canonical_empty_categories(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@ep-neon-staging.neon.tech/neondb"},
            clear=False,
        ):
            adapter, _ = self._adapter(tmpdir)
            loaded = adapter.load_profile_documents()
            self.assertEqual(loaded["master_profile"]["profile"], {})
            self.assertEqual(loaded["projects"], {"projects": []})
            self.assertEqual(loaded["skills"], {"skill_groups": []})
            self.assertEqual(loaded["experience"], {"experiences": []})
            self.assertEqual(loaded["education"], {"education": []})
            self.assertEqual(loaded["certifications"], {"certifications": []})
            self.assertEqual(loaded["achievements"], {"achievements": []})

    def test_achievements_use_only_stored_profile_document_scope(self):
        profile = self._profile_fixture()
        profile["master_profile"]["record_indexes"]["achievement_ids"] = ["achievement_not_stored"]
        database = self._database_for(profile)
        database["profile_documents"].pop("achievements")
        database["profile_documents"]["achievements"] = {
            "achievements": [{"record_id": "achievement_saved", "name": "Stored Achievement"}]
        }
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@ep-neon-staging.neon.tech/neondb"},
            clear=False,
        ):
            adapter, _ = self._adapter(tmpdir, database)
            loaded = adapter.load_profile_documents()
            self.assertEqual(loaded["achievements"]["achievements"], [{"record_id": "achievement_saved", "name": "Stored Achievement"}])

        database["profile_documents"].pop("achievements")
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@ep-neon-staging.neon.tech/neondb"},
            clear=False,
        ):
            adapter, _ = self._adapter(tmpdir, database)
            self.assertEqual(adapter.load_profile_documents()["achievements"], {"achievements": []})

    def test_postgres_adapter_uses_postgres_backend_and_preserves_shapes(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@ep-neon-staging.neon.tech/neondb",
            },
            clear=False,
        ):
            adapter = PostgresStorageAdapter(root=tmpdir)
            adapter.client = Mock()
            adapter.client.healthcheck.return_value = {"backend": "postgres", "configured": True, "ready": True, "reachable": True, "error": None}
            adapter.client.connect.return_value = DummyConnection()

            payload = {
                "master_profile": {
                    "profile": {"name": "Jane Doe", "links": {"linkedin": "linkedin.com/in/jane"}},
                    "source_documents": [{"source_id": "resume"}],
                    "record_indexes": {"project_ids": ["project_1"]},
                    "conflicts_requiring_review": [],
                },
                "skills": {"skill_groups": [{"category": "programming_languages", "skills": [{"name": "Python"}]}]},
                "projects": {"projects": [{"record_id": "project_1", "name": "Demo"}]},
                "experience": {"experiences": []},
                "certifications": {"certifications": []},
                "education": {"education": []},
                "achievements": {"achievements": []},
            }

            adapter.save_profile_documents(payload)
            loaded = adapter.load_profile_documents()
            self.assertEqual(loaded["master_profile"]["profile"]["name"], "Jane Doe")
            self.assertEqual(adapter.validate(), [])

    def test_postgres_adapter_fails_closed_on_unhealthy_stage(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@ep-neon-staging.neon.tech/neondb",
            },
            clear=False,
        ):
            adapter = PostgresStorageAdapter(root=tmpdir)
            adapter.client = Mock()
            adapter.client.healthcheck.return_value = {"backend": "postgres", "configured": True, "ready": False, "reachable": False, "error": "timeout"}

            with self.assertRaises(RuntimeError):
                adapter.save_profile_documents({"master_profile": {"profile": {}}, "skills": {"skill_groups": []}, "projects": {"projects": []}, "experience": {"experiences": []}, "certifications": {"certifications": []}, "education": {"education": []}, "achievements": {"achievements": []}})

    def test_postgres_adapter_refuses_non_postgres_backend(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"CAREER_OS_STORAGE_BACKEND": "file"}, clear=False):
            adapter = PostgresStorageAdapter(root=tmpdir)
            self.assertFalse(adapter.is_ready())
            with self.assertRaises(RuntimeError):
                adapter.load_profile_documents()


if __name__ == "__main__":
    unittest.main()
