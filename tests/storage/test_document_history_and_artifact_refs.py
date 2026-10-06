import json
import shutil
import tempfile
import unittest
from pathlib import Path

import application_assistant as aa
import career_os_api as api
import jd_resume_planner as planner

ROOT = Path(__file__).resolve().parents[2]


class DocumentHistoryAndArtifactRefsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="doc-history-artifacts-")
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.jobs = self.root / "job_descriptions"
        self.reports = self.root / "output" / "reports"
        self.letters = self.root / "output" / "cover_letters"
        self.resumes = self.root / "output" / "resumes"
        for directory in (self.data, self.jobs, self.reports, self.letters, self.resumes):
            directory.mkdir(parents=True, exist_ok=True)
        for source in (ROOT / "data").glob("*.json"):
            if source.name == "document_history.json":
                continue
            shutil.copy2(source, self.data / source.name)
        history_path = self.data / "document_history.json"
        if history_path.exists():
            history_path.unlink()

        self.originals = {
            "aa": (aa.ROOT, aa.DATA, aa.JOBS, aa.OUT, aa.REPORTS, aa.LETTERS, aa.RESUMES),
            "api_root": api.ROOT,
            "planner_data": planner.DATA,
        }
        aa.ROOT, aa.DATA, aa.JOBS = self.root, self.data, self.jobs
        aa.OUT, aa.REPORTS, aa.LETTERS, aa.RESUMES = self.root / "output", self.reports, self.letters, self.resumes
        api.ROOT = self.root
        planner.DATA = self.data

    def tearDown(self):
        aa.ROOT, aa.DATA, aa.JOBS, aa.OUT, aa.REPORTS, aa.LETTERS, aa.RESUMES = self.originals["aa"]
        api.ROOT = self.originals["api_root"]
        planner.DATA = self.originals["planner_data"]
        self.tmp.cleanup()

    def test_document_history_round_trip_preserves_unicode_and_metadata(self):
        doc = self.resumes / "resume_history.docx"
        pdf = self.resumes / "resume_history.pdf"
        doc.write_bytes(b"history-docx")
        pdf.write_bytes(b"history-pdf")

        app_record = {
            "application_id": "app_history_123",
            "company_name": "Café — AI-ML",
            "job_title": "Python Engineer – ML",
            "selected_projects": ["AI-ML project"],
            "selected_skills": ["Python"],
            "selected_certifications": ["Azure AI"],
        }
        aa.save_history(app_record, "resume", doc, pdf)

        history = aa.load_document_history()
        self.assertEqual(len(history["documents"]), 1)
        entry = history["documents"][0]
        self.assertEqual(entry["application_id"], "app_history_123")
        self.assertEqual(entry["company"], "Café — AI-ML")
        self.assertEqual(entry["docx"], "output/resumes/resume_history.docx")
        self.assertEqual(entry["pdf"], "output/resumes/resume_history.pdf")
        self.assertEqual(entry["selected_projects"], ["AI-ML project"])

    def test_resume_cover_letter_and_plan_references_resolve_in_active_root(self):
        jd = (
            "Junior Business Data Analyst — Fresher\n"
            "Required Skills:\n- Python\n- SQL\n- Data Analysis\n- Reporting\n"
            "Responsibilities:\n- Prepare reports and analyze business data."
        )
        created = aa.create_application("Artifact Ref Test", "Junior Business Data Analyst", "https://example.test/artifacts", jd)
        app = aa.get_app(created["application"]["application_id"])[0]

        working_docx = self.resumes / "working_resume.docx"
        working_pdf = self.resumes / "working_resume.pdf"
        working_docx.write_bytes(b"working-docx")
        working_pdf.write_bytes(b"working-pdf")

        final_docx = self.resumes / "final_resume.docx"
        final_pdf = self.resumes / "final_resume.pdf"
        final_docx.write_bytes(b"final-docx")
        final_pdf.write_bytes(b"final-pdf")

        cover_path = self.letters / "cover_letter.md"
        cover_path.write_text("Dear Hiring Manager", encoding="utf-8")

        report_path = self.reports / "phase8_report.json"
        report_path.write_text(json.dumps({"approved": True}, ensure_ascii=False) + "\n", encoding="utf-8")

        store = aa.load_store()
        target = next(item for item in store["applications"] if item["application_id"] == app["application_id"])
        target.update({
            "working_resume_reference": str(working_docx.relative_to(self.root)),
            "working_resume_pdf_reference": str(working_pdf.relative_to(self.root)),
            "working_resume_docx_path": str(working_docx.relative_to(self.root)),
            "working_resume_pdf_path": str(working_pdf.relative_to(self.root)),
            "resume_reference": str(final_docx.relative_to(self.root)),
            "resume_pdf_reference": str(final_pdf.relative_to(self.root)),
            "resume_docx_path": str(final_docx.relative_to(self.root)),
            "resume_pdf_path": str(final_pdf.relative_to(self.root)),
            "cover_letter_reference": str(cover_path.relative_to(self.root)),
            "phase8_plan_reference": str(report_path.relative_to(self.root)),
        })
        aa.save_store(store)

        self.assertEqual(api.resolve_ref(target["working_resume_reference"], root=self.root), working_docx)
        self.assertEqual(api.resolve_ref(target["resume_reference"], root=self.root), final_docx)
        self.assertEqual(api.resolve_ref(target["cover_letter_reference"], root=self.root), cover_path)
        self.assertEqual(api.resolve_ref(target["phase8_plan_reference"], root=self.root), report_path)

    def test_missing_and_stale_artifact_paths_are_detected_without_changing_contracts(self):
        jd = (
            "Junior Business Data Analyst — Fresher\n"
            "Required Skills:\n- Python\n- SQL\n- Data Analysis\n- Reporting\n"
            "Responsibilities:\n- Prepare reports and analyze business data."
        )
        created = aa.create_application("Missing Artifact Test", "Junior Business Data Analyst", "https://example.test/missing-artifact", jd)
        app = aa.get_app(created["application"]["application_id"])[0]
        app["resume_generation_allowed"] = True
        app["resume_working_artifact_stale"] = True
        app["working_resume_docx_path"] = "output/resumes/does-not-exist.docx"
        app["working_resume_pdf_path"] = "output/resumes/does-not-exist.pdf"
        app["working_resume_docx_sha256"] = "abc"
        app["working_resume_pdf_sha256"] = "def"

        decision = api.validate_working_revision_for_finalization(app["application_id"], app)
        self.assertEqual(decision["decision"], "stale_working")

        app["resume_working_artifact_stale"] = False
        app["working_resume_docx_path"] = "output/resumes/missing.docx"
        app["working_resume_pdf_path"] = "output/resumes/missing.pdf"
        decision = api.validate_working_revision_for_finalization(app["application_id"], app)
        self.assertEqual(decision["decision"], "artifact_missing")


if __name__ == "__main__":
    unittest.main()
