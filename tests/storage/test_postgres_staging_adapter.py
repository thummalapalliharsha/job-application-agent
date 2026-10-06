import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from postgres_storage_adapter import PostgresStorageAdapter


class DummyCursor:
    def __init__(self):
        self.executed = []
        self._payloads = {
            "master_profile": {
                "profile": {"name": "Jane Doe", "links": {"linkedin": "linkedin.com/in/jane"}},
                "source_documents": [{"source_id": "resume"}],
                "record_indexes": {"project_ids": ["project_1"]},
                "conflicts_requiring_review": [],
            },
            "skills": {"skill_groups": [{"category": "programming_languages", "skills": [{"name": "Python"}]}]},
            "projects": {"projects": [{"record_id": "project_1", "name": "Demo"}]},
            "experience": {"experiences": []},
            "certifications": {"certifications": []},
            "education": {"education": []},
            "achievements": {"achievements": []},
        }
        self.last_params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self.last_params = params
        return None

    def fetchone(self):
        if self.last_params and isinstance(self.last_params, tuple) and self.last_params and self.last_params[0] in self._payloads:
            return (json.dumps(self._payloads[self.last_params[0]], ensure_ascii=False),)
        return None

    def fetchall(self):
        return [("app_1", json.dumps({"application_id": "app_1", "job_title": "Engineer"}))]


class DummyConnection:
    def __init__(self):
        self.cursor_obj = DummyCursor()

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        return None

    def rollback(self):
        return None

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class PostgresStorageAdapterTests(unittest.TestCase):
    def test_postgres_adapter_uses_postgres_backend_and_preserves_shapes(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@ep-neon-staging.neon.tech/neondb",
            },
            clear=False,
        ):
            adapter = PostgresStorageAdapter(root=tmpdir)
            adapter.client = Mock()
            adapter.client.healthcheck.return_value = {"backend": "postgres", "configured": True, "ready": True, "reachable": True, "error": None}
            adapter.client.connect.return_value = DummyConnection()

            payload = {
                "master_profile": {
                    "profile": {"name": "Jane Doe", "links": {"linkedin": "linkedin.com/in/jane"}},
                    "source_documents": [{"source_id": "resume"}],
                    "record_indexes": {"project_ids": ["project_1"]},
                    "conflicts_requiring_review": [],
                },
                "skills": {"skill_groups": [{"category": "programming_languages", "skills": [{"name": "Python"}]}]},
                "projects": {"projects": [{"record_id": "project_1", "name": "Demo"}]},
                "experience": {"experiences": []},
                "certifications": {"certifications": []},
                "education": {"education": []},
                "achievements": {"achievements": []},
            }

            adapter.save_profile_documents(payload)
            loaded = adapter.load_profile_documents()
            self.assertEqual(loaded["master_profile"]["profile"]["name"], "Jane Doe")
            self.assertEqual(adapter.validate(), [])

    def test_postgres_adapter_fails_closed_on_unhealthy_stage(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "CAREER_OS_POSTGRES_URL": "postgresql://user:pw@ep-neon-staging.neon.tech/neondb",
            },
            clear=False,
        ):
            adapter = PostgresStorageAdapter(root=tmpdir)
            adapter.client = Mock()
            adapter.client.healthcheck.return_value = {"backend": "postgres", "configured": True, "ready": False, "reachable": False, "error": "timeout"}

            with self.assertRaises(RuntimeError):
                adapter.save_profile_documents({"master_profile": {"profile": {}}, "skills": {"skill_groups": []}, "projects": {"projects": []}, "experience": {"experiences": []}, "certifications": {"certifications": []}, "education": {"education": []}, "achievements": {"achievements": []}})

    def test_postgres_adapter_refuses_non_postgres_backend(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {"CAREER_OS_STORAGE_BACKEND": "file"}, clear=False):
            adapter = PostgresStorageAdapter(root=tmpdir)
            self.assertFalse(adapter.is_ready())
            with self.assertRaises(RuntimeError):
                adapter.load_profile_documents()


if __name__ == "__main__":
    unittest.main()
