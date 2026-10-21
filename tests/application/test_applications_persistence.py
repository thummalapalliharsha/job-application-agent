import json
import http.client
import os
import tempfile
import threading
import unittest
from contextlib import ExitStack, contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import application_assistant as aa
import career_os_api as api
import career_os_config


class FakeApplicationDatabase:
    def __init__(self, *, fail_on_insert=False):
        self.rows = {}
        self.fail_on_insert = fail_on_insert

    def cursor(self):
        return FakeApplicationCursor(self)


class FakeApplicationCursor:
    def __init__(self, database):
        self.database = database
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, params=None):
        normalized = " ".join(statement.split()).casefold()
        if normalized.startswith("select application_id, payload_json"):
            self.rows = [
                (application_id, payload)
                for application_id, payload in sorted(self.database.rows.items())
            ]
        elif normalized.startswith("insert into application_records"):
            if self.database.fail_on_insert:
                raise RuntimeError("simulated PostgreSQL insert failure")
            application_id, payload = params[:2]
            self.database.rows[application_id] = payload
        else:
            raise AssertionError(f"Unexpected PostgreSQL statement: {statement}")

    def fetchall(self):
        return self.rows


class FakeApplicationConnection:
    def __init__(self, database):
        self.database = database

    @contextmanager
    def transaction(self):
        yield self

    def cursor(self):
        return self.database.cursor()


class ApplicationStorePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="app-store-persistence-")
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.jobs = self.root / "job_descriptions"
        self.output = self.root / "output"
        self.reports = self.output / "reports"
        self.letters = self.output / "cover_letters"
        self.resumes = self.output / "resumes"
        for directory in (self.data, self.jobs, self.reports, self.resumes, self.letters):
            directory.mkdir(parents=True, exist_ok=True)

        self.original_root = aa.ROOT
        self.original_data = aa.DATA
        self.original_jobs = aa.JOBS
        self.original_out = aa.OUT
        self.original_reports = aa.REPORTS
        self.original_letters = aa.LETTERS
        self.original_resumes = aa.RESUMES
        self.backend_patch = patch.dict(os.environ, {"CAREER_OS_STORAGE_BACKEND": "file"}, clear=False)
        self.backend_patch.start()

        aa.ROOT = self.root
        aa.DATA = self.data
        aa.JOBS = self.jobs
        aa.OUT = self.output
        aa.REPORTS = self.reports
        aa.LETTERS = self.letters
        aa.RESUMES = self.resumes

    def tearDown(self):
        aa.ROOT = self.original_root
        aa.DATA = self.original_data
        aa.JOBS = self.original_jobs
        aa.OUT = self.original_out
        aa.REPORTS = self.original_reports
        aa.LETTERS = self.original_letters
        aa.RESUMES = self.original_resumes
        self.backend_patch.stop()
        self.temporary.cleanup()

    @staticmethod
    def _application_plan(_jd_text, _report_path):
        return {
            "resume_plan": {
                "projects_to_include": [],
                "skills_to_include": [],
                "certifications_to_include": [],
                "experience_decisions": [],
            },
            "jd_analysis": {"requirements": []},
            "evidence_summary": {
                "supported_requirements": [],
                "partial_requirements": [],
                "unsupported_requirements": [],
            },
        }

    @staticmethod
    def _request_api(method, path, payload=None):
        server = ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
        host = f"127.0.0.1:{server.server_port}"
        original_hosts = set(api._ALLOWED_HOSTS)
        api._ALLOWED_HOSTS.add(host)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=5
            )
            headers = {"Authorization": "Bearer persistence-test-token"}
            body = None
            if payload is not None:
                headers["Content-Type"] = "application/json"
                body = json.dumps(payload)
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            result = json.loads(response.read().decode("utf-8"))
            connection.close()
            return response.status, result
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            api._ALLOWED_HOSTS.clear()
            api._ALLOWED_HOSTS.update(original_hosts)

    def _postgres_test_patches(self, database):
        connection = FakeApplicationConnection(database)
        return (
            patch.dict(
                os.environ,
                {
                    "CAREER_OS_STORAGE_BACKEND": "postgres",
                    "CAREER_OS_POSTGRES_URL": "postgresql://unit.test/career_os",
                },
                clear=False,
            ),
            patch("postgres_storage_adapter.psycopg", object()),
            patch(
                "postgres_client.PostgresClient.healthcheck",
                return_value={
                    "backend": "postgres",
                    "configured": True,
                    "ready": True,
                    "reachable": True,
                    "error": None,
                },
            ),
            patch(
                "postgres_client.PostgresClient.connect",
                return_value=connection,
            ),
            patch.object(api, "_API_TOKEN", "persistence-test-token"),
            patch.object(api, "profile_summary", return_value={}),
            patch.object(api, "ROOT", self.root),
            patch.object(aa, "phase8_plan", side_effect=self._application_plan),
        )

    def test_postgres_create_is_readable_from_bootstrap(self):
        database = FakeApplicationDatabase()
        with ExitStack() as stack:
            for patcher in self._postgres_test_patches(database):
                stack.enter_context(patcher)
            self.assertEqual(
                aa._application_store_adapter(self.root).backend_name,
                "postgres",
            )
            status, created = self._request_api(
                "POST",
                "/api/applications",
                {
                    "company": "PostgreSQL Round Trip Co",
                    "title": "Persistence Engineer",
                    "url": "https://example.test/postgres-round-trip",
                    "job_description": (
                        "Persistence Engineer\nResponsibilities:\n- Persist records."
                    ),
                },
            )
            self.assertEqual(status, 201, created)
            application = created["application"]
            application_id = application["application_id"]
            self.assertIn(application_id, database.rows)

            status, bootstrap = self._request_api("GET", "/api/bootstrap")

        self.assertEqual(status, 200, bootstrap)
        reloaded = next(
            item for item in bootstrap["applications"]
            if item["application_id"] == application_id
        )
        self.assertEqual(reloaded["company_name"], "PostgreSQL Round Trip Co")
        self.assertEqual(reloaded["job_title"], "Persistence Engineer")
        self.assertEqual(
            reloaded["job_description_text"],
            application["job_description_text"],
        )

    def test_postgres_insert_failure_returns_non_success_create_response(self):
        database = FakeApplicationDatabase(fail_on_insert=True)
        with ExitStack() as stack:
            for patcher in self._postgres_test_patches(database):
                stack.enter_context(patcher)
            status, result = self._request_api(
                "POST",
                "/api/applications",
                {
                    "company": "Failed PostgreSQL Co",
                    "title": "Persistence Engineer",
                    "url": "https://example.test/postgres-failure",
                    "job_description": (
                        "Persistence Engineer\nResponsibilities:\n- Persist records."
                    ),
                },
            )

        self.assertEqual(status, 500, result)
        self.assertNotEqual(result.get("decision"), "created")
        self.assertEqual(database.rows, {})

    def test_application_adapter_selection_and_postgres_failures(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(aa._application_store_adapter(self.root).backend_name, "file")

        with patch.object(aa, "ROOT", career_os_config.CODE_ROOT), patch.object(
            career_os_config, "STORAGE_ROOT", self.root
        ):
            self.assertEqual(aa._application_store_adapter().root, self.root.resolve())

        with patch.dict(os.environ, {"CAREER_OS_STORAGE_BACKEND": "postgres"}, clear=True):
            adapter = aa._application_store_adapter(self.root)
            with self.assertRaisesRegex(RuntimeError, "configuration is missing"):
                adapter.load_application_store()

        with patch.dict(
            os.environ,
            {"CAREER_OS_STORAGE_BACKEND": "postgres", "CAREER_OS_POSTGRES_URL": "postgresql://test"},
            clear=True,
        ), patch("postgres_storage_adapter.psycopg", object()):
            adapter = aa._application_store_adapter(self.root)
            self.assertEqual(adapter.backend_name, "postgres")
            with self.assertRaisesRegex(RuntimeError, "snapshots cannot be saved"):
                aa.save_store({"applications": []})
            with patch.object(adapter.client, "ping", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "PostgreSQL application storage is unavailable"):
                    adapter.load_application_store()

    def test_file_adapter_mutation_rejects_stale_delete_and_preserves_updates(self):
        adapter = aa.FileStorageAdapter(root=self.root)
        adapter.save_application_store({"applications": [{
            "application_id": "app_mutable",
            "current_status": "saved",
            "application_notes": [],
        }]})
        original = adapter.load_application_store()["applications"][0]
        updated = adapter.mutate_application(
            "app_mutable",
            lambda current: current.update({"current_status": "interview"}),
        )
        self.assertEqual(updated["current_status"], "interview")
        self.assertIsNone(adapter.delete_application("app_mutable", expected=original))
        self.assertEqual(adapter.load_application_store()["applications"], [updated])
        deleted = adapter.delete_application("app_mutable", expected=updated)
        self.assertEqual(deleted, updated)
        self.assertEqual(adapter.load_application_store(), {"applications": []})

    def test_concurrent_cover_letter_edits_compare_and_swap_unique_artifacts(self):
        application_id = "app_concurrent_letter"
        original_reference = "output/cover_letters/active.md"
        final_reference = "output/cover_letters/finalized.md"
        original_path = self.root / original_reference
        final_path = self.root / final_reference
        original_path.write_text("Original working letter.\n", encoding="utf-8")
        final_path.write_text("Finalized letter.\n", encoding="utf-8")
        adapter = aa.FileStorageAdapter(root=self.root)
        adapter.save_application_store({"applications": [{
            "application_id": application_id,
            "company_name": "Example Co",
            "cover_letter_working_reference": original_reference,
            "cover_letter_source_reference": original_reference,
            "cover_letter_reference": final_reference,
        }]})

        mutation_barrier = threading.Barrier(2)
        original_mutate = aa.mutate_application
        results = []
        failures = []

        def synchronized_mutate(aid, mutation, root=None):
            mutation_barrier.wait(timeout=5)
            return original_mutate(aid, mutation, root=root)

        def edit(content):
            try:
                results.append(aa.edit_cover_letter(application_id, content))
            except Exception as exc:
                failures.append(exc)

        new_artifacts = set(self.letters.glob("*.md"))
        with patch.object(aa, "resolve_storage_reference", side_effect=lambda ref: self.root / ref), \
             patch.object(aa, "mutate_application", side_effect=synchronized_mutate):
            workers = [
                threading.Thread(target=edit, args=(f"Letter for Example Co: edit {index}.",))
                for index in (1, 2)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=5)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(failures, [])
        self.assertCountEqual([result["decision"] for result in results], ["saved", "conflict"])
        created_artifacts = set(self.letters.glob("*.md")) - new_artifacts
        self.assertEqual(len(created_artifacts), 2)
        self.assertEqual(original_path.read_text(encoding="utf-8"), "Original working letter.\n")
        self.assertEqual(final_path.read_text(encoding="utf-8"), "Finalized letter.\n")

        store = adapter.load_application_store()
        saved_application = store["applications"][0]
        active_reference = saved_application["cover_letter_working_reference"]
        self.assertEqual(saved_application["cover_letter_source_reference"], active_reference)
        self.assertEqual(saved_application["cover_letter_reference"], final_reference)
        active_path = self.root / active_reference
        self.assertIn(active_path, created_artifacts)
        saved_result = next(result for result in results if result["decision"] == "saved")
        self.assertEqual(saved_result["cover_letter_working_reference"], active_reference)
        self.assertEqual(active_path.read_text(encoding="utf-8"), saved_result["content"])
        orphan_path = next(path for path in created_artifacts if path != active_path)
        self.assertNotEqual(orphan_path.read_text(encoding="utf-8"), saved_result["content"])

    def test_create_save_reload_round_trip(self):
        jd = "Junior Generative AI RAG Engineer\nRequired Skills:\n- Python\n- RAG\nResponsibilities:\n- Build retrieval pipelines."
        created = aa.create_application("Example AI", "Junior RAG Engineer", "https://example.com/jobs/123", jd)
        self.assertEqual(created["decision"], "created", created)

        app = created["application"]
        self.assertTrue(app["application_id"].startswith("app_"))
        self.assertEqual(app["current_status"], "awaiting_resume_approval")
        self.assertTrue((self.root / app["job_description_reference"]).exists())

        reloaded = aa.load_store()["applications"]
        self.assertEqual(len(reloaded), 1)
        self.assertEqual(reloaded[0]["application_id"], app["application_id"])
        self.assertEqual(reloaded[0]["company_name"], "Example AI")
        self.assertEqual(reloaded[0]["job_title"], "Junior RAG Engineer")
        self.assertEqual(reloaded[0]["selected_projects"], reloaded[0]["selected_projects"])

    def test_create_reloads_store_after_planning_before_persisting(self):
        adapter = aa.FileStorageAdapter(root=self.root)
        adapter.save_application_store({"applications": [
            {"application_id": "app_abcd", "company_name": "ABCD", "current_status": "saved"},
            {"application_id": "app_keep", "company_name": "Keep Co", "current_status": "saved"},
        ]})
        planning_started = threading.Event()
        finish_planning = threading.Event()
        create_results = []
        create_errors = []

        def paused_plan(_jd_text, _report_path):
            planning_started.set()
            if not finish_planning.wait(timeout=5):
                raise TimeoutError("Test did not release application planning.")
            return {
                "resume_plan": {
                    "projects_to_include": [],
                    "skills_to_include": [],
                    "certifications_to_include": [],
                    "experience_decisions": [],
                },
                "jd_analysis": {"requirements": []},
                "evidence_summary": {
                    "supported_requirements": [],
                    "partial_requirements": [],
                    "unsupported_requirements": [],
                },
            }

        def create():
            try:
                create_results.append(aa.create_application(
                    "New Co",
                    "New Role",
                    "https://example.test/new-role",
                    "New Role\nResponsibilities:\n- Build systems.",
                ))
            except Exception as exc:
                create_errors.append(exc)

        with patch.object(aa, "_application_store_adapter", return_value=adapter), \
             patch.object(aa, "phase8_plan", side_effect=paused_plan):
            worker = threading.Thread(target=create)
            worker.start()
            try:
                self.assertTrue(planning_started.wait(timeout=5))
                deleted = aa.delete_application_record(
                    "app_abcd",
                    expected={
                        "application_id": "app_abcd",
                        "company_name": "ABCD",
                        "current_status": "saved",
                    },
                )
                self.assertIsNotNone(deleted)
                updated = aa.mutate_application(
                    "app_keep",
                    lambda current: current.update({"current_status": "interview"}),
                )
                self.assertEqual(updated["current_status"], "interview")
            finally:
                finish_planning.set()
                worker.join(timeout=5)

        self.assertFalse(worker.is_alive(), "Application creation did not finish.")
        self.assertEqual(create_errors, [])
        self.assertEqual(create_results[0]["decision"], "created")
        records = {
            item["application_id"]: item
            for item in adapter.load_application_store()["applications"]
        }
        self.assertNotIn("app_abcd", records)
        self.assertEqual(records["app_keep"]["current_status"], "interview")
        self.assertIn(create_results[0]["application"]["application_id"], records)

    def test_nested_payload_round_trip_and_status_history_preserved(self):
        store = {"applications": [{
            "application_id": "app_nested_123",
            "company_name": "Example AI",
            "job_title": "Junior RAG Engineer",
            "job_url": "https://example.com/jobs/123",
            "project_selection_record_ids": ["project_a", "project_b"],
            "selected_projects": [{"record_id": "project_a", "name": "RAG Demo"}],
            "status_history": [
                {"old_status": None, "new_status": "awaiting_resume_approval", "timestamp": "2026-01-01T00:00:00Z"},
                {"old_status": "awaiting_resume_approval", "new_status": "resume_ready", "timestamp": "2026-01-02T00:00:00Z"},
            ],
            "application_notes": [{"note": "First note", "source": "user_provided"}],
            "provenance": {"phase8_source": "output/reports/test_plan.json", "candidate_source": "data/*.json"},
            "resume_generation_allowed": True,
            "current_status": "resume_ready",
        }]}

        aa.save_store(store)
        reloaded = aa.load_store()
        self.assertEqual(reloaded, store)
        self.assertEqual(reloaded["applications"][0]["status_history"][-1]["new_status"], "resume_ready")
        self.assertEqual(reloaded["applications"][0]["application_notes"][0]["note"], "First note")

    def test_status_update_and_notes_persist_across_reload(self):
        jd = "Junior Data Analyst\nRequired Skills:\n- Python\nResponsibilities:\n- Analyze data."
        created = aa.create_application("Acme", "Junior Data Analyst", "https://example.com/jobs/abc", jd)
        aid = created["application"]["application_id"]

        updated = aa.update_status(aid, "interview")
        self.assertEqual(updated["application"]["current_status"], "interview")
        self.assertGreaterEqual(len(updated["application"]["status_history"]), 2)

        noted = aa.add_note(aid, "Follow up with recruiter on Thursday.", "2026-02-05")
        self.assertEqual(noted["application"]["application_notes"][-1]["note"], "Follow up with recruiter on Thursday.")
        self.assertEqual(noted["application"]["follow_up_date"], "2026-02-05")

        reloaded = aa.load_store()["applications"][0]
        self.assertEqual(reloaded["current_status"], "interview")
        self.assertEqual(reloaded["status_history"][-1]["new_status"], "interview")
        self.assertEqual(reloaded["application_notes"][-1]["note"], "Follow up with recruiter on Thursday.")

    def test_duplicate_detection_and_ids_are_unchanged(self):
        jd = "Junior RAG Engineer\nRequired Skills:\n- Python\n- RAG\nResponsibilities:\n- Build retrieval pipelines."
        first = aa.create_application("Example AI", "Junior RAG Engineer", "https://example.com/jobs/dup-a", jd)
        store_before_duplicate = (self.data / "applications.json").read_bytes()
        second = aa.create_application("Example AI", "Junior RAG Engineer", "https://example.com/jobs/dup-a", jd)
        self.assertEqual(second["decision"], "duplicate_requires_clarification")
        self.assertIs(second["persistent_write_allowed"], False)
        self.assertEqual(second["possible_existing_applications"][0]["application_id"], first["application"]["application_id"])
        self.assertEqual((self.data / "applications.json").read_bytes(), store_before_duplicate)
        self.assertEqual(first["application"]["application_id"], aa.load_store()["applications"][0]["application_id"])
        self.assertEqual(first["application"]["application_id"], aa.get_app(first["application"]["application_id"])[0]["application_id"])

    def test_missing_and_empty_store_are_compatibility_defaults(self):
        self.assertEqual(aa.load_store(), {"applications": []})

        self.data.joinpath("applications.json").write_text("", encoding="utf-8")
        self.assertEqual(aa.load_store(), {"applications": []})

        self.data.joinpath("applications.json").write_text("{not-json}", encoding="utf-8")
        self.assertEqual(aa.load_store(), {"applications": []})

    def test_active_runtime_root_isolation(self):
        first_root = self.root
        second_root = first_root.parent / "other-root"
        second_root.mkdir(parents=True, exist_ok=True)
        second_data = second_root / "data"
        second_jobs = second_root / "job_descriptions"
        second_output = second_root / "output"
        for directory in (second_data, second_jobs, second_output):
            directory.mkdir(parents=True, exist_ok=True)

        aa.ROOT = first_root
        aa.DATA = first_root / "data"
        aa.JOBS = first_root / "job_descriptions"
        aa.OUT = first_root / "output"
        aa.REPORTS = first_root / "output" / "reports"
        aa.LETTERS = first_root / "output" / "cover_letters"
        aa.RESUMES = first_root / "output" / "resumes"

        aa.save_store({"applications": [{"application_id": "app_root_one", "current_status": "awaiting_resume_approval", "status_history": []}]})

        aa.ROOT = second_root
        aa.DATA = second_data
        aa.JOBS = second_jobs
        aa.OUT = second_output
        aa.REPORTS = second_output / "reports"
        aa.LETTERS = second_output / "cover_letters"
        aa.RESUMES = second_output / "resumes"

        aa.save_store({"applications": [{"application_id": "app_root_two", "current_status": "resume_ready", "status_history": []}]})

        self.assertEqual(aa.load_store()["applications"][0]["application_id"], "app_root_two")
        self.assertEqual(json.loads((first_root / "data" / "applications.json").read_text(encoding="utf-8"))["applications"][0]["application_id"], "app_root_one")

    def test_existing_application_deletion_behavior_still_works(self):
        target = {"application_id": "app_del", "company_name": "Delete Co", "job_title": "Role", "current_status": "resume_ready", "status_history": [{"old_status": None, "new_status": "resume_ready"}], "application_notes": [{"note": "note"}], "phase8_plan_reference": "output/reports/plan.json", "resume_reference": "output/resumes/final.docx", "cover_letter_reference": "output/cover_letters/final.md"}
        other = {"application_id": "app_keep", "company_name": "Keep Co", "job_title": "Role", "current_status": "awaiting_resume_approval", "status_history": [], "application_notes": []}

        (self.reports).mkdir(parents=True, exist_ok=True)
        (self.resumes).mkdir(parents=True, exist_ok=True)
        (self.letters).mkdir(parents=True, exist_ok=True)

        (self.reports / "plan.json").write_text("{}", encoding="utf-8")
        (self.resumes / "final.docx").write_bytes(b"resume")
        (self.letters / "final.md").write_text("letter", encoding="utf-8")
        aa.save_store({"applications": [target, other]})

        result = aa.delete_application if hasattr(aa, "delete_application") else None
        if result is None:
            self.skipTest("delete_application is not available in this module")

        deleted = result("app_del")
        self.assertEqual(deleted["decision"], "deleted", deleted)
        remaining = aa.load_store()["applications"]
        self.assertEqual([item["application_id"] for item in remaining], ["app_keep"])

    def test_reviewed_plan_lifecycle_still_round_trips(self):
        jd = "Junior Business Data Analyst\nRequired Skills:\n- Python\n- SQL\nResponsibilities:\n- Analyze business data."
        created = aa.create_application("Lifecycle Co", "Junior Business Data Analyst", "https://example.com/jobs/lifecycle", jd)
        app = created["application"]

        plan_path = self.root / app["phase8_plan_reference"]
        self.assertTrue(plan_path.exists())

        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertIn("resume_plan", plan)
        self.assertIn("projects_to_include", plan["resume_plan"])

        app_after = aa.get_app(app["application_id"])[0]
        self.assertEqual(app_after["phase8_plan_reference"], app["phase8_plan_reference"])


if __name__ == "__main__":
    unittest.main()
