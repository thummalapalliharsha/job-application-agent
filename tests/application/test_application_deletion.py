#!/usr/bin/env python3
"""Application deletion tests using isolated temporary storage only."""
from __future__ import annotations

import copy
import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import application_assistant as aa
import career_os_api as api


class FakePostgresAdapter:
    backend_name = "postgres"

    def __init__(self, applications):
        self.applications = copy.deepcopy(applications)
        self.document_history = None
        self.before_delete_calls = 0
        self.before_check = None
        self.failure_before_check = None
        self.failure_after_staging = None
        self.crash_after_delete = None

    def load_application_store(self):
        return {"applications": copy.deepcopy(self.applications)}

    def load_document_history(self):
        if self.document_history is None:
            path = aa.DATA / "document_history.json"
            self.document_history = (
                json.loads(path.read_text(encoding="utf-8"))["documents"]
                if path.is_file()
                else []
            )
        return {"documents": copy.deepcopy(self.document_history)}

    def delete_application(self, application_id, expected=None, before_delete=None):
        if self.before_check is not None:
            self.before_check(self)
        if self.failure_before_check is not None:
            raise self.failure_before_check
        current = next(
            (item for item in self.applications if item.get("application_id") == application_id),
            None,
        )
        if current is None or current != expected:
            return None
        if before_delete is not None:
            self.before_delete_calls += 1
            before_delete()
        if self.failure_after_staging is not None:
            raise self.failure_after_staging
        self.applications = [
            item for item in self.applications if item.get("application_id") != application_id
        ]
        self.document_history = [
            item for item in (self.document_history or [])
            if item.get("application_id") != application_id
        ]
        if self.crash_after_delete is not None:
            raise self.crash_after_delete
        return copy.deepcopy(current)


class ApplicationDeletionTests(unittest.TestCase):
    application_id = "app_deadbeefcafe"
    other_application_id = "app_c0ffee123456"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="application-deletion-")
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.jobs = self.root / "job_descriptions"
        self.output = self.root / "output"
        self.reports = self.output / "reports"
        self.resumes = self.output / "resumes"
        self.letters = self.output / "cover_letters"
        self.edits = self.output / "resume_edits"
        for directory in (self.data, self.jobs, self.reports, self.resumes, self.letters, self.edits):
            directory.mkdir(parents=True, exist_ok=True)

        self.original_paths = (aa.ROOT, aa.DATA, aa.JOBS, aa.OUT, aa.REPORTS, aa.LETTERS, aa.RESUMES, api.ROOT)
        self.original_deleted_ids = set(aa.DELETED_APPLICATION_IDS)
        aa.ROOT, aa.DATA, aa.JOBS = self.root, self.data, self.jobs
        aa.OUT, aa.REPORTS, aa.LETTERS, aa.RESUMES = self.output, self.reports, self.letters, self.resumes
        api.ROOT = self.root
        aa.DELETED_APPLICATION_IDS.clear()

        self.target_refs = {
            "job_description_reference": "job_descriptions/app_deadbeefcafe_role.txt",
            "phase8_plan_reference": "output/reports/app_deadbeefcafe_phase8_plan.json",
            "resume_validation_reference": "output/reports/app_deadbeefcafe_resume_validation.json",
            "working_resume_docx_path": "output/resumes/app_deadbeefcafe_Working.docx",
            "working_resume_pdf_path": "output/resumes/app_deadbeefcafe_Working.pdf",
            "resume_reference": "output/resumes/app_deadbeefcafe_Final.docx",
            "resume_pdf_reference": "output/resumes/app_deadbeefcafe_Final.pdf",
            "working_resume_revision_reference": "output/resume_edits/app_deadbeefcafe/rev_123.json",
            "working_resume_validation_reference": "output/reports/app_deadbeefcafe_resume_document_validation.json",
            "cover_letter_working_reference": "output/cover_letters/app_deadbeefcafe_Working.md",
            "cover_letter_working_docx_reference": "output/cover_letters/app_deadbeefcafe_Working.docx",
            "cover_letter_working_pdf_reference": "output/cover_letters/app_deadbeefcafe_Working.pdf",
            "cover_letter_reference": "output/cover_letters/app_deadbeefcafe_Final.md",
            "cover_letter_pdf_reference": "output/cover_letters/app_deadbeefcafe_Final.pdf",
            "candidate_profile_path": "data/skills.json",
            "unsafe_path": "output/../../data/master_profile.json",
        }
        for key, reference in self.target_refs.items():
            if key in {"candidate_profile_path", "unsafe_path"}:
                continue
            self.write_artifact(reference)
        self.write_artifact("output/reports/app_deadbeefcafe_orphan_validation.json")
        self.write_artifact("output/resumes/app_deadbeefcafe_old_revision.pdf")
        self.write_artifact("output/resume_edits/app_deadbeefcafe/rev_123.json")
        self.write_artifact("output/resumes/shared.pdf")
        (self.data / "skills.json").write_text('{"skills": []}\n', encoding="utf-8")
        (self.data / "master_profile.json").write_text('{"profile": {}}\n', encoding="utf-8")

        self.target = {"application_id": self.application_id, "job_title": "Temporary Target", **self.target_refs}
        self.other = {
            "application_id": self.other_application_id,
            "job_title": "Temporary Other",
            "working_resume_reference": "output/resumes/shared.pdf",
        }
        (self.data / "applications.json").write_text(
            json.dumps({"applications": [self.target, self.other]}, indent=2) + "\n", encoding="utf-8"
        )
        self.history_record = {
            "document_id": "history_target",
            "application_id": self.application_id,
            "kind": "resume",
            "docx": "output/resumes/app_deadbeefcafe_history.docx",
            "pdf": "output/resumes/app_deadbeefcafe_history.pdf",
        }
        self.other_history_record = {
            "document_id": "history_other",
            "application_id": self.other_application_id,
            "kind": "resume",
            "docx": "output/resumes/shared.pdf",
        }
        self.write_artifact(self.history_record["docx"])
        self.write_artifact(self.history_record["pdf"])
        (self.data / "document_history.json").write_text(
            json.dumps({"documents": [self.history_record, self.other_history_record]}, indent=2) + "\n",
            encoding="utf-8",
        )

    def tearDown(self):
        aa.ROOT, aa.DATA, aa.JOBS, aa.OUT, aa.REPORTS, aa.LETTERS, aa.RESUMES, api.ROOT = self.original_paths
        aa.DELETED_APPLICATION_IDS.clear()
        aa.DELETED_APPLICATION_IDS.update(self.original_deleted_ids)
        self.temporary.cleanup()

    def write_artifact(self, reference):
        path = self.root / Path(reference.replace("\\", "/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("temporary application artifact\n", encoding="utf-8")
        return path

    def call_delete_route(self, application_id):
        server = ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
        host = f"127.0.0.1:{server.server_port}"
        original_hosts = set(api._ALLOWED_HOSTS)
        api._ALLOWED_HOSTS.add(host)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            headers = {"Authorization": f"Bearer {api._API_TOKEN}"} if api._API_TOKEN else {}
            connection.request("DELETE", f"/api/applications/{application_id}", headers=headers)
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

    def call_health_route(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
        host = f"127.0.0.1:{server.server_port}"
        original_hosts = set(api._ALLOWED_HOSTS)
        api._ALLOWED_HOSTS.add(host)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", "/api/health")
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

    def test_delete_removes_only_target_data_and_stale_save_cannot_restore_it(self):
        stale_store = copy.deepcopy(aa.load_store())
        result = api.delete_application(self.application_id)
        self.assertEqual(result["decision"], "deleted", result)
        self.assertEqual(result["message"], "Application removed from history.")

        aa.save_store(stale_store)
        saved = aa.load_store()["applications"]
        self.assertEqual([item["application_id"] for item in saved], [self.other_application_id])
        history = json.loads((self.data / "document_history.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [item["application_id"] for item in history["documents"]],
            [self.other_application_id],
        )

        for reference in self.target_refs.values():
            path = api.resolve_ref(reference)
            if reference.startswith("data/") or reference.startswith("output/../../"):
                self.assertTrue(path is None or path.exists())
            elif path is not None:
                self.assertFalse(path.exists(), reference)
        for reference in (
            "output/reports/app_deadbeefcafe_orphan_validation.json",
            "output/resumes/app_deadbeefcafe_old_revision.pdf",
            "output/resume_edits/app_deadbeefcafe/rev_123.json",
            self.history_record["docx"],
            self.history_record["pdf"],
        ):
            self.assertFalse((self.root / reference).exists(), reference)
        self.assertTrue((self.root / "output/resumes/shared.pdf").is_file())
        self.assertTrue((self.data / "skills.json").is_file())
        self.assertTrue((self.data / "master_profile.json").is_file())

    def test_delete_route_returns_success_then_404_for_missing_application(self):
        status, result = self.call_delete_route(self.application_id)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["decision"], "deleted")
        status, result = self.call_delete_route(self.application_id)
        self.assertEqual(status, 404, result)
        self.assertEqual(result["decision"], "not_found")

    def test_postgres_delete_uses_adapter_without_writing_application_json(self):
        store_path = self.data / "applications.json"
        original_file = store_path.read_bytes()
        adapter = FakePostgresAdapter([self.target, self.other])
        with patch.object(aa, "_application_store_adapter", return_value=adapter):
            result = api.delete_application(self.application_id)

        self.assertEqual(result["decision"], "deleted", result)
        self.assertEqual(
            [item["application_id"] for item in adapter.applications],
            [self.other_application_id],
        )
        self.assertEqual(store_path.read_bytes(), original_file)
        history = json.loads((self.data / "document_history.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [item["application_id"] for item in history["documents"]],
            [self.application_id, self.other_application_id],
        )
        self.assertEqual(
            [item["application_id"] for item in adapter.document_history],
            [self.other_application_id],
        )
        self.assertFalse((self.root / "output/resumes/app_deadbeefcafe_Final.docx").exists())
        self.assertTrue((self.root / "output/resumes/shared.pdf").is_file())
        self.assertEqual(adapter.before_delete_calls, 1)

    def test_postgres_stale_delete_preserves_application_artifacts_and_history(self):
        adapter = FakePostgresAdapter([self.target, self.other])
        artifact = self.root / "output" / "resumes" / "app_deadbeefcafe_Final.docx"
        history_before = (self.data / "document_history.json").read_bytes()

        def update_before_locked_check(current_adapter):
            current_adapter.applications[0]["current_status"] = "interview"

        adapter.before_check = update_before_locked_check
        original_write_bytes = Path.write_bytes
        with patch.object(Path, "write_bytes", autospec=True, side_effect=original_write_bytes) as write_bytes:
            with patch.object(aa, "_application_store_adapter", return_value=adapter):
                result = api.delete_application(self.application_id)

        self.assertEqual(result["decision"], "error")
        self.assertEqual(adapter.applications[0]["current_status"], "interview")
        self.assertEqual(adapter.before_delete_calls, 0)
        write_bytes.assert_not_called()
        self.assertTrue(artifact.is_file())
        self.assertEqual((self.data / "document_history.json").read_bytes(), history_before)

    def test_postgres_missing_record_does_not_change_artifacts_or_history(self):
        adapter = FakePostgresAdapter([self.target, self.other])
        artifact = self.root / "output" / "resumes" / "app_deadbeefcafe_Final.docx"
        history_before = (self.data / "document_history.json").read_bytes()
        adapter.before_check = lambda current_adapter: current_adapter.applications.clear()

        with patch.object(aa, "_application_store_adapter", return_value=adapter):
            result = api.delete_application(self.application_id)

        self.assertEqual(result["decision"], "error")
        self.assertEqual(adapter.before_delete_calls, 0)
        self.assertTrue(artifact.is_file())
        self.assertEqual((self.data / "document_history.json").read_bytes(), history_before)

    def test_postgres_database_failure_before_cleanup_preserves_files(self):
        adapter = FakePostgresAdapter([self.target, self.other])
        adapter.failure_before_check = RuntimeError("simulated database failure")
        artifact = self.root / "output" / "resumes" / "app_deadbeefcafe_Final.docx"
        history_before = (self.data / "document_history.json").read_bytes()

        with patch.object(aa, "_application_store_adapter", return_value=adapter):
            result = api.delete_application(self.application_id)

        self.assertEqual(result["decision"], "error")
        self.assertEqual(adapter.before_delete_calls, 0)
        self.assertTrue(artifact.is_file())
        self.assertEqual((self.data / "document_history.json").read_bytes(), history_before)

    def test_postgres_transaction_failure_after_staging_restores_artifacts_and_history(self):
        adapter = FakePostgresAdapter([self.target, self.other])
        adapter.failure_after_staging = RuntimeError("simulated transaction failure")
        history_before = (self.data / "document_history.json").read_bytes()
        artifact = self.root / "output" / "resumes" / "app_deadbeefcafe_Final.docx"

        with patch.object(aa, "_application_store_adapter", return_value=adapter):
            result = api.delete_application(self.application_id)

        self.assertEqual(result["decision"], "error")
        self.assertIn(self.application_id, [item["application_id"] for item in adapter.applications])
        self.assertTrue(artifact.is_file())
        self.assertEqual((self.data / "document_history.json").read_bytes(), history_before)
        self.assertFalse(api._application_deletion_manifest_dir().exists())
        self.assertFalse(any(
            path.exists()
            for root in api._application_artifact_roots()
            for path in root.rglob(".*.delete-*")
        ))

    def test_file_store_write_failure_restores_staged_artifacts_and_history(self):
        original_history = (self.data / "document_history.json").read_bytes()
        artifact_paths = [
            self.root / reference
            for reference in self.target_refs.values()
            if reference.startswith(("job_descriptions/", "output/"))
        ]
        artifact_paths.extend([
            self.root / self.history_record["docx"],
            self.root / self.history_record["pdf"],
        ])
        original_artifacts = {
            path: path.read_bytes()
            for path in artifact_paths
            if path.is_file()
        }
        write_json = api._atomic_write_json

        def fail_application_store_write(path, value, *, exclusive=False):
            if Path(path) == self.data / "applications.json":
                raise OSError("simulated application-store write failure")
            return write_json(path, value, exclusive=exclusive)

        with patch.dict(os.environ, {"CAREER_OS_STORAGE_BACKEND": "file"}), patch.object(
            api,
            "_atomic_write_json",
            side_effect=fail_application_store_write,
        ):
            result = api.delete_application(self.application_id)

        self.assertEqual(result["decision"], "error", result)
        self.assertIn("simulated application-store write failure", result["message"])
        self.assertIn(
            self.application_id,
            [item["application_id"] for item in aa.load_store()["applications"]],
        )
        self.assertEqual((self.data / "document_history.json").read_bytes(), original_history)
        self.assertEqual(
            {path: path.read_bytes() for path in original_artifacts},
            original_artifacts,
        )
        manifests = api._application_deletion_manifest_dir()
        self.assertFalse(manifests.exists() and list(manifests.glob("*.json")))

    def test_postgres_cleanup_failure_is_retried_from_durable_manifest(self):
        adapter = FakePostgresAdapter([self.target, self.other])
        artifact = self.root / "output" / "resumes" / "app_deadbeefcafe_Final.docx"
        original_history = (self.data / "document_history.json").read_bytes()
        original_unlink = Path.unlink

        def fail_staged_artifact_cleanup(path, *args, **kwargs):
            if ".delete-" in path.name:
                raise OSError("simulated artifact cleanup failure")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", autospec=True, side_effect=fail_staged_artifact_cleanup):
            with patch.object(aa, "_application_store_adapter", return_value=adapter):
                result = api.delete_application(self.application_id)

        self.assertEqual(result["decision"], "deleted", result)
        self.assertTrue(result["cleanup_pending"])
        self.assertNotIn(self.application_id, [item["application_id"] for item in adapter.applications])
        self.assertEqual(adapter.before_delete_calls, 1)
        self.assertFalse(artifact.exists())
        self.assertTrue(api._application_deletion_manifest_dir().exists())
        self.assertTrue(list(api._application_deletion_manifest_dir().glob("*.json")))

        with patch.object(aa, "_application_store_adapter", return_value=adapter):
            retry = api.delete_application(self.application_id)

        self.assertEqual(retry["decision"], "not_found")
        self.assertFalse(api._application_deletion_manifest_dir().exists())
        self.assertFalse(any(path.exists() for path in self.resumes.glob(".*.delete-*")))
        history = json.loads((self.data / "document_history.json").read_text(encoding="utf-8"))
        self.assertEqual((self.data / "document_history.json").read_bytes(), original_history)
        self.assertEqual(
            [item["application_id"] for item in history["documents"]],
            [self.application_id, self.other_application_id],
        )
        self.assertEqual(
            [item["application_id"] for item in adapter.document_history],
            [self.other_application_id],
        )

    def test_postgres_process_recovery_finalizes_deletion_after_database_commit(self):
        adapter = FakePostgresAdapter([self.target, self.other])
        adapter.crash_after_delete = KeyboardInterrupt()
        artifact = self.root / "output" / "resumes" / "app_deadbeefcafe_Final.docx"
        original_history = (self.data / "document_history.json").read_bytes()

        with patch.object(aa, "_application_store_adapter", return_value=adapter):
            with self.assertRaises(KeyboardInterrupt):
                api.delete_application(self.application_id)

        self.assertFalse(artifact.exists())
        manifests = list(api._application_deletion_manifest_dir().glob("*.json"))
        self.assertEqual(len(manifests), 1)
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        staged_artifact = Path(next(
            item["staged"] for item in manifest["artifacts"]
            if item["original"].endswith("app_deadbeefcafe_Final.docx")
        ))
        self.assertEqual(staged_artifact.parent, artifact.parent)
        self.assertTrue(staged_artifact.is_file())

        with patch.object(aa, "_application_store_adapter", return_value=adapter):
            result = api.delete_application(self.application_id)

        self.assertEqual(result["decision"], "not_found")
        self.assertFalse(staged_artifact.exists())
        self.assertFalse(api._application_deletion_manifest_dir().exists())
        history = json.loads((self.data / "document_history.json").read_text(encoding="utf-8"))
        self.assertEqual((self.data / "document_history.json").read_bytes(), original_history)
        self.assertEqual(
            [item["application_id"] for item in history["documents"]],
            [self.application_id, self.other_application_id],
        )
        self.assertEqual(
            [item["application_id"] for item in adapter.document_history],
            [self.other_application_id],
        )

    def test_health_reports_unavailable_postgres_storage(self):
        adapter = Mock()
        adapter.backend_name = "postgres"
        adapter.is_ready.return_value = False
        with patch.object(aa, "_application_store_adapter", return_value=adapter):
            status, result = self.call_health_route()
        self.assertEqual(status, 503)
        self.assertFalse(result["ok"])
        self.assertEqual(result["storage_backend"], "postgres")