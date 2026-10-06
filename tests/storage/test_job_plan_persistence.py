import json
import shutil
import tempfile
import unittest
from pathlib import Path

import application_assistant as aa
import career_os_api as api
import jd_resume_planner as planner

ROOT = Path(__file__).resolve().parents[2]


class JobPlanPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="job-plan-persistence-")
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.jobs = self.root / "job_descriptions"
        self.reports = self.root / "output" / "reports"
        self.letters = self.root / "output" / "cover_letters"
        self.resumes = self.root / "output" / "resumes"
        for directory in (self.data, self.jobs, self.reports, self.letters, self.resumes):
            directory.mkdir(parents=True, exist_ok=True)
        for source in (ROOT / "data").glob("*.json"):
            shutil.copy2(source, self.data / source.name)

        self.originals = {
            "aa": (aa.ROOT, aa.DATA, aa.JOBS, aa.OUT, aa.REPORTS, aa.LETTERS, aa.RESUMES),
            "api_root": api.ROOT,
            "planner_data": planner.DATA,
        }
        aa.ROOT, aa.DATA, aa.JOBS = self.root, self.data, self.jobs
        aa.OUT, aa.REPORTS, aa.LETTERS, aa.RESUMES = self.root / "output", self.reports, self.letters, self.resumes
        api.ROOT = self.root.parent
        planner.DATA = self.data

    def tearDown(self):
        aa.ROOT, aa.DATA, aa.JOBS, aa.OUT, aa.REPORTS, aa.LETTERS, aa.RESUMES = self.originals["aa"]
        api.ROOT = self.originals["api_root"]
        planner.DATA = self.originals["planner_data"]
        self.tmp.cleanup()

    def test_resolve_ref_uses_the_active_runtime_root_for_saved_plan_files(self):
        jd = (
            "Junior Business Data Analyst — Fresher\n"
            "Required Skills:\n- Python\n- SQL\n- Data Analysis\n- Reporting\n"
            "Responsibilities:\n- Prepare reports and analyze business data."
        )
        created = aa.create_application("Runtime Root Test", "Junior Business Data Analyst", "https://example.test/runtime-root", jd)
        self.assertEqual(created["decision"], "created", created)
        app = aa.get_app(created["application"]["application_id"])[0]
        plan_path = self.root / app["phase8_plan_reference"]
        self.assertTrue(plan_path.exists(), plan_path)
        self.assertEqual(api.resolve_ref(app["phase8_plan_reference"], root=self.root), plan_path)

    def test_project_edit_plan_reads_the_persisted_reviewed_plan_from_the_active_root(self):
        jd = (
            "Junior Business Data Analyst — Fresher\n"
            "Required Skills:\n- Python\n- SQL\n- Data Analysis\n- Reporting\n"
            "Responsibilities:\n- Prepare reports and analyze business data."
        )
        created = aa.create_application("Persisted Plan Test", "Junior Business Data Analyst", "https://example.test/persisted-plan", jd)
        app = aa.get_app(created["application"]["application_id"])[0]
        plan_path = self.root / app["phase8_plan_reference"]
        persisted = {
            "mode": "job_application_planning",
            "source_jd_text": jd,
            "resume_plan": {
                "projects_to_include": [],
                "project_selection_source": "manual",
                "project_selection_record_ids": [],
                "skills_to_include": [{"name": "Python", "category": "programming_languages"}],
            },
            "approval_checkpoint": {"resume_generation_allowed": False},
        }
        plan_path.write_text(json.dumps(persisted, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        loaded = api.project_edit_plan(app, root=self.root)
        self.assertEqual(loaded["resume_plan"]["project_selection_source"], "manual")
        self.assertEqual(loaded["resume_plan"]["projects_to_include"], [])
        self.assertEqual(loaded["resume_plan"]["skills_to_include"][0]["name"], "Python")


if __name__ == "__main__":
    unittest.main()
