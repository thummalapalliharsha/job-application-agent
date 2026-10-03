#!/usr/bin/env python3
"""Application deletion tests using isolated temporary storage only."""
from __future__ import annotations

import copy
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import application_assistant as aa
import career_os_api as api


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
            "application_id": self.application_id,
            "kind": "resume",
            "docx": "output/resumes/app_deadbeefcafe_history.docx",
            "pdf": "output/resumes/app_deadbeefcafe_history.pdf",
        }
        self.other_history_record = {
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

    def test_delete_removes_only_target_data_and_stale_save_cannot_restore_it(self):
        stale_store = copy.deepcopy(aa.load_store())
        result = api.delete_application(self.application_id)
        self.assertEqual(result["decision"], "deleted", result)
        self.assertEqual(result["message"], "Application removed from history.")

        aa.save_store(stale_store)
        saved = aa.load_store()["applications"]
        self.assertEqual([item["application_id"] for item in saved], [self.other_application_id])
        history = json.loads((self.data / "document_history.json").read_text(encoding="utf-8"))
        self.assertEqual([item["application_id"] for item in history["documents"]], [self.other_application_id])

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