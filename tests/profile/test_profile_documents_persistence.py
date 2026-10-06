import json
import os
import tempfile
import unittest
from pathlib import Path

import career_os_api as api
import profile_update_agent as pua
from profile_security import ProfilePinVerificationError, hash_profile_pin


class ProfileDocumentsPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.pin = "123456"
        os.environ["CAREER_OS_PROFILE_PIN_HASH"] = hash_profile_pin(self.pin)

    def _profile_documents(self):
        return {
            "master_profile": {
                "profile": {
                    "name": "Ada Lovelace",
                    "headline": "Analyst and mathematician",
                    "location": "London",
                    "contact": {"email": "ada@example.com"},
                    "links": {"github": "github.com/ada"},
                },
                "source_documents": [{"source_id": "resume", "source_name": "resume.pdf"}],
                "record_indexes": {"project_ids": ["project_1"], "skill_categories": ["programming_languages"]},
                "conflicts_requiring_review": [],
                "provenance": [{"source_id": "resume"}],
            },
            "skills": {
                "skill_groups": [
                    {"category": "programming_languages", "skills": [{"name": "Python", "status": "verified"}]}
                ]
            },
            "projects": {
                "projects": [
                    {
                        "record_id": "project_1",
                        "name": "Analytical Engine",
                        "project_status": "completed",
                        "github_availability": "github_verified",
                        "technologies": ["Python", "SQL"],
                        "selection_metadata": {"available_for_resume": True},
                    }
                ]
            },
            "experience": {
                "experiences": [
                    {"record_id": "exp_1", "organization": "Analytical Engine", "title": "Mathematician"}
                ]
            },
            "certifications": {"certifications": [{"record_id": "cred_1", "name": "Certified Analyst"}]},
            "education": {"education": [{"record_id": "edu_1", "institution": "University of London", "degree": "BSc"}]},
            "achievements": {"achievements": [{"record_id": "ach_1", "name": "Published paper"}]},
        }

    def test_canonical_profile_documents_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name, payload in self._profile_documents().items():
                pua.dump(name, payload, root=tmpdir, pin=self.pin)

            reloaded = pua.all_data(tmpdir)
            for name, payload in self._profile_documents().items():
                self.assertEqual(reloaded[name], payload)
                self.assertEqual(pua.load(name, root=tmpdir), payload)

    def test_missing_profile_documents_use_compatibility_default_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data = pua.all_data(tmpdir)
            self.assertEqual(data["master_profile"]["profile"], {})
            self.assertEqual(data["skills"], {"skill_groups": []})
            self.assertEqual(data["projects"], {"projects": []})
            self.assertEqual(data["experience"], {"experiences": []})
            self.assertEqual(data["certifications"], {"certifications": []})
            self.assertEqual(data["education"], {"education": []})
            self.assertEqual(data["achievements"], {"achievements": []})

    def test_invalid_pin_still_blocks_profile_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ProfilePinVerificationError):
                pua.dump("skills", {"skill_groups": []}, root=tmpdir, pin="000000")

    def test_profile_add_edit_plan_applies_without_changing_profile_shapes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            initial = self._profile_documents()
            for name, payload in initial.items():
                pua.dump(name, payload, root=tmpdir, pin=self.pin)

            plan = pua.plan_profile_edit(
                updates={
                    "master_profile": {"location": "Paris"},
                    "projects": [{"record_id": "project_1", "fields": {"technologies": ["Python", "SQL", "Rust"]}}],
                },
                additions={
                    "skills": [{"category": "programming_languages", "fields": {"name": "Rust"}}],
                },
                root=tmpdir,
            )
            self.assertEqual(plan["decision"], "planned")

            pua.apply_plan(plan, root=tmpdir, confirm=True, pin=self.pin, invalidate_applications=False)
            after = pua.all_data(tmpdir)
            self.assertEqual(after["master_profile"]["profile"]["location"], "Paris")
            self.assertTrue(any(item["name"] == "Rust" for item in after["skills"]["skill_groups"][0]["skills"]))

    def test_profile_changes_invalidate_approved_applications_when_relevant(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_dir = root / "data"
            data_dir.mkdir(parents=True, exist_ok=True)

            initial = self._profile_documents()
            for name, payload in initial.items():
                (data_dir / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            plan_path = root / "output" / "reports" / "approved_plan.json"
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(json.dumps({"resume_plan": {"projects_to_include": [{"record_id": "project_1"}], "skills_to_include": [{"name": "Python"}]}}), encoding="utf-8")

            app = {
                "application_id": "app_123",
                "resume_generation_allowed": True,
                "current_status": "resume_ready",
                "phase8_plan_reference": "output/reports/approved_plan.json",
                "project_selection_record_ids": ["project_1"],
                "selected_skills": ["Python"],
                "status_history": [{"old_status": "resume_ready", "new_status": "resume_ready"}],
                "last_updated": "2026-01-01T00:00:00Z",
            }
            (data_dir / "applications.json").write_text(json.dumps({"applications": [app]}, ensure_ascii=False), encoding="utf-8")

            invalidated = api.invalidate_approved_applications_for_profile_actions(
                [{"action": "update_profile_fields", "category": "master_profile", "selector": {"record_id": "master_profile"}, "fields": {"name": "New Name"}}],
                root=tmpdir,
            )
            self.assertIn("app_123", invalidated)

            updated = json.loads((data_dir / "applications.json").read_text(encoding="utf-8"))
            self.assertFalse(updated["applications"][0]["resume_generation_allowed"])
            self.assertEqual(updated["applications"][0]["current_status"], "awaiting_resume_approval")

            unaffected = api.invalidate_approved_applications_for_profile_actions(
                [{"action": "update_profile_fields", "category": "master_profile", "selector": {"record_id": "master_profile"}, "fields": {"headline": "Unrelated change"}}],
                root=tmpdir,
            )
            self.assertEqual(unaffected, [])


if __name__ == "__main__":
    unittest.main()
