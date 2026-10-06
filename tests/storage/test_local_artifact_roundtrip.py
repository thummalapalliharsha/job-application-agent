import json
import shutil
import tempfile
import unittest
from pathlib import Path

import application_assistant as aa
import career_os_api as api

ROOT = Path(__file__).resolve().parents[2]


class LocalArtifactRoundtripTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="local-artifact-roundtrip-")
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.jobs = self.root / "job_descriptions"
        self.output = self.root / "output"
        self.reports = self.output / "reports"
        self.letters = self.output / "cover_letters"
        self.resumes = self.output / "resumes"
        for directory in (self.data, self.jobs, self.reports, self.letters, self.resumes):
            directory.mkdir(parents=True, exist_ok=True)

        for source in (ROOT / "data").glob("*.json"):
            if source.name in {"applications.json", "document_history.json"}:
                continue
            shutil.copy2(source, self.data / source.name)
        self.data.joinpath("applications.json").write_text(json.dumps({"applications": []}, ensure_ascii=False) + "\n", encoding="utf-8")
        history_path = self.data / "document_history.json"
        if history_path.exists():
            history_path.unlink()

        self.originals = {
            "aa": (aa.ROOT, aa.DATA, aa.JOBS, aa.OUT, aa.REPORTS, aa.LETTERS, aa.RESUMES),
            "api_root": api.ROOT,
        }
        aa.ROOT, aa.DATA, aa.JOBS = self.root, self.data, self.jobs
        aa.OUT, aa.REPORTS, aa.LETTERS, aa.RESUMES = self.output, self.reports, self.letters, self.resumes
        api.ROOT = self.root

    def tearDown(self):
        aa.ROOT, aa.DATA, aa.JOBS, aa.OUT, aa.REPORTS, aa.LETTERS, aa.RESUMES = self.originals["aa"]
        api.ROOT = self.originals["api_root"]
        self.tmp.cleanup()

    def test_resume_and_cover_letter_roundtrip_uses_active_storage_root(self):
        jd = (
            "We are looking for a Junior Business Data Analyst to support business teams with data-driven reporting and analysis.\n\n"
            "Responsibilities:\n"
            "- Clean and validate business datasets.\n"
            "- Analyze sales and customer data to identify trends.\n"
            "- Write SQL queries for data extraction and analysis.\n"
            "- Build dashboards and reports for stakeholders.\n"
            "- Use Python, Pandas and NumPy for data analysis.\n"
            "- Communicate findings clearly.\n\n"
            "Required Skills:\n"
            "- Python\n"
            "- SQL\n"
            "- Pandas\n"
            "- NumPy\n"
            "- Data Cleaning\n"
            "- Exploratory Data Analysis\n"
            "- Data Visualization\n"
            "- Analytical Thinking\n\n"
            "Preferred Skills:\n"
            "- Power BI\n"
            "- Excel\n"
            "- Git/GitHub\n\n"
            "Education:\n"
            "- Bachelor's degree in Computer Science or a related field.\n"
            "- Freshers are welcome."
        )
        created = aa.create_application("Local Artifact Co", "Junior Business Data Analyst", "https://example.com/jobs/local-artifact", jd)
        self.assertEqual(created["decision"], "created", created)
        aid = created["application"]["application_id"]

        app = aa.get_app(aid)[0]
        app["resume_generation_allowed"] = True
        aa.save_store({"applications": [app]})

        working = api.generate_working_resume(aid)
        self.assertEqual(working["decision"], "created", working)
        working_docx = self.root / working["working"]["docx_reference"]
        working_pdf = self.root / working["working"]["pdf_reference"]
        self.assertTrue(working_docx.is_file())
        self.assertTrue(working_pdf.is_file())
        self.assertEqual(api.resolve_ref(working["working"]["docx_reference"], root=self.root), working_docx)
        self.assertEqual(api.resolve_ref(working["working"]["pdf_reference"], root=self.root), working_pdf)

        final = api.finalize_resume(aid)
        self.assertEqual(final["decision"], "finalized", final)
        finalized_app = aa.get_app(aid)[0]
        final_docx = self.root / finalized_app["resume_docx_path"]
        final_pdf = self.root / finalized_app["resume_pdf_path"]
        self.assertTrue(final_docx.is_file())
        self.assertTrue(final_pdf.is_file())
        self.assertEqual(api.resolve_ref(finalized_app["resume_docx_path"], root=self.root), final_docx)
        self.assertEqual(api.resolve_ref(finalized_app["resume_pdf_path"], root=self.root), final_pdf)

        letter = api.generate_working_cover_letter(aid)
        self.assertEqual(letter["decision"], "created", letter)
        cover_markdown = self.root / letter["cover_letter_working_reference"]
        cover_docx = self.root / letter["cover_letter_working_docx_reference"]
        cover_pdf = self.root / letter["cover_letter_working_pdf_reference"]
        self.assertTrue(cover_markdown.is_file())
        self.assertTrue(cover_docx.is_file())
        self.assertTrue(cover_pdf.is_file())
        self.assertEqual(api.resolve_ref(letter["cover_letter_working_reference"], root=self.root), cover_markdown)
        self.assertEqual(api.resolve_ref(letter["cover_letter_working_docx_reference"], root=self.root), cover_docx)
        self.assertEqual(api.resolve_ref(letter["cover_letter_working_pdf_reference"], root=self.root), cover_pdf)

    def test_resume_resolution_and_stale_artifact_rejection_remain_active_root_safe(self):
        jd = (
            "We are looking for a Junior Business Data Analyst to support business teams with data-driven reporting and analysis.\n\n"
            "Responsibilities:\n"
            "- Clean and validate business datasets.\n"
            "- Analyze sales and customer data to identify trends.\n"
            "- Write SQL queries for data extraction and analysis.\n"
            "- Build dashboards and reports for stakeholders.\n"
            "- Use Python, Pandas and NumPy for data analysis.\n"
            "- Communicate findings clearly.\n\n"
            "Required Skills:\n"
            "- Python\n"
            "- SQL\n"
            "- Pandas\n"
            "- NumPy\n"
            "- Data Cleaning\n"
            "- Exploratory Data Analysis\n"
            "- Data Visualization\n"
            "- Analytical Thinking\n\n"
            "Preferred Skills:\n"
            "- Power BI\n"
            "- Excel\n"
            "- Git/GitHub\n\n"
            "Education:\n"
            "- Bachelor's degree in Computer Science or a related field.\n"
            "- Freshers are welcome."
        )
        created = aa.create_application("Stale Artifact Co", "Junior Data Analyst", "https://example.com/jobs/stale-artifact", jd)
        aid = created["application"]["application_id"]
        app = aa.get_app(aid)[0]
        app["resume_generation_allowed"] = True
        aa.save_store({"applications": [app]})

        working = api.generate_working_resume(aid)
        self.assertEqual(working["decision"], "created", working)

        app = aa.get_app(aid)[0]
        app["resume_working_artifact_stale"] = True
        app["working_resume_docx_path"] = "output/resumes/does-not-exist.docx"
        app["working_resume_pdf_path"] = "output/resumes/does-not-exist.pdf"
        decision = api.validate_working_revision_for_finalization(aid, app)
        self.assertEqual(decision["decision"], "stale_working")

        app["resume_working_artifact_stale"] = False
        decision = api.validate_working_revision_for_finalization(aid, app)
        self.assertEqual(decision["decision"], "artifact_missing")


if __name__ == "__main__":
    unittest.main()
