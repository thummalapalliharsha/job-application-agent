import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from career_os_config import (
    DATA_DIR,
    JOB_DESCRIPTIONS_DIR,
    OUTPUT_DIR,
    POSTGRES_CONFIG,
    resolve_storage_reference,
    storage_reference,
    postgres_storage_ready,
)
from postgres_config import PostgresConfig, load_postgres_config, postgres_storage_ready as postgres_ready, validate_postgres_config


class PostgresConfigContractTests(unittest.TestCase):
    def test_postgres_config_loads_env_values(self):
        with patch.dict(
            os.environ,
            {
                "CAREER_OS_STORAGE_BACKEND": "postgres",
                "POSTGRES_HOST": "db.example.internal",
                "POSTGRES_PORT": "5432",
                "POSTGRES_DB": "career_os",
                "POSTGRES_USER": "app_user",
                "POSTGRES_PASSWORD": "s3cret",
            },
            clear=False,
        ):
            config = load_postgres_config()
            self.assertEqual(config.backend, "postgres")
            self.assertEqual(config.host, "db.example.internal")
            self.assertEqual(config.port, 5432)
            self.assertEqual(config.database, "career_os")
            self.assertEqual(config.user, "app_user")
            self.assertEqual(config.password, "s3cret")
            self.assertTrue(config.is_configured)
            self.assertTrue(postgres_ready(config))

    def test_validate_postgres_config_rejects_missing_required_values(self):
        config = PostgresConfig(
            backend="postgres",
            host="",
            port=5432,
            database="career_os",
            user="app_user",
            password="",
            url="",
        )
        valid, missing = validate_postgres_config(config)
        self.assertFalse(valid)
        self.assertIn("POSTGRES_PASSWORD", missing)
        self.assertIn("POSTGRES_HOST", validate_postgres_config(PostgresConfig(backend="postgres", host="", port=5432, database="career_os", user="app_user", password="pw", url=""))[1])

    def test_postgres_storage_ready_false_when_backend_is_not_postgres(self):
        config = PostgresConfig(backend="file")
        self.assertFalse(postgres_storage_ready(config))
        self.assertFalse(postgres_storage_ready())

    def test_storage_reference_and_resolve_round_trip_for_default_roots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_file = root / "data" / "master_profile.json"
            data_file.parent.mkdir(parents=True, exist_ok=True)
            data_file.write_text('{"name": "Example"}', encoding="utf-8")
            jobs_file = root / "job_descriptions" / "app_123.txt"
            jobs_file.parent.mkdir(parents=True, exist_ok=True)
            jobs_file.write_text("job text", encoding="utf-8")
            output_file = root / "output" / "reports" / "report.json"
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text("{}", encoding="utf-8")

            self.assertEqual(storage_reference(data_file, root=root), "data/master_profile.json")
            self.assertEqual(storage_reference(jobs_file, root=root), "job_descriptions/app_123.txt")
            self.assertEqual(storage_reference(output_file, root=root), "output/reports/report.json")

            self.assertEqual(resolve_storage_reference("data/master_profile.json", root=root), data_file.resolve())
            self.assertEqual(resolve_storage_reference("job_descriptions/app_123.txt", root=root), jobs_file.resolve())
            self.assertEqual(resolve_storage_reference("output/reports/report.json", root=root), output_file.resolve())

    def test_default_storage_paths_are_compatible_with_existing_config(self):
        self.assertTrue(DATA_DIR.exists())
        self.assertTrue(JOB_DESCRIPTIONS_DIR.exists())
        self.assertTrue(OUTPUT_DIR.exists())
        self.assertIsInstance(POSTGRES_CONFIG, PostgresConfig)


if __name__ == "__main__":
    unittest.main()
