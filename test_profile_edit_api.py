#!/usr/bin/env python3
"""Isolated tests for confirmed canonical Profile / Evidence edits."""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import career_os_api as api
import profile_update_agent as pua

ROOT = Path(__file__).resolve().parent


class ProfileEditApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="profile-edit-api-")
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.output = self.root / "output"
        for directory in (self.data, self.output / "resumes", self.output / "cover_letters"):
            directory.mkdir(parents=True, exist_ok=True)
        for source in (ROOT / "data").glob("*.json"):
            shutil.copy2(source, self.data / source.name)
        self.original_root = api.ROOT
        api.ROOT = self.root
        (self.output / "resumes" / "existing.docx").write_bytes(b"existing resume")
        (self.output / "cover_letters" / "existing.pdf").write_bytes(b"existing letter")
        self.artifact_bytes = {
            path: path.read_bytes()
            for path in (self.output / "resumes").iterdir()
        }
        self.artifact_bytes.update({
            path: path.read_bytes()
            for path in (self.output / "cover_letters").iterdir()
        })

    def tearDown(self):
        api.ROOT = self.original_root
        self.temporary.cleanup()

    def _updates(self):
        profile = pua.all_data(self.root)
        skill_group = next(group for group in profile["skills"]["skill_groups"] if group["category"] == "programming_languages")
        skill = skill_group["skills"][0]
        project = profile["projects"]["projects"][0]
        experience = profile["experience"]["experiences"][0]
        education = profile["education"]["education"][0]
        certification = profile["certifications"]["certifications"][0]
        return {
            "master_profile": {"name": "Updated Candidate", "headline": "Evidence-led analyst", "location": "Toronto"},
            "skills": [{"category": skill_group["category"], "name": skill["name"], "fields": {"name": skill["name"] + " (candidate edit)"}}],
            "projects": [{"record_id": project["record_id"], "fields": {"purpose": "Updated user-provided project purpose."}}],
            "experience": [{"record_id": experience["record_id"], "fields": {"title": "Updated Internship Title"}}],
            "education": [{"record_id": education["record_id"], "fields": {"grade": "Updated grade"}}],
            "certifications": [{"record_id": certification["record_id"], "fields": {"issuer": "Updated issuer"}}],
        }

    def _plan(self, updates=None):
        return api.plan_profile_edit({"updates": updates or self._updates()})

    def _additions(self):
        return {
            "skills": [{"category": "tools_and_platforms", "fields": {"name": "Profile Add Test Skill"}}],
            "projects": [{"fields": {
                "name": "Profile Add Test Project", "project_type": "github_project", "project_status": "in_progress",
                "purpose": "A user-described test project.", "functionality": ["User-provided project detail."],
                "technologies": ["Python"], "github_url": "https://github.com/example/profile-add-test",
            }}],
            "experience": [{"fields": {
                "organization": "Profile Add Test Organization", "title": "Test Intern",
                "experience_type": "employment_internship", "work_mode": "virtual",
                "start_date": "2026-01", "responsibilities": ["User-provided responsibility."],
            }}],
            "education": [{"fields": {
                "institution": "Profile Add Test University", "degree": "BSc",
                "field_of_study": "Computer Science", "start_date": "2026", "coursework": ["User-provided course."],
            }}],
            "certifications": [{"fields": {
                "name": "Profile Add Test Certificate", "issuer": "Example Issuer",
                "credential_type": "certificate", "issue_date": "2026-01",
            }}],
            "achievements": [{"fields": {
                "name": "Profile Add Test Achievement", "description": "User-provided achievement.",
                "date": "2026-02", "issuer": "Example Organization",
            }}],
        }

    def test_add_all_repeatable_record_types_and_preserve_existing_records(self):
        before = pua.all_data(self.root)
        applications_before = (self.data / "applications.json").read_bytes()
        existing = {
            "skills": copy.deepcopy(before["skills"]["skill_groups"]),
            "projects": copy.deepcopy(before["projects"]["projects"]),
            "experience": copy.deepcopy(before["experience"]["experiences"]),
            "education": copy.deepcopy(before["education"]["education"]),
            "certifications": copy.deepcopy(before["certifications"]["certifications"]),
            "achievements": copy.deepcopy(before["achievements"]["achievements"]),
        }
        plan = api.plan_profile_edit({
            "updates": {"master_profile": {"location": "Addition Test Location"}},
            "additions": self._additions(),
        })
        self.assertEqual(plan["decision"], "planned", plan)
        add_actions = [action for action in plan["actions"] if action["action"] == "add_profile_record"]
        self.assertEqual({action["category"] for action in add_actions}, {"skills", "projects", "experience", "education", "certifications", "achievements"})
        result = api.apply_profile_edit({"plan": plan, "confirmed": True})
        self.assertEqual(result["decision"], "profile_updated", result)

        after = pua.all_data(self.root)
        self.assertEqual(after["master_profile"]["profile"]["location"], "Addition Test Location")
        self.assertEqual(len(after["skills"]["skill_groups"]), len(existing["skills"]))
        for previous_group, current_group in zip(existing["skills"], after["skills"]["skill_groups"]):
            if previous_group["category"] == "tools_and_platforms":
                self.assertEqual(current_group["skills"][:-1], previous_group["skills"])
                self.assertEqual(current_group["skills"][-1]["name"], "Profile Add Test Skill")
            else:
                self.assertEqual(current_group, previous_group)
        self.assertEqual(after["projects"]["projects"][:-1], existing["projects"])
        self.assertEqual(after["experience"]["experiences"][:-1], existing["experience"])
        self.assertEqual(after["education"]["education"][:-1], existing["education"])
        self.assertEqual(after["certifications"]["certifications"][:-1], existing["certifications"])
        self.assertEqual(after["achievements"]["achievements"][-1]["record_id"], "achievement_profile_add_test_achievement")
        self.assertEqual(after["achievements"]["achievements"][-1]["status"], "candidate_provided")

        added_skill = next(
            skill for group in after["skills"]["skill_groups"]
            for skill in group["skills"] if skill["name"] == "Profile Add Test Skill"
        )
        self.assertEqual(added_skill["status"], "candidate_provided")
        self.assertEqual(added_skill["evidence"][0]["evidence_type"], "explicit_user_statement")
        added_project = after["projects"]["projects"][-1]
        self.assertEqual(added_project["record_id"], "project_profile_add_test_project")
        self.assertEqual(added_project["status"], "candidate_provided")
        self.assertEqual(added_project["github_url"], "https://github.com/example/profile-add-test")
        self.assertEqual(added_project["github_availability"], "github_pending")
        self.assertEqual(added_project["sources"][0]["evidence_type"], "explicit_user_statement")
        self.assertEqual(added_project["provenance"][0]["evidence_location"], "Career OS Profile / Evidence editor")
        added_experience = after["experience"]["experiences"][-1]
        self.assertEqual(added_experience["record_id"], "experience_profile_add_test_organization_test_intern")
        self.assertEqual(added_experience["status"], "candidate_provided")
        self.assertEqual(added_experience["sources"][0]["evidence_type"], "explicit_user_statement")
        self.assertEqual(after["education"]["education"][-1]["status"], "candidate_provided")
        self.assertEqual(after["education"]["education"][-1]["sources"][0]["evidence_type"], "explicit_user_statement")
        self.assertEqual(after["certifications"]["certifications"][-1]["record_id"], "credential_profile_add_test_certificate")
        self.assertEqual(after["certifications"]["certifications"][-1]["status"], "candidate_provided")
        self.assertEqual(after["certifications"]["certifications"][-1]["sources"][0]["evidence_type"], "explicit_user_statement")
        self.assertIn("project_profile_add_test_project", after["master_profile"]["record_indexes"]["project_ids"])
        self.assertIn("experience_profile_add_test_organization_test_intern", after["master_profile"]["record_indexes"]["experience_ids"])
        self.assertEqual((self.data / "applications.json").read_bytes(), applications_before)
        self.assertEqual({path: path.read_bytes() for path in self.artifact_bytes}, self.artifact_bytes)

    def test_add_requires_confirmation_and_rejects_stale_plan(self):
        plan = api.plan_profile_edit({"updates": {}, "additions": self._additions()})
        original = {path: path.read_bytes() for path in self.data.glob("*.json")}
        result = api.apply_profile_edit({"plan": plan})
        self.assertEqual(result["decision"], "confirmation_required")
        self.assertEqual({path: path.read_bytes() for path in self.data.glob("*.json")}, original)

        data = pua.all_data(self.root)
        data["master_profile"]["profile"]["location"] = "Changed during review"
        pua.dump("master_profile", data["master_profile"], self.root)
        stale_snapshot = {path: path.read_bytes() for path in self.data.glob("*.json")}
        result = api.apply_profile_edit({"plan": plan, "confirmed": True})
        self.assertEqual(result["decision"], "stale_profile")
        self.assertEqual({path: path.read_bytes() for path in self.data.glob("*.json")}, stale_snapshot)

    def test_invalid_addition_is_rejected_without_partial_writes(self):
        additions = self._additions()
        additions["projects"][0]["fields"]["github_url"] = "https://example.invalid/not-github"
        original = {path: path.read_bytes() for path in self.data.glob("*.json")}

        plan = api.plan_profile_edit({"updates": {}, "additions": additions})
        result = api.apply_profile_edit({"plan": plan, "confirmed": True})

        self.assertEqual(plan["decision"], "invalid")
        self.assertEqual(result["decision"], "invalid")
        self.assertEqual({path: path.read_bytes() for path in self.data.glob("*.json")}, original)

    def test_profile_edits_persist_and_return_updated_canonical_profile(self):
        before = pua.all_data(self.root)
        untouched_project = copy.deepcopy(before["projects"]["projects"][1])
        untouched_skill_group = copy.deepcopy(before["skills"]["skill_groups"][-1])
        old_skill = next(
            skill for group in before["skills"]["skill_groups"]
            for skill in group["skills"]
            if group["category"] == "programming_languages"
        )
        plan = self._plan()
        self.assertEqual(plan["decision"], "planned", plan)
        result = api.apply_profile_edit({"plan": plan, "confirmed": True})

        self.assertEqual(result["decision"], "profile_updated", result)
        self.assertEqual(result["profile"]["name"], "Updated Candidate")
        self.assertEqual(result["profile"]["headline"], "Evidence-led analyst")
        self.assertEqual(result["profile"]["location"], "Toronto")
        after = pua.all_data(self.root)
        self.assertEqual(after["master_profile"]["sources"][-1]["evidence_type"], "explicit_user_statement")
        self.assertEqual(after["master_profile"]["provenance"][-1]["evidence_location"], "Career OS Profile / Evidence editor")
        updated_skill = next(
            skill for group in after["skills"]["skill_groups"]
            for skill in group["skills"]
            if group["category"] == "programming_languages"
            and skill["name"] == "Python (candidate edit)"
        )
        self.assertEqual(updated_skill["status"], "candidate_provided")
        self.assertEqual(updated_skill["evidence"][:-1], old_skill["evidence"])
        self.assertEqual(updated_skill["evidence"][-1]["evidence_type"], "explicit_user_statement")
        updated_project = after["projects"]["projects"][0]
        self.assertEqual(updated_project["status"], "candidate_provided")
        self.assertEqual(updated_project["purpose"], "Updated user-provided project purpose.")
        self.assertEqual(updated_project["github_url"], before["projects"]["projects"][0]["github_url"])
        self.assertEqual(updated_project["sources"][:-1], before["projects"]["projects"][0]["sources"])
        self.assertEqual(updated_project["provenance"][:-1], before["projects"]["projects"][0]["provenance"])
        self.assertEqual(after["experience"]["experiences"][0]["title"], "Updated Internship Title")
        self.assertEqual(after["education"]["education"][0]["grade"], "Updated grade")
        self.assertEqual(after["certifications"]["certifications"][0]["issuer"], "Updated issuer")
        self.assertEqual(after["projects"]["projects"][1], untouched_project)
        self.assertEqual(after["skills"]["skill_groups"][-1], untouched_skill_group)
        self.assertEqual((self.data / "applications.json").read_bytes(), (ROOT / "data" / "applications.json").read_bytes())
        self.assertEqual({path: path.read_bytes() for path in self.artifact_bytes}, self.artifact_bytes)

    def test_persistence_requires_explicit_confirmation(self):
        plan = self._plan()
        original = {path: path.read_bytes() for path in self.data.glob("*.json")}

        result = api.apply_profile_edit({"plan": plan})

        self.assertEqual(result["decision"], "confirmation_required")
        self.assertEqual({path: path.read_bytes() for path in self.data.glob("*.json")}, original)

    def test_invalid_mixed_update_is_rejected_without_partial_writes(self):
        updates = {
            "master_profile": {"name": "Must Not Persist"},
            "projects": [{"record_id": "project_telecom_churn_logistic_regression", "fields": {"github_url": "https://example.invalid/unsupported"}}],
        }
        original = {path: path.read_bytes() for path in self.data.glob("*.json")}

        plan = self._plan(updates)
        result = api.apply_profile_edit({"plan": plan, "confirmed": True})

        self.assertEqual(plan["decision"], "invalid")
        self.assertEqual(result["decision"], "invalid")
        self.assertEqual({path: path.read_bytes() for path in self.data.glob("*.json")}, original)

    def test_stale_profile_plan_is_rejected(self):
        plan = self._plan()
        data = pua.all_data(self.root)
        data["master_profile"]["profile"]["location"] = "Changed after review"
        pua.dump("master_profile", data["master_profile"], self.root)
        original = {path: path.read_bytes() for path in self.data.glob("*.json")}

        result = api.apply_profile_edit({"plan": plan, "confirmed": True})

        self.assertEqual(result["decision"], "stale_profile")
        self.assertEqual({path: path.read_bytes() for path in self.data.glob("*.json")}, original)


if __name__ == "__main__":
    unittest.main(verbosity=2)