#!/usr/bin/env python3
"""Isolated API tests for explicit JD skill-gap confirmation."""
from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
import unittest
from pathlib import Path

import application_assistant as aa
import career_os_api as api
import jd_resume_planner as planner
import profile_security as psecurity

ROOT = Path(__file__).resolve().parent


class SkillGapConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="skill-gap-confirmation-")
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
            "profile_pin_hash": os.environ.get("CAREER_OS_PROFILE_PIN_HASH"),
        }
        aa.ROOT, aa.DATA, aa.JOBS = self.root, self.data, self.jobs
        aa.OUT, aa.REPORTS, aa.LETTERS, aa.RESUMES = self.root / "output", self.reports, self.letters, self.resumes
        api.ROOT = self.root
        planner.DATA = self.data
        self.pin = f"{secrets.randbelow(1_000_000):06d}"
        self.wrong_pin = f"{(int(self.pin) + 1) % 1_000_000:06d}"
        os.environ["CAREER_OS_PROFILE_PIN_HASH"] = psecurity.hash_profile_pin(self.pin)
        created = aa.create_application(
            "Gap Test Company", "Junior RAG Engineer", "https://example.test/gap",
            "Junior RAG Engineer\nRequired Skills:\n- Python\n- RAG\n- LangChain",
        )
        self.assertEqual(created["decision"], "created")
        self.aid = created["application"]["application_id"]
        store = aa.load_store()
        app = next(item for item in store["applications"] if item["application_id"] == self.aid)
        app["working_resume_generation_id"] = "gen_" + "1" * 32
        app["working_resume_docx_path"] = "output/resumes/previous.docx"
        aa.save_store(store)

    def tearDown(self):
        aa.ROOT, aa.DATA, aa.JOBS, aa.OUT, aa.REPORTS, aa.LETTERS, aa.RESUMES = self.originals["aa"]
        api.ROOT = self.originals["api_root"]
        planner.DATA = self.originals["planner_data"]
        if self.originals["profile_pin_hash"] is None:
            os.environ.pop("CAREER_OS_PROFILE_PIN_HASH", None)
        else:
            os.environ["CAREER_OS_PROFILE_PIN_HASH"] = self.originals["profile_pin_hash"]
        self.temporary.cleanup()

    def test_requires_confirmation_and_only_accepts_unsupported_required_skill(self):
        store_path = self.data / "applications.json"
        before = store_path.read_bytes()
        self.assertEqual(api.confirm_skill_gap(self.aid, {"skill": "LangChain", "category": "generative_ai"})["decision"], "confirmation_required")
        self.assertEqual(api.confirm_skill_gap(self.aid, {"skill": "Python", "category": "programming_languages", "confirmed": True, "pin": self.pin})["decision"], "invalid")
        self.assertEqual(store_path.read_bytes(), before)

    def test_confirmation_updates_profile_plan_and_approval_state_without_project_claim(self):
        projects_before = json.loads((self.data / "projects.json").read_text(encoding="utf-8"))["projects"]
        result = api.confirm_skill_gap(self.aid, {"skill": "LangChain", "category": "generative_ai", "confirmed": True, "pin": self.pin})
        self.assertEqual(result["decision"], "skill_added_candidate_provided", result)
        self.assertEqual(result["status"], "candidate_provided")
        self.assertIn("until verified", result["message"])

        profile = json.loads((self.data / "skills.json").read_text(encoding="utf-8"))
        skill = next(skill for group in profile["skill_groups"] for skill in group["skills"] if skill["name"] == "LangChain")
        self.assertEqual(skill["status"], "candidate_provided")
        self.assertEqual(skill["evidence"][0]["evidence_type"], "explicit_user_confirmation")
        projects_after = json.loads((self.data / "projects.json").read_text(encoding="utf-8"))["projects"]
        self.assertEqual(projects_after, projects_before)

        app = next(item for item in aa.load_store()["applications"] if item["application_id"] == self.aid)
        plan = json.loads((self.root / app["phase8_plan_reference"]).read_text(encoding="utf-8"))
        self.assertFalse(app["resume_generation_allowed"])
        self.assertTrue(app["resume_working_artifact_stale"])
        self.assertEqual(app["current_status"], "awaiting_resume_approval")
        self.assertFalse(plan["approval_checkpoint"]["resume_generation_allowed"])
        self.assertNotIn("LangChain", [item["name"] for item in plan["resume_plan"]["skills_to_include"]])
        self.assertGreaterEqual(len(aa.load_store()["applications"]), 1)

    def test_skill_gap_write_requires_pin_and_preserves_all_data_on_failure(self):
        app = next(item for item in aa.load_store()["applications"] if item["application_id"] == self.aid)
        plan_path = self.root / app["phase8_plan_reference"]
        paths = [self.data / "skills.json", self.data / "master_profile.json", self.data / "applications.json", plan_path]
        original = {path: path.read_bytes() for path in paths}
        for pin in (None, "wrong!", self.wrong_pin):
            payload = {"skill": "LangChain", "category": "generative_ai", "confirmed": True}
            if pin is not None:
                payload["pin"] = pin
            result = api.confirm_skill_gap(self.aid, payload)
            self.assertEqual(result["decision"], "pin_verification_required", result)
            self.assertNotIn(self.pin, json.dumps(result))
            self.assertEqual({path: path.read_bytes() for path in paths}, original)


if __name__ == "__main__":
    unittest.main(verbosity=2)