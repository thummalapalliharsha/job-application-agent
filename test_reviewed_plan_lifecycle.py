#!/usr/bin/env python3
"""Sandboxed integration tests for reviewed-plan approval and Working/Final lifecycle."""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import application_assistant as aa
import career_os_api as api
import jd_resume_planner as planner
import resume_generator as rg

ROOT = Path(__file__).resolve().parent


class ReviewedPlanLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="reviewed-plan-lifecycle-")
        self.root = Path(self.temporary.name)
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
        api.ROOT = self.root
        planner.DATA = self.data
        self.jd = (
            "Junior Business Data Analyst — Fresher\n"
            "Required Skills:\n- Python\n- SQL\n- Data Analysis\n- Reporting\n"
            "Responsibilities:\n- Prepare reports and analyze business data."
        )
        created = aa.create_application("Lifecycle Test", "Junior Business Data Analyst", "https://example.test/lifecycle", self.jd)
        self.assertEqual(created["decision"], "created")
        self.aid = created["application"]["application_id"]
        store = aa.load_store()
        self.app = next(item for item in store["applications"] if item["application_id"] == self.aid)
        self.old_plan_ref = self.app["phase8_plan_reference"]
        old_plan_path = self.root / self.old_plan_ref
        self.old_plan_bytes = old_plan_path.read_bytes()

        historical_stem = f"{aa.slug(self.app.get('company_name') or 'company')}_{aa.slug(self.app.get('job_title') or 'role')}_{self.aid}_Final"
        self.old_final_docx = self.resumes / f"{historical_stem}.docx"
        self.old_final_pdf = self.resumes / f"{historical_stem}.pdf"
        self.old_final_docx.write_bytes(b"historical-final-docx")
        self.old_final_pdf.write_bytes(b"historical-final-pdf")
        self.app.update({
            "working_resume_generation_id": "gen_" + "1" * 32,
            "working_resume_docx_path": "output/resumes/historical_Working.docx",
            "resume_generation_id": "gen_" + "2" * 32,
            "resume_reference": str(self.old_final_docx.relative_to(self.root)),
            "resume_pdf_reference": str(self.old_final_pdf.relative_to(self.root)),
            "resume_docx_path": str(self.old_final_docx.relative_to(self.root)),
            "resume_pdf_path": str(self.old_final_pdf.relative_to(self.root)),
            "resume_finalized_at": "2026-01-01T00:00:00+00:00",
        })
        aa.save_store(store)
        self.profile = planner.load_profile()

    def tearDown(self):
        aa.ROOT, aa.DATA, aa.JOBS, aa.OUT, aa.REPORTS, aa.LETTERS, aa.RESUMES = self.originals["aa"]
        api.ROOT = self.originals["api_root"]
        planner.DATA = self.originals["planner_data"]
        self.temporary.cleanup()

    def reviewed_plan(self):
        plan = planner.plan_resume(self.jd.strip(), self.profile)
        plan["candidate_skill_categories"] = [
            group.get("category") for group in self.profile["skills"].get("skill_groups", []) if group.get("category")
        ]
        return plan

    def test_approval_persists_exact_reviewed_plan_and_synchronizes_application(self):
        plan = self.reviewed_plan()
        old_reference = self.app["phase8_plan_reference"]
        mismatched = copy.deepcopy(plan)
        mismatched["source_jd_text"] = "Unrelated role"
        self.assertEqual(aa.approve_resume(self.aid, mismatched)["decision"], "plan_jd_mismatch")
        tampered = copy.deepcopy(plan)
        tampered["resume_plan"]["projects_to_include"] = []
        self.assertEqual(aa.approve_resume(self.aid, tampered)["decision"], "plan_evidence_mismatch")
        self.assertEqual(aa.get_app(self.aid)[0]["phase8_plan_reference"], old_reference)

        approved = aa.approve_resume(self.aid, plan)
        self.assertEqual(approved["decision"], "approved", approved)
        app = aa.get_app(self.aid)[0]
        self.assertNotEqual(app["phase8_plan_reference"], old_reference)
        saved = json.loads((self.root / app["phase8_plan_reference"]).read_text(encoding="utf-8"))
        expected_projects = [item["record_id"] for item in plan["resume_plan"]["projects_to_include"]]
        expected_certifications = [item["name"] for item in plan["resume_plan"]["certifications_to_include"]]
        expected_experience = [item["record_id"] for item in plan["resume_plan"]["experience_to_include"]]
        self.assertEqual(saved["resume_plan"]["projects_to_include"], plan["resume_plan"]["projects_to_include"])
        self.assertTrue(saved["approval_checkpoint"]["resume_generation_allowed"])
        self.assertEqual(app["project_selection_record_ids"], expected_projects)
        self.assertEqual(app["selected_projects"], [item["name"] for item in plan["resume_plan"]["projects_to_include"]])
        self.assertEqual(app["selected_certifications"], expected_certifications)
        self.assertEqual(app["selected_experience"], expected_experience)
        self.assertEqual(app["phase8_plan_reference"], approved["phase8_plan_reference"])
        self.assertEqual((self.root / old_reference).read_bytes(), self.old_plan_bytes)

    def test_insightedge_selection_is_three_expected_projects_no_experience_four_certs(self):
        insightedge = next(item for item in aa.load_store()["applications"]
                           if item["application_id"] == "app_d003a3f71d8c")
        plan = planner.plan_resume(insightedge["job_description_text"], self.profile)
        self.assertEqual([item["record_id"] for item in plan["resume_plan"]["projects_to_include"]], [
            "project_bank_customer_clustering_dashboard",
            "project_sample_sales_data",
            "project_imdb_movie_analysis",
        ])
        self.assertEqual(plan["resume_plan"]["experience_to_include"], [])
        self.assertEqual([item["record_id"] for item in plan["resume_plan"]["certifications_to_include"]], [
            "credential_altair_rapidminer",
            "credential_eduskills_ai_ml_virtual_internship",
            "credential_ediglobe_ai_internship",
            "credential_ramp_coding",
        ])

    def test_regeneration_uses_reviewed_plan_and_finalization_preserves_history(self):
        plan = self.reviewed_plan()
        approval = aa.approve_resume(self.aid, plan)
        self.assertEqual(approval["decision"], "approved", approval)
        expected_plan_ref = approval["phase8_plan_reference"]
        captured = {}

        def fake_generate(passed_plan, _profile, output):
            captured["plan"] = copy.deepcopy(passed_plan)
            Path(output).write_bytes(b"working-content-from-approved-plan")

        def fake_convert(docx):
            pdf = Path(docx).with_suffix(".pdf")
            pdf.write_bytes(b"pdf-for-" + Path(docx).read_bytes())
            return pdf

        with patch.object(rg, "profile", return_value=self.profile), \
             patch.object(rg, "generate", side_effect=fake_generate), \
             patch.object(rg, "validate", return_value={"page_count": 1, "final_status": "PASS"}), \
             patch.object(api, "convert_pdf", side_effect=fake_convert):
            result = api.generate_working_resume(self.aid)
            self.assertEqual(result["decision"], "created", result)
            generated_ids = [item["record_id"] for item in captured["plan"]["resume_plan"]["projects_to_include"]]
            expected_ids = [item["record_id"] for item in plan["resume_plan"]["projects_to_include"]]
            self.assertEqual(generated_ids, expected_ids)
            self.assertEqual(captured["plan"]["resume_plan"]["experience_to_include"], plan["resume_plan"]["experience_to_include"])
            self.assertEqual(captured["plan"]["resume_plan"]["certifications_to_include"], plan["resume_plan"]["certifications_to_include"])

            app = aa.get_app(self.aid)[0]
            self.assertEqual(app["phase8_plan_reference"], expected_plan_ref)
            self.assertTrue(app["resume_final_stale"])
            self.assertFalse(app["resume_working_artifact_stale"])
            working_docx = self.root / app["working_resume_docx_path"]
            self.assertEqual(working_docx.read_bytes(), b"working-content-from-approved-plan")
            self.assertEqual(self.old_final_docx.read_bytes(), b"historical-final-docx")
            self.assertEqual(self.old_final_pdf.read_bytes(), b"historical-final-pdf")

            with patch.object(api, "validate_working_revision_for_finalization", return_value={
                "decision": "ready", "source": working_docx, "pdf": self.root / app["working_resume_pdf_path"],
                "plan": captured["plan"], "profile": self.profile,
            }), patch.object(rg, "validate", return_value={"page_count": 1, "final_status": "PASS"}), \
                 patch.object(api, "convert_pdf", side_effect=fake_convert):
                finalized = api.finalize_resume(self.aid)

        self.assertEqual(finalized["decision"], "finalized", finalized)
        updated = aa.get_app(self.aid)[0]
        current_final = self.root / updated["resume_docx_path"]
        self.assertEqual(current_final.read_bytes(), working_docx.read_bytes())
        self.assertTrue(updated["resume_docx_path"].endswith("_v2.docx"))
        self.assertFalse(updated["resume_final_stale"])
        self.assertTrue(self.old_final_docx.is_file() and self.old_final_pdf.is_file())
        self.assertEqual(self.old_final_docx.read_bytes(), b"historical-final-docx")
        self.assertEqual(self.old_final_pdf.read_bytes(), b"historical-final-pdf")


if __name__ == "__main__":
    unittest.main(verbosity=2)