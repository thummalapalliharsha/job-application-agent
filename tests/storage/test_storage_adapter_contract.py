import json
import tempfile
import unittest
from pathlib import Path

from postgres_storage_adapter import PostgresStorageAdapter
from storage_adapter import FileStorageAdapter, StorageAdapter


class StorageAdapterContractTests(unittest.TestCase):
    def test_storage_adapter_is_abstract(self):
        self.assertTrue(hasattr(StorageAdapter, "load_profile_documents"))
        self.assertTrue(hasattr(StorageAdapter, "save_profile_documents"))
        self.assertTrue(hasattr(StorageAdapter, "load_application_store"))
        self.assertTrue(hasattr(StorageAdapter, "save_application_store"))

    def test_file_adapter_profile_document_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = FileStorageAdapter(root=tmpdir)
            profile_documents = {
                "master_profile": {
                    "profile": {
                        "name": "Ada Lovelace",
                        "location": "London",
                        "links": {"github": "github.com/ada"},
                    },
                    "source_documents": [{"source_id": "resume", "source_name": "resume.pdf"}],
                    "record_indexes": {"project_ids": ["project_1"]},
                    "conflicts_requiring_review": [],
                },
                "skills": {"skill_groups": [{"category": "programming_languages", "skills": [{"name": "Python"}]}]},
                "projects": {"projects": [{"record_id": "project_1", "name": "Ada Project", "technologies": ["Python", "SQL"]}]},
                "experience": {"experiences": [{"record_id": "exp_1", "organization": "Analytical Engine"}]},
                "certifications": {"certifications": [{"name": "Certified Analyst"}]},
                "education": {"education": [{"institution": "University of London"}]},
                "achievements": {"achievements": [{"name": "First Published Paper"}]},
            }

            adapter.save_profile_documents(profile_documents)
            loaded = adapter.load_profile_documents()

            self.assertEqual(loaded, profile_documents)
            self.assertEqual(json.loads((Path(tmpdir) / "data" / "master_profile.json").read_text(encoding="utf-8"))["profile"]["name"], "Ada Lovelace")

    def test_file_adapter_application_store_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = FileStorageAdapter(root=tmpdir)
            store = {
                "applications": [
                    {
                        "application_id": "app_123",
                        "company_name": "Example Corp",
                        "job_title": "Data Analyst",
                        "status_history": [{"old_status": None, "new_status": "awaiting_resume_approval"}],
                        "selected_projects": ["Project A"],
                        "selected_skills": ["Python"],
                    }
                ]
            }

            adapter.save_application_store(store)
            loaded = adapter.load_application_store()

            self.assertEqual(loaded, store)

    def test_missing_profile_documents_return_empty_default_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = FileStorageAdapter(root=tmpdir)
            loaded = adapter.load_profile_documents()

            self.assertIn("master_profile", loaded)
            self.assertIn("skills", loaded)
            self.assertIn("projects", loaded)
            self.assertIn("experience", loaded)
            self.assertIn("certifications", loaded)
            self.assertIn("education", loaded)
            self.assertIn("achievements", loaded)
            self.assertEqual(loaded["skills"], {"skill_groups": []})
            self.assertEqual(loaded["projects"], {"projects": []})
            self.assertEqual(loaded["achievements"], {"achievements": []})

    def test_missing_application_store_returns_empty_default_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = FileStorageAdapter(root=tmpdir)
            self.assertEqual(adapter.load_application_store(), {"applications": []})

    def test_postgres_adapter_preserves_nested_json_on_write_then_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = PostgresStorageAdapter(root=tmpdir)
            payload = {
                "master_profile": {
                    "profile": {"name": "Jane Doe", "links": {"linkedin": "linkedin.com/in/jane"}},
                    "source_documents": [{"source_id": "resume", "source_name": "resume.pdf"}],
                    "record_indexes": {"project_ids": ["project_42"]},
                    "conflicts_requiring_review": [],
                },
                "skills": {"skill_groups": [{"category": "tools_and_platforms", "skills": [{"name": "Git"}]}]},
                "projects": {"projects": [{"record_id": "project_42", "name": "RAG Demo", "technologies": ["Python", "OpenAI"]}]},
                "experience": {"experiences": []},
                "certifications": {"certifications": []},
                "education": {"education": []},
                "achievements": {"achievements": []},
            }

            adapter.save_profile_documents(payload)
            loaded = adapter.load_profile_documents()

            self.assertEqual(loaded, payload)
            self.assertEqual(loaded["master_profile"]["profile"]["links"]["linkedin"], "linkedin.com/in/jane")

    def test_postgres_adapter_uses_compatibility_fallback_without_inventing_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = PostgresStorageAdapter(root=tmpdir)
            missing_profile = adapter.load_profile_documents()
            missing_store = adapter.load_application_store()

            self.assertEqual(missing_profile["skills"], {"skill_groups": []})
            self.assertEqual(missing_store, {"applications": []})
            self.assertFalse(adapter.is_ready())


if __name__ == "__main__":
    unittest.main()
