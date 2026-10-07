#!/usr/bin/env python3
"""Isolated tests for confirmed canonical Profile / Evidence edits."""
from __future__ import annotations

import copy
import http.client
import json
import os
import secrets
import shutil
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import application_assistant as aa
import career_os_api as api
import jd_resume_planner as planner
import profile_update_agent as pua
import profile_security as psecurity

ROOT = Path(__file__).resolve().parents[2]


class ProfileEditApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="profile-edit-api-")
        self.root = Path(self.temporary.name)
        self.data = self.root / "data"
        self.output = self.root / "output"
        self.jobs = self.root / "job_descriptions"
        self.reports = self.output / "reports"
        self.letters = self.output / "cover_letters"
        self.resumes = self.output / "resumes"
        for directory in (self.data, self.jobs, self.reports, self.resumes, self.letters):
            directory.mkdir(parents=True, exist_ok=True)
        for source in (ROOT / "data").glob("*.json"):
            shutil.copy2(source, self.data / source.name)
        (self.data / "applications.json").write_text('{"applications":[]}\n', encoding="utf-8")
        self.original_root = api.ROOT
        self.original_aa = (aa.ROOT, aa.DATA, aa.JOBS, aa.OUT, aa.REPORTS, aa.LETTERS, aa.RESUMES)
        self.original_planner_data = planner.DATA
        api.ROOT = self.root
        aa.ROOT, aa.DATA, aa.JOBS = self.root, self.data, self.jobs
        aa.OUT, aa.REPORTS, aa.LETTERS, aa.RESUMES = self.output, self.reports, self.letters, self.resumes
        planner.DATA = self.data
        self.original_pin_hash = os.environ.get("CAREER_OS_PROFILE_PIN_HASH")
        self.pin = f"{secrets.randbelow(1_000_000):06d}"
        self.wrong_pin = f"{(int(self.pin) + 1) % 1_000_000:06d}"
        self.replacement_pin = f"{(int(self.pin) + 2) % 1_000_000:06d}"
        os.environ["CAREER_OS_PROFILE_PIN_HASH"] = psecurity.hash_profile_pin(self.pin)
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
        aa.ROOT, aa.DATA, aa.JOBS, aa.OUT, aa.REPORTS, aa.LETTERS, aa.RESUMES = self.original_aa
        planner.DATA = self.original_planner_data
        if self.original_pin_hash is None:
            os.environ.pop("CAREER_OS_PROFILE_PIN_HASH", None)
        else:
            os.environ["CAREER_OS_PROFILE_PIN_HASH"] = self.original_pin_hash
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

    def _seed_approved_application(self, application_id, *, project_ids=(), skill_records=(), experience_ids=(), certification_ids=()):
        profile = pua.all_data(self.root)
        projects = {item["record_id"]: item for item in profile["projects"]["projects"]}
        certifications = {item["record_id"]: item for item in profile["certifications"]["certifications"]}
        reference = f"output/reports/{application_id}_approved_plan.json"
        plan = {
            "mode": "job_application_planning",
            "approval_checkpoint": {"resume_generation_allowed": True},
            "resume_plan": {
                "projects_to_include": [copy.deepcopy(projects[record_id]) for record_id in project_ids],
                "project_selection_source": "manual" if project_ids else "automatic",
                "project_selection_record_ids": list(project_ids),
                "skills_to_include": copy.deepcopy(list(skill_records)),
                "experience_to_include": [{"record_id": record_id} for record_id in experience_ids],
                "certifications_to_include": [copy.deepcopy(certifications[record_id]) for record_id in certification_ids],
            },
        }
        plan_path = self.root / reference
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        store_path = self.data / "applications.json"
        store = json.loads(store_path.read_text(encoding="utf-8"))
        store["applications"].append({
            "application_id": application_id,
            "phase8_plan_reference": reference,
            "resume_generation_allowed": True,
            "resume_working_artifact_stale": False,
            "working_resume_generation_id": "gen_profile_invalidation_test",
            "working_resume_docx_path": "output/resumes/profile_invalidation_test.docx",
            "resume_final_stale": False,
            "current_status": "resume_ready",
            "status_history": [],
            "project_selection_record_ids": list(project_ids),
            "selected_projects": [projects[record_id]["name"] for record_id in project_ids],
            "selected_skills": [item["name"] for item in skill_records],
            "selected_experience": list(experience_ids),
            "selected_certifications": [certifications[record_id]["name"] for record_id in certification_ids],
        })
        store_path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
        return plan_path

    def _post(self, path, payload):
        server = ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
        host = f"127.0.0.1:{server.server_port}"
        original_hosts = set(api._ALLOWED_HOSTS)
        api._ALLOWED_HOSTS.add(host)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            headers = {"Content-Type": "application/json"}
            if api._API_TOKEN:
                headers["Authorization"] = f"Bearer {api._API_TOKEN}"
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("POST", path, body=json.dumps(payload), headers=headers)
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
        result = api.apply_profile_edit({"plan": plan, "confirmed": True, "pin": self.pin})
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
        pua.dump("master_profile", data["master_profile"], self.root, pin=self.pin)
        stale_snapshot = {path: path.read_bytes() for path in self.data.glob("*.json")}
        result = api.apply_profile_edit({"plan": plan, "confirmed": True, "pin": self.pin})
        self.assertEqual(result["decision"], "stale_profile")
        self.assertEqual({path: path.read_bytes() for path in self.data.glob("*.json")}, stale_snapshot)

    def test_invalid_addition_is_rejected_without_partial_writes(self):
        additions = self._additions()
        additions["projects"][0]["fields"]["github_url"] = "https://example.invalid/not-github"
        original = {path: path.read_bytes() for path in self.data.glob("*.json")}

        plan = api.plan_profile_edit({"updates": {}, "additions": additions})
        result = api.apply_profile_edit({"plan": plan, "confirmed": True, "pin": self.pin})

        self.assertEqual(plan["decision"], "invalid")
        self.assertEqual(result["decision"], "invalid")
        self.assertEqual({path: path.read_bytes() for path in self.data.glob("*.json")}, original)

    def test_profile_edits_persist_and_return_updated_canonical_profile(self):
        before = pua.all_data(self.root)
        applications_before = (self.data / "applications.json").read_bytes()
        untouched_project = copy.deepcopy(before["projects"]["projects"][1])
        untouched_skill_group = copy.deepcopy(before["skills"]["skill_groups"][-1])
        old_skill = next(
            skill for group in before["skills"]["skill_groups"]
            for skill in group["skills"]
            if group["category"] == "programming_languages"
        )
        plan = self._plan()
        self.assertEqual(plan["decision"], "planned", plan)
        result = api.apply_profile_edit({"plan": plan, "confirmed": True, "pin": self.pin})

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
        self.assertEqual((self.data / "applications.json").read_bytes(), applications_before)
        self.assertEqual({path: path.read_bytes() for path in self.artifact_bytes}, self.artifact_bytes)

    def test_persistence_requires_explicit_confirmation(self):
        plan = self._plan()
        original = {path: path.read_bytes() for path in self.data.glob("*.json")}

        result = api.apply_profile_edit({"plan": plan})

        self.assertEqual(result["decision"], "confirmation_required")
        self.assertEqual({path: path.read_bytes() for path in self.data.glob("*.json")}, original)

    def test_missing_wrong_and_invalid_pin_reject_without_changing_profile(self):
        plan = self._plan()
        profile_files = [self.data / f"{name}.json" for name in pua.CATEGORIES]
        original = {path: path.read_bytes() for path in profile_files}
        for pin in (None, self.wrong_pin, "12x456", "12345", "1234567"):
            payload = {"plan": plan, "confirmed": True}
            if pin is not None:
                payload["pin"] = pin
            result = api.apply_profile_edit(payload)
            self.assertEqual(result["decision"], "pin_verification_required", result)
            self.assertNotIn(self.pin, json.dumps(result))
            self.assertEqual({path: path.read_bytes() for path in profile_files}, original)

    def test_direct_http_write_without_pin_is_unauthorized_and_read_only_access_works(self):
        plan = self._plan()
        profile_files = [self.data / f"{name}.json" for name in pua.CATEGORIES]
        original = {path: path.read_bytes() for path in profile_files}
        status, result = self._post("/api/profile/edit/apply", {"plan": plan, "confirmed": True})

        self.assertEqual(status, 401)
        self.assertEqual(result["decision"], "pin_verification_required")
        self.assertNotIn(self.pin, json.dumps(result))
        self.assertEqual({path: path.read_bytes() for path in profile_files}, original)
        self.assertEqual(api.profile_summary()["name"], pua.all_data(self.root)["master_profile"]["profile"]["name"])
        self.assertEqual(api.profile_security_status(), {"pin_configured": True})

    def test_pin_hash_is_separate_from_profile_and_never_returned(self):
        pin_hash = os.environ["CAREER_OS_PROFILE_PIN_HASH"]
        profile_json = "\n".join(path.read_text(encoding="utf-8") for path in self.data.glob("*.json"))
        self.assertNotIn(self.pin, profile_json)
        self.assertNotIn(pin_hash, profile_json)
        self.assertFalse((self.data / "profile_security.json").exists())
        self.assertNotIn(self.pin, json.dumps(api.profile_security_status()))
        self.assertNotIn(pin_hash, json.dumps(api.profile_security_status()))

    def test_missing_environment_hash_fails_closed_without_writing(self):
        plan = self._plan()
        original = {path: path.read_bytes() for path in self.data.glob("*.json")}
        os.environ.pop("CAREER_OS_PROFILE_PIN_HASH", None)

        result = api.apply_profile_edit({"plan": plan, "confirmed": True, "pin": self.pin})

        self.assertEqual(result["decision"], "pin_verification_required")
        self.assertFalse(api.profile_security_status()["pin_configured"])
        self.assertEqual({path: path.read_bytes() for path in self.data.glob("*.json")}, original)
        self.assertFalse((self.data / "profile_security.json").exists())

    def test_common_profile_file_writer_rejects_direct_calls_without_pin(self):
        original = {path: path.read_bytes() for path in self.data.glob("*.json") if path.name != "profile_security.json"}
        for category in pua.CATEGORIES:
            with self.subTest(category=category), self.assertRaises(psecurity.ProfilePinVerificationError):
                pua.dump(category, pua.all_data(self.root)[category], self.root)
        self.assertEqual({path: path.read_bytes() for path in original}, original)

    def test_editing_a_selected_project_invalidates_only_affected_approved_application(self):
        projects = pua.all_data(self.root)["projects"]["projects"]
        selected_project, unrelated_project = projects[:2]
        affected_plan_path = self._seed_approved_application("app_selected_project", project_ids=[selected_project["record_id"]])
        unrelated_plan_path = self._seed_approved_application("app_unrelated_project", project_ids=[unrelated_project["record_id"]])
        approved_snapshot = affected_plan_path.read_bytes()

        edit_plan = api.plan_profile_edit({"updates": {"projects": [{
            "record_id": selected_project["record_id"],
            "fields": {"purpose": "Updated source-backed purpose for lifecycle test."},
        }]}})
        result = api.apply_profile_edit({"plan": edit_plan, "confirmed": True, "pin": self.pin})

        self.assertEqual(result["decision"], "profile_updated", result)
        applications = {item["application_id"]: item for item in json.loads((self.data / "applications.json").read_text(encoding="utf-8"))["applications"]}
        self.assertFalse(applications["app_selected_project"]["resume_generation_allowed"])
        self.assertEqual(applications["app_selected_project"]["current_status"], "awaiting_resume_approval")
        self.assertTrue(applications["app_selected_project"]["resume_working_artifact_stale"])
        self.assertTrue(applications["app_unrelated_project"]["resume_generation_allowed"])
        self.assertEqual(affected_plan_path.read_bytes(), approved_snapshot)
        self.assertTrue(unrelated_plan_path.is_file())

    def test_selected_skills_certifications_experience_and_education_invalidate_approval(self):
        for index, category in enumerate(("skills", "certifications", "experience", "education")):
            with self.subTest(category=category):
                profile = pua.all_data(self.root)
                if category == "skills":
                    group = profile["skills"]["skill_groups"][0]
                    item = group["skills"][0]
                    selection = {"skill_records": [{"name": item["name"], "category": group["category"]}]}
                    updates = {"skills": [{"name": item["name"], "category": group["category"], "fields": {"name": item["name"] + " Updated"}}]}
                elif category == "certifications":
                    item = profile["certifications"]["certifications"][0]
                    selection = {"certification_ids": [item["record_id"]]}
                    updates = {"certifications": [{"record_id": item["record_id"], "fields": {"issuer": "Updated issuer for lifecycle test"}}]}
                elif category == "experience":
                    item = profile["experience"]["experiences"][0]
                    selection = {"experience_ids": [item["record_id"]]}
                    updates = {"experience": [{"record_id": item["record_id"], "fields": {"title": item["title"] + " Updated"}}]}
                else:
                    item = profile["education"]["education"][0]
                    selection = {}
                    updates = {"education": [{"record_id": item["record_id"], "fields": {"grade": "Updated grade for lifecycle test"}}]}

                application_id = f"app_profile_input_{category}"
                self._seed_approved_application(application_id, **selection)
                edit_plan = api.plan_profile_edit({"updates": updates})
                result = api.apply_profile_edit({"plan": edit_plan, "confirmed": True, "pin": self.pin})
                self.assertEqual(result["decision"], "profile_updated", result)
                applications = json.loads((self.data / "applications.json").read_text(encoding="utf-8"))["applications"]
                updated = next(app for app in applications if app["application_id"] == application_id)
                self.assertFalse(updated["resume_generation_allowed"])
                self.assertEqual(updated["current_status"], "awaiting_resume_approval")

    def test_education_coursework_change_does_not_invalidate_resume_inputs(self):
        education = pua.all_data(self.root)["education"]["education"][0]
        self._seed_approved_application("app_coursework_not_rendered")
        plan = api.plan_profile_edit({"updates": {"education": [{
            "record_id": education["record_id"],
            "fields": {"coursework": ["Additional course outside the resume output"]},
        }]}})
        result = api.apply_profile_edit({"plan": plan, "confirmed": True, "pin": self.pin})

        self.assertEqual(result["decision"], "profile_updated", result)
        app = json.loads((self.data / "applications.json").read_text(encoding="utf-8"))["applications"][0]
        self.assertTrue(app["resume_generation_allowed"])
        self.assertEqual(app["current_status"], "resume_ready")

    def test_profile_added_completed_candidate_project_is_selector_eligible(self):
        additions = {"projects": [{"fields": {
            "name": "Profile Lifecycle Test Project",
            "project_type": "project",
            "project_status": "completed",
            "purpose": "A profile-added project used to verify selector eligibility.",
            "functionality": ["Processes test records."],
            "technologies": ["Python"],
        }}]}
        plan = api.plan_profile_edit({"updates": {}, "additions": additions})
        saved = api.apply_profile_edit({"plan": plan, "confirmed": True, "pin": self.pin})
        self.assertEqual(saved["decision"], "profile_updated", saved)

        project = pua.all_data(self.root)["projects"]["projects"][-1]
        self.assertEqual(project["status"], "candidate_provided")
        self.assertEqual(project["project_status"], "completed")
        self.assertIn(project["record_id"], {item["record_id"] for item in api.eligible_completed_projects()})
        not_a_supported_verification_edit = api.plan_profile_edit({"updates": {"projects": [{
            "record_id": project["record_id"], "fields": {"status": "verified"},
        }]}})
        self.assertEqual(not_a_supported_verification_edit["decision"], "invalid")

        canonical = pua.all_data(self.root)
        canonical_project = next(item for item in canonical["projects"]["projects"] if item["record_id"] == project["record_id"])
        canonical_project["status"] = "verified"
        pua.dump("projects", canonical["projects"], self.root, pin=self.pin)
        self.assertIn(project["record_id"], {item["record_id"] for item in api.eligible_completed_projects()})

    def test_completed_project_selector_accepts_verified_and_candidate_provided_only(self):
        profile = pua.all_data(self.root)
        profile["projects"]["projects"] = [
            {"record_id": "verified_complete", "name": "Verified Complete", "project_status": "completed", "status": "verified", "github_availability": "github_verified"},
            {"record_id": "candidate_complete", "name": "Candidate Complete", "project_status": "completed", "status": "candidate_provided", "github_availability": "github_pending"},
            {"record_id": "candidate_in_progress", "name": "Candidate In Progress", "project_status": "in_progress", "status": "candidate_provided", "github_availability": "github_pending"},
            {"record_id": "incomplete_candidate", "name": "Incomplete Candidate", "project_status": "planned", "status": "candidate_provided", "github_availability": "github_pending"},
            {"record_id": "invalid_candidate", "name": "Invalid Candidate", "project_status": "unknown", "status": "candidate_provided", "github_availability": "github_pending"},
        ]
        pua.dump("projects", profile["projects"], self.root, pin=self.pin)

        eligible = {item["record_id"] for item in api.eligible_completed_projects(self.root)}
        self.assertIn("verified_complete", eligible)
        self.assertIn("candidate_complete", eligible)
        self.assertNotIn("candidate_in_progress", eligible)
        self.assertNotIn("incomplete_candidate", eligible)
        self.assertNotIn("invalid_candidate", eligible)

        candidate = next(item for item in pua.all_data(self.root)["projects"]["projects"] if item["record_id"] == "candidate_complete")
        self.assertEqual(candidate["status"], "candidate_provided")
        self.assertEqual(candidate["github_availability"], "github_pending")

    def test_new_and_reanalyzed_unapproved_applications_use_current_profile(self):
        jd = (
            "Junior Generative AI RAG Engineer\nRequired Skills:\n- Python\n- RAG\n"
            "- ChromaDB\n- Ollama\nResponsibilities:\n- Build retrieval augmented generation applications."
        )
        project_id = "project_student_performance_rag"
        before = planner.plan_resume(jd, pua.all_data(self.root))
        self.assertIn(project_id, [item["record_id"] for item in before["resume_plan"]["projects_to_include"]])

        created = aa.create_application("Profile Freshness Before Approval", "Junior RAG Engineer", "", jd)
        self.assertEqual(created["decision"], "created", created)
        app_id = created["application"]["application_id"]
        profile = pua.all_data(self.root)
        project = next(item for item in profile["projects"]["projects"] if item["record_id"] == project_id)
        edit = api.plan_profile_edit({"updates": {"projects": [{
            "record_id": project_id,
            "fields": {"purpose": "Updated purpose after application creation."},
        }]}})
        saved = api.apply_profile_edit({"plan": edit, "confirmed": True, "pin": self.pin})
        self.assertEqual(saved["decision"], "profile_updated", saved)

        refreshed = api.analyze_resume_plan({"application_id": app_id, "job_description": jd})
        self.assertNotIn(project_id, [item["record_id"] for item in refreshed["resume_plan"]["projects_to_include"]])
        app_after_edit = aa.get_app(app_id)[0]
        self.assertFalse(app_after_edit["resume_generation_allowed"])

        new_application = aa.create_application("Profile Freshness After Approval", "Junior RAG Engineer", "", jd + "\nAdditional responsibility: Maintain service endpoints.")
        self.assertEqual(new_application["decision"], "created", new_application)
        new_plan_path = self.root / new_application["application"]["phase8_plan_reference"]
        new_plan = json.loads(new_plan_path.read_text(encoding="utf-8"))
        self.assertNotIn(project_id, [item["record_id"] for item in new_plan["resume_plan"]["projects_to_include"]])

    def test_invalid_mixed_update_is_rejected_without_partial_writes(self):
        updates = {
            "master_profile": {"name": "Must Not Persist"},
            "projects": [{"record_id": "project_telecom_churn_logistic_regression", "fields": {"github_url": "https://example.invalid/unsupported"}}],
        }
        original = {path: path.read_bytes() for path in self.data.glob("*.json")}

        plan = self._plan(updates)
        result = api.apply_profile_edit({"plan": plan, "confirmed": True, "pin": self.pin})

        self.assertEqual(plan["decision"], "invalid")
        self.assertEqual(result["decision"], "invalid")
        self.assertEqual({path: path.read_bytes() for path in self.data.glob("*.json")}, original)

    def test_stale_profile_plan_is_rejected(self):
        plan = self._plan()
        data = pua.all_data(self.root)
        data["master_profile"]["profile"]["location"] = "Changed after review"
        pua.dump("master_profile", data["master_profile"], self.root, pin=self.pin)
        original = {path: path.read_bytes() for path in self.data.glob("*.json")}

        result = api.apply_profile_edit({"plan": plan, "confirmed": True, "pin": self.pin})

        self.assertEqual(result["decision"], "stale_profile")
        self.assertEqual({path: path.read_bytes() for path in self.data.glob("*.json")}, original)


if __name__ == "__main__":
    unittest.main(verbosity=2)