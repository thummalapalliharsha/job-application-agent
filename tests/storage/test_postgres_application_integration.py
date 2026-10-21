"""Opt-in integration tests for application persistence on local PostgreSQL only."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import application_assistant as aa
import postgres_storage_adapter as postgres_storage
import profile_update_agent as pua
from postgres_config import PostgresConfig
from postgres_storage_adapter import PostgresStorageAdapter
from profile_security import hash_profile_pin
from storage_adapter import profile_documents_revision


EXPECTED_HOST = "127.0.0.1"
EXPECTED_PORT = 55432
EXPECTED_DATABASE = "career_test"
EXPECTED_USER = "career_test"
PASSWORD_ENVIRONMENT_VARIABLE = "CAREER_OS_TEST_POSTGRES_PASSWORD"
LIBPQ_TARGET_ENVIRONMENT_VARIABLES = (
    "POSTGRES_URL",
    "DATABASE_URL",
    "CAREER_OS_POSTGRES_URL",
    "POSTGRES_HOST",
    "PGHOST",
    "PGHOSTADDR",
    "CAREER_OS_POSTGRES_HOST",
    "POSTGRES_PORT",
    "PGPORT",
    "CAREER_OS_POSTGRES_PORT",
    "POSTGRES_DB",
    "PGDATABASE",
    "CAREER_OS_POSTGRES_DB",
    "POSTGRES_USER",
    "PGUSER",
    "CAREER_OS_POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "PGPASSWORD",
    "CAREER_OS_POSTGRES_PASSWORD",
    "PGPASSFILE",
    "PGSERVICE",
    "PGSERVICEFILE",
    "PGSSLMODE",
    "PGOPTIONS",
    "PGTARGETSESSIONATTRS",
)


class PostgresApplicationIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend_patch = patch.dict(
            os.environ,
            {"CAREER_OS_STORAGE_BACKEND": "postgres"},
            clear=False,
        )
        cls.backend_patch.start()
        cls.addClassCleanup(cls.backend_patch.stop)
        cls.saved_connection_environment = {
            key: os.environ.pop(key)
            for key in LIBPQ_TARGET_ENVIRONMENT_VARIABLES
            if key in os.environ
        }
        cls.addClassCleanup(cls._restore_connection_environment)

        if postgres_storage.psycopg is None:
            raise unittest.SkipTest("psycopg is not installed.")

        password = os.environ.get(PASSWORD_ENVIRONMENT_VARIABLE, "")
        if not password:
            raise unittest.SkipTest(
                f"Set {PASSWORD_ENVIRONMENT_VARIABLE} for the disposable local database."
            )

        cls.config = PostgresConfig(
            backend="postgres",
            host=EXPECTED_HOST,
            port=EXPECTED_PORT,
            database=EXPECTED_DATABASE,
            user=EXPECTED_USER,
            password=password,
            url="",
            sslmode="disable",
        )
        cls._assert_exact_target(cls.config)

        cls.identity_adapter = PostgresStorageAdapter(config=cls.config)
        cls.addClassCleanup(cls.identity_adapter.client.close)
        connection_kwargs = cls.identity_adapter.client._connection_kwargs()
        if (
            connection_kwargs.get("host") != EXPECTED_HOST
            or connection_kwargs.get("port") != EXPECTED_PORT
            or connection_kwargs.get("dbname") != EXPECTED_DATABASE
            or connection_kwargs.get("user") != EXPECTED_USER
            or "conninfo" in connection_kwargs
        ):
            raise RuntimeError("PostgreSQL connection arguments did not match the local target.")

        connection = cls.identity_adapter.client.connect()
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT current_database(), current_user, current_setting('server_version_num')::integer"
                )
                identity = cursor.fetchone()
                cursor.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'application_records'
                    ORDER BY ordinal_position
                    """
                )
                columns = {row[0] for row in cursor.fetchall()}
                cursor.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'document_history_records'
                    """
                )
                history_columns = {row[0] for row in cursor.fetchall()}
                cursor.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = 'document_history_migrations'
                    )
                    """
                )
                history_migration_table_exists = cursor.fetchone()[0]

        if identity is None:
            raise RuntimeError("Could not verify local PostgreSQL database identity.")
        database_name, username, version_number = identity
        if (database_name, username) != (EXPECTED_DATABASE, EXPECTED_USER):
            raise RuntimeError("PostgreSQL identity did not match the approved local test target.")
        if version_number // 10000 != 16:
            raise RuntimeError("The approved local PostgreSQL target is not PostgreSQL 16.")
        required_columns = {
            "application_id",
            "payload_json",
            "job_description_reference",
            "phase8_plan_reference",
            "resume_reference",
            "cover_letter_reference",
            "selected_projects",
            "selected_skill_names",
            "updated_at",
        }
        if columns != required_columns:
            raise RuntimeError("application_records schema does not match the expected test schema.")
        if not {
            "document_id",
            "application_id",
            "payload_json",
            "history_position",
            "created_at",
            "updated_at",
        } <= history_columns:
            raise RuntimeError("document_history_records schema does not match the expected test schema.")
        if not history_migration_table_exists:
            raise RuntimeError("document_history_migrations schema is missing.")

    @staticmethod
    def _assert_exact_target(config: PostgresConfig) -> None:
        target = (config.host, config.port, config.database, config.user, config.url)
        expected = (EXPECTED_HOST, EXPECTED_PORT, EXPECTED_DATABASE, EXPECTED_USER, "")
        if target != expected:
            raise RuntimeError("Refusing PostgreSQL integration test outside the exact local target.")

    @classmethod
    def _restore_connection_environment(cls) -> None:
        for key in LIBPQ_TARGET_ENVIRONMENT_VARIABLES:
            os.environ.pop(key, None)
        os.environ.update(cls.saved_connection_environment)

    def setUp(self):
        self.storage_temporary = tempfile.TemporaryDirectory(prefix="career-os-pg-integration-root-")
        self.addCleanup(self.storage_temporary.cleanup)
        self.adapter = PostgresStorageAdapter(
            root=self.storage_temporary.name,
            config=self.config,
        )
        self.created_records: dict[str, dict] = {}
        self.addCleanup(self._cleanup_created_records)

    def _new_record(self) -> dict:
        application_id = f"it_app_{uuid.uuid4().hex}"
        return {
            "application_id": application_id,
            "company_name": "PostgreSQL Integration Test",
            "job_title": "Persistence Test",
            "current_status": "saved",
            "application_notes": [{"text": "initial", "timestamp": "test"}],
            "selected_projects": ["Test Project"],
            "selected_skills": ["Test Skill"],
            "job_description_reference": "job_descriptions/integration-test.txt",
            "phase8_plan_reference": "output/reports/integration-test.json",
        }

    def _insert_record(self, record: dict) -> None:
        self.adapter.insert_application(record)
        self.created_records[record["application_id"]] = copy.deepcopy(record)

    def _cleanup_created_records(self) -> None:
        try:
            for application_id, expected in list(self.created_records.items()):
                deleted = self.adapter.delete_application(application_id, expected=expected)
                if deleted is None:
                    raise AssertionError(
                        "A test-created row changed unexpectedly; it was left untouched."
                    )
                self.created_records.pop(application_id)
        finally:
            self.adapter.client.close()

    def _history_adapter(self, root: Path) -> PostgresStorageAdapter:
        adapter = PostgresStorageAdapter(root=root, config=self.config)
        self.addCleanup(adapter.client.close)
        return adapter

    def _remove_legacy_migration_marker(self, source_hash: str) -> None:
        try:
            connection = self.adapter.client.connect()
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        DELETE FROM document_history_migrations
                        WHERE migration_id = %s AND source_sha256 = %s
                        """,
                        ("legacy_document_history_v1", source_hash),
                    )
        finally:
            self.adapter.client.close()

    def test_document_history_crud_restart_and_application_delete(self):
        record = self._new_record()
        self._insert_record(record)
        with tempfile.TemporaryDirectory(prefix="career-os-pg-history-") as temporary:
            root = Path(temporary)
            adapter = self._history_adapter(root)
            entry = adapter.append_document_history(
                {
                    "application_id": record["application_id"],
                    "kind": "resume",
                    "company": "Initial",
                }
            )
            document_id = entry["document_id"]
            self.assertEqual(adapter.load_document_history(), {"documents": [entry]})

            updated = adapter.replace_document_history_entry(
                document_id,
                {
                    "application_id": record["application_id"],
                    "kind": "cover_letter",
                    "company": "Updated",
                },
            )
            self.assertEqual(updated["document_id"], document_id)
            restarted = self._history_adapter(root)
            self.assertEqual(restarted.load_document_history(), {"documents": [updated]})
            self.assertEqual(restarted.delete_document_history_entry(document_id), updated)
            self.assertEqual(restarted.load_document_history(), {"documents": []})

            second = restarted.append_document_history(
                {"application_id": record["application_id"], "kind": "resume"}
            )
            deleted = self.adapter.delete_application(
                record["application_id"],
                expected=record,
            )
            self.assertEqual(deleted, record)
            self.created_records.pop(record["application_id"])
            self.assertEqual(restarted.load_document_history(), {"documents": []})
            self.assertNotEqual(second["document_id"], document_id)

    def test_document_history_snapshot_write_rolls_back_after_injected_failure(self):
        record = self._new_record()
        self._insert_record(record)
        with tempfile.TemporaryDirectory(prefix="career-os-pg-history-rollback-") as temporary:
            adapter = self._history_adapter(Path(temporary))
            existing = adapter.append_document_history(
                {"application_id": record["application_id"], "kind": "existing"}
            )
            original_insert = adapter._insert_document_history_entry

            def fail_after_insert(cursor, entry):
                original_insert(cursor, entry)
                raise RuntimeError("injected history write failure")

            replacement = {
                "documents": [
                    {"document_id": f"new-{uuid.uuid4().hex}", "application_id": record["application_id"], "kind": "first"},
                    {"document_id": f"new-{uuid.uuid4().hex}", "application_id": record["application_id"], "kind": "second"},
                ]
            }
            with patch.object(adapter, "_insert_document_history_entry", side_effect=fail_after_insert):
                with self.assertRaisesRegex(RuntimeError, "injected history write failure"):
                    adapter.save_document_history(replacement)
            self.assertEqual(adapter.load_document_history(), {"documents": [existing]})

    def test_legacy_history_migration_preserves_duplicates_and_source(self):
        record = self._new_record()
        self._insert_record(record)
        first_entry = {
            "application_id": record["application_id"],
            "kind": "resume",
            "company": "Before duplicates",
        }
        duplicate_entry = {
            "application_id": record["application_id"],
            "kind": "resume",
            "company": "Duplicate legacy record",
        }
        source = json.dumps(
            {"documents": [first_entry, duplicate_entry, duplicate_entry]},
            ensure_ascii=False,
        ).encode("utf-8")
        source_hash = hashlib.sha256(source).hexdigest()
        self.addCleanup(self._remove_legacy_migration_marker, source_hash)
        with tempfile.TemporaryDirectory(prefix="career-os-pg-history-migrate-") as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir(parents=True)
            legacy_path = data / "document_history.json"
            legacy_path.write_bytes(source)
            adapter = self._history_adapter(root)
            migrated = adapter.load_document_history()["documents"]
            reread = adapter.load_document_history()["documents"]

            self.assertEqual(len(migrated), 3)
            self.assertEqual(migrated, reread)
            self.assertEqual(
                [item["company"] for item in migrated],
                ["Before duplicates", "Duplicate legacy record", "Duplicate legacy record"],
            )
            self.assertNotEqual(migrated[1]["document_id"], migrated[2]["document_id"])
            self.assertEqual(legacy_path.read_bytes(), source)
            self.assertEqual(
                {item["application_id"] for item in migrated},
                {record["application_id"]},
            )

    def test_malformed_legacy_history_fails_without_import_or_overwrite(self):
        for source in (b"not json", b'{"documents": "invalid"}'):
            with tempfile.TemporaryDirectory(prefix="career-os-pg-history-malformed-") as temporary:
                root = Path(temporary)
                data = root / "data"
                data.mkdir(parents=True)
                legacy_path = data / "document_history.json"
                legacy_path.write_bytes(source)
                adapter = self._history_adapter(root)

                with self.assertRaisesRegex(postgres_storage.DocumentHistoryMigrationError, "not imported"):
                    adapter.load_document_history()
                self.assertEqual(legacy_path.read_bytes(), source)
                connection = adapter.client.connect()
                with connection.transaction():
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT COUNT(*) FROM document_history_migrations WHERE migration_id = %s",
                            ("legacy_document_history_v1",),
                        )
                        self.assertEqual(cursor.fetchone()[0], 0)

    def test_legacy_history_migration_refuses_to_merge_existing_database_rows(self):
        record = self._new_record()
        self._insert_record(record)
        with tempfile.TemporaryDirectory(prefix="career-os-pg-history-conflict-") as temporary:
            root = Path(temporary)
            adapter = self._history_adapter(root)
            existing = adapter.append_document_history(
                {"application_id": record["application_id"], "kind": "postgres"}
            )
            data = root / "data"
            data.mkdir(parents=True)
            legacy_path = data / "document_history.json"
            source = json.dumps(
                {"documents": [{"application_id": record["application_id"], "kind": "legacy"}]}
            ).encode("utf-8")
            legacy_path.write_bytes(source)

            with self.assertRaisesRegex(
                postgres_storage.DocumentHistoryConflictError,
                "refusing to merge or overwrite",
            ):
                adapter.load_document_history()
            self.assertEqual(legacy_path.read_bytes(), source)
            legacy_path.unlink()
            self.assertEqual(adapter.load_document_history(), {"documents": [existing]})

    def test_insert_read_mutate_and_expected_delete(self):
        original = self._new_record()
        self._insert_record(original)

        loaded = self.adapter.load_application_store()["applications"]
        self.assertIn(original, loaded)

        updated = self.adapter.mutate_application(
            original["application_id"],
            lambda current: current.update(
                {
                    "current_status": "interview",
                    "application_notes": [{"text": "updated", "timestamp": "test"}],
                }
            ),
        )
        expected_updated = copy.deepcopy(original)
        expected_updated.update(
            {
                "current_status": "interview",
                "application_notes": [{"text": "updated", "timestamp": "test"}],
            }
        )
        self.assertEqual(updated, expected_updated)
        self.created_records[original["application_id"]] = copy.deepcopy(expected_updated)
        self.assertIn(
            expected_updated,
            self.adapter.load_application_store()["applications"],
        )

        self.assertIsNone(
            self.adapter.delete_application(original["application_id"], expected=original)
        )
        loaded_after_stale_delete = {
            item["application_id"]: item
            for item in self.adapter.load_application_store()["applications"]
        }
        self.assertEqual(
            loaded_after_stale_delete[original["application_id"]],
            expected_updated,
        )

        deleted = self.adapter.delete_application(
            original["application_id"],
            expected=expected_updated,
        )
        self.assertEqual(deleted, expected_updated)
        self.assertNotIn(
            original["application_id"],
            {
                item["application_id"]
                for item in self.adapter.load_application_store()["applications"]
            },
        )
        self.created_records.pop(original["application_id"])

    def test_duplicate_insert_fails_without_changing_original(self):
        original = self._new_record()
        self._insert_record(original)

        with self.assertRaises(postgres_storage.psycopg.errors.UniqueViolation):
            self.adapter.insert_application({**original, "current_status": "corrupted"})

        loaded = self.adapter.load_application_store()["applications"]
        self.assertIn(original, loaded)
        self.assertNotIn(
            {**original, "current_status": "corrupted"},
            loaded,
        )

    def test_mutation_callback_failure_rolls_back_changes(self):
        original = self._new_record()
        self._insert_record(original)

        def fail_after_mutating(current):
            current["current_status"] = "must_not_persist"
            raise RuntimeError("injected mutation callback failure")

        with self.assertRaisesRegex(RuntimeError, "injected mutation callback failure"):
            self.adapter.mutate_application(original["application_id"], fail_after_mutating)

        self.assertIn(
            original,
            self.adapter.load_application_store()["applications"],
        )

    def test_stale_profile_update_is_rejected_after_concurrent_postgres_commit(self):
        original_profile = self.adapter.load_profile_documents()
        expected_revision = profile_documents_revision(original_profile)
        concurrent_profile = copy.deepcopy(original_profile)
        concurrent_profile["master_profile"].setdefault("profile", {})["location"] = (
            f"Concurrent update {uuid.uuid4().hex}"
        )
        stale_adapter = PostgresStorageAdapter(config=self.config)
        ready_to_persist = threading.Event()
        continue_stale_update = threading.Event()
        result: list[BaseException | str] = []

        def pause_before_persist(_documents):
            ready_to_persist.set()
            if not continue_stale_update.wait(timeout=10):
                raise TimeoutError("Concurrent profile update was not released.")

        def stale_update():
            plan = {
                "decision": "planned",
                "base_revision": expected_revision,
                "actions": [{
                    "action": "update_profile_fields",
                    "category": "master_profile",
                    "selector": {},
                    "fields": {"headline": f"Stale update {uuid.uuid4().hex}"},
                }],
            }
            try:
                pua.apply_plan(
                    plan,
                    root=Path(tempfile.gettempdir()) / "career-os-pg-stale-profile-test",
                    confirm=True,
                    pin="123456",
                    _before_persist=pause_before_persist,
                )
            except Exception as exc:
                result.append(exc)
            else:
                result.append("stale update unexpectedly succeeded")

        worker = threading.Thread(target=stale_update)
        pin_hash = hash_profile_pin("123456")
        try:
            with patch.dict(os.environ, {"CAREER_OS_PROFILE_PIN_HASH": pin_hash}, clear=False), \
                 patch.object(pua, "_storage_adapter", return_value=stale_adapter), \
                 patch.object(pua, "all_data", side_effect=lambda _root=None: stale_adapter.load_profile_documents()):
                worker.start()
                self.assertTrue(ready_to_persist.wait(timeout=10))
                self.adapter.save_profile_documents(concurrent_profile)
                continue_stale_update.set()
                worker.join(timeout=15)

            self.assertFalse(worker.is_alive(), "Stale profile update did not finish.")
            self.assertEqual(len(result), 1)
            self.assertIsInstance(result[0], RuntimeError)
            self.assertRegex(str(result[0]), "Profile data changed during profile update")
            self.assertEqual(
                self.adapter.load_profile_documents(),
                self.adapter.normalize_profile_documents(concurrent_profile),
            )
        finally:
            continue_stale_update.set()
            if worker.is_alive():
                worker.join(timeout=15)
            stale_adapter.client.close()
            self.adapter.save_profile_documents(original_profile)

    def test_concurrent_cover_letter_edits_use_postgres_reference_compare_and_swap(self):
        application_id = f"it_cover_letter_{uuid.uuid4().hex}"
        temporary = tempfile.TemporaryDirectory(prefix="career-os-pg-cover-letter-")
        root = Path(temporary.name)
        letters = root / "output" / "cover_letters"
        letters.mkdir(parents=True)
        original_reference = "output/cover_letters/active.md"
        finalized_reference = "output/cover_letters/finalized.md"
        original_path = root / original_reference
        finalized_path = root / finalized_reference
        original_path.write_text("Original working letter.\n", encoding="utf-8")
        finalized_path.write_text("Finalized letter.\n", encoding="utf-8")
        application = {
            "application_id": application_id,
            "company_name": "Example Co",
            "job_title": "Persistence Test",
            "current_status": "saved",
            "cover_letter_working_reference": original_reference,
            "cover_letter_source_reference": original_reference,
            "cover_letter_reference": finalized_reference,
        }
        self._insert_record(application)
        barrier = threading.Barrier(2)
        original_mutate = aa.mutate_application
        results: list[dict] = []
        errors: list[BaseException] = []

        def postgres_adapter(root=None):
            return PostgresStorageAdapter(root=root, config=self.config)

        def synchronized_mutate(aid, mutation, root=None):
            barrier.wait(timeout=10)
            return original_mutate(aid, mutation, root=root)

        def edit(content):
            try:
                results.append(aa.edit_cover_letter(application_id, content))
            except Exception as exc:
                errors.append(exc)

        workers = [
            threading.Thread(
                target=edit,
                args=(f"Letter for Example Co: edit {index}.",),
            )
            for index in (1, 2)
        ]
        try:
            with patch.dict(os.environ, {"CAREER_OS_STORAGE_BACKEND": "postgres"}, clear=False), \
                 patch.object(aa, "_application_store_adapter", side_effect=postgres_adapter), \
                 patch.object(aa, "mutate_application", side_effect=synchronized_mutate), \
                 patch.object(aa, "resolve_storage_reference", side_effect=lambda ref: root / ref), \
                 patch.object(aa, "ROOT", root), \
                 patch.object(aa, "DATA", root / "data"), \
                 patch.object(aa, "LETTERS", letters):
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join(timeout=20)

            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertEqual(errors, [])
            self.assertCountEqual(
                [result["decision"] for result in results],
                ["saved", "conflict"],
            )
            current = next(
                record
                for record in self.adapter.load_application_store()["applications"]
                if record["application_id"] == application_id
            )
            active_reference = current["cover_letter_working_reference"]
            self.assertEqual(current["cover_letter_source_reference"], active_reference)
            self.assertEqual(current["cover_letter_reference"], finalized_reference)
            active_path = root / active_reference
            saved_result = next(item for item in results if item["decision"] == "saved")
            self.assertEqual(active_path.read_text(encoding="utf-8"), saved_result["content"])
            self.assertEqual(original_path.read_text(encoding="utf-8"), "Original working letter.\n")
            self.assertEqual(finalized_path.read_text(encoding="utf-8"), "Finalized letter.\n")
            self.assertEqual(len(list(letters.glob("*.md"))), 4)
            self.created_records[application_id] = current
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.join(timeout=20)
            try:
                self.created_records[application_id] = next(
                    record
                    for record in self.adapter.load_application_store()["applications"]
                    if record["application_id"] == application_id
                )
            except StopIteration:
                self.created_records.pop(application_id, None)
            temporary.cleanup()

    def test_invalid_postgres_config_fails_closed_without_file_fallback(self):
        with tempfile.TemporaryDirectory(prefix="postgres-no-fallback-") as temporary:
            root = Path(temporary)
            data_directory = root / "data"
            data_directory.mkdir()
            sentinel = data_directory / "applications.json"
            sentinel_bytes = b'{"applications":[{"application_id":"file_sentinel"}]}\n'
            sentinel.write_bytes(sentinel_bytes)

            invalid_config = PostgresConfig(
                backend="postgres",
                host="",
                port=EXPECTED_PORT,
                database="",
                user="",
                password="",
                url="",
                sslmode="disable",
            )
            adapter = PostgresStorageAdapter(root=root, config=invalid_config)
            with patch.object(adapter.client, "healthcheck") as healthcheck:
                with self.assertRaisesRegex(RuntimeError, "configuration is missing"):
                    adapter.load_application_store()
            healthcheck.assert_not_called()
            self.assertIsNone(adapter.client._connection)
            self.assertEqual(sentinel.read_bytes(), sentinel_bytes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
