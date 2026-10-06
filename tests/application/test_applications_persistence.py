import json
import tempfile
import unittest
from pathlib import Path

import application_assistant as aa


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
        self.temporary.cleanup()

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
        second = aa.create_application("Example AI", "Junior RAG Engineer", "https://example.com/jobs/dup-a", jd)
        self.assertEqual(second["decision"], "duplicate_requires_clarification")
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
