#!/usr/bin/env python3
"""Certification eligibility, relevance, status, and generator consistency tests."""
from __future__ import annotations

import copy
import hashlib
import unittest
from pathlib import Path

import application_assistant as aa
import jd_resume_planner as planner
import resume_generator as rg

ROOT = Path(__file__).resolve().parent
INSIGHTEDGE_ID = "app_d003a3f71d8c"


class CertificationSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = next(item for item in aa.load_store()["applications"] if item["application_id"] == INSIGHTEDGE_ID)
        cls.profile = rg.profile()
        cls.jd = cls.app["job_description_text"]

    def test_insightedge_selects_only_relevant_source_backed_certifications(self):
        plan = planner.plan_resume(self.jd, copy.deepcopy(self.profile))
        selected = plan["resume_plan"]["certifications_to_include"]
        self.assertEqual([item["record_id"] for item in selected], [
            "credential_altair_rapidminer",
            "credential_eduskills_ai_ml_virtual_internship",
            "credential_ediglobe_ai_internship",
            "credential_ramp_coding",
        ])
        self.assertNotIn("credential_tcs_ion_career_edge", [item["record_id"] for item in selected])
        self.assertNotIn("credential_nptel_iot", [item["record_id"] for item in selected])
        self.assertTrue(all(item["matched_areas"] for item in selected))

    def test_candidate_provided_status_is_preserved_and_verified_shortage_is_explicit(self):
        plan = planner.plan_resume(self.jd, copy.deepcopy(self.profile))
        summary = plan["resume_plan"]["certification_selection_summary"]
        self.assertEqual(summary["verified_eligible_count"], 0)
        self.assertEqual(summary["candidate_provided_eligible_count"], 4)
        self.assertEqual(summary["verified_selected_count"], 0)
        self.assertEqual(summary["candidate_provided_selected_count"], 4)
        self.assertFalse(summary["verified_minimum_met"])
        self.assertIn("Only 0 relevant verified", summary["verified_minimum_unmet_reason"])
        self.assertTrue(all(item["status"] == "candidate_provided" and item["verification_status"] == "candidate_provided" for item in plan["resume_plan"]["certifications_to_include"]))

    def test_verified_status_ranks_above_candidate_provided_without_status_rewrite(self):
        profile = copy.deepcopy(self.profile)
        eduskills = next(item for item in profile["certifications"]["certifications"] if item["record_id"] == "credential_eduskills_ai_ml_virtual_internship")
        eduskills["status"] = "verified"
        selected, _, _ = planner.certification_selection(planner.analyze_jd(self.jd), self.jd, profile)
        entry = next(item for item in selected if item["record_id"] == eduskills["record_id"])
        self.assertEqual(entry["status"], "verified")
        self.assertEqual(entry["verification_status"], "verified")
        self.assertEqual(eduskills["status"], "verified")
        self.assertEqual(next(item for item in self.profile["certifications"]["certifications"] if item["record_id"] == eduskills["record_id"])["status"], "candidate_provided")

    def test_planner_and_generator_use_identical_approved_certifications(self):
        plan = planner.plan_resume(self.jd, copy.deepcopy(self.profile))
        generated = rg.effective_certs(plan, self.profile)
        self.assertEqual([item["record_id"] for item in generated], plan["resume_plan"]["certification_selection_summary"]["selected_record_ids"])
        self.assertEqual([item["status"] for item in generated], [item["status"] for item in plan["resume_plan"]["certifications_to_include"]])

    def test_order_is_deterministic_for_identical_jd_and_profile(self):
        first = planner.plan_resume(self.jd, copy.deepcopy(self.profile))
        second = planner.plan_resume(self.jd, copy.deepcopy(self.profile))
        first_ids = [item["record_id"] for item in first["resume_plan"]["certifications_to_include"]]
        second_ids = [item["record_id"] for item in second["resume_plan"]["certifications_to_include"]]
        self.assertEqual(first_ids, second_ids)

    def test_fewer_than_four_relevant_records_are_not_padded(self):
        profile = copy.deepcopy(self.profile)
        profile["certifications"]["certifications"] = [
            item for item in profile["certifications"]["certifications"]
            if item["record_id"] in {"credential_altair_rapidminer", "credential_ramp_coding"}
        ]
        selected, summary, _ = planner.certification_selection(planner.analyze_jd(self.jd), self.jd, profile)
        self.assertEqual(len(selected), 2)
        self.assertEqual(summary["eligible_relevant_count"], 2)
        self.assertEqual(summary["selected_count"], 2)
        self.assertIn("Only 0 relevant verified", summary["verified_minimum_unmet_reason"])

    def test_selection_does_not_modify_canonical_certification_data(self):
        path = ROOT / "data" / "certifications.json"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        planner.plan_resume(self.jd, copy.deepcopy(self.profile))
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)