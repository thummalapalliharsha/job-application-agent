import json
import tempfile
import unittest
from pathlib import Path

from postgres_backfill_dry_run import (
    build_a_tier_manifest,
    run_isolated_dry_run,
    validate_manifest,
)


class PostgresBackfillDryRunTests(unittest.TestCase):
    def _write_fixture(self, root: Path) -> None:
        data_dir = root / "data"
        data_dir.mkdir(parents=True)

        payloads = {
            "master_profile.json": {
                "profile": {"name": "Synthetic Candidate"},
                "record_indexes": {"project_ids": ["project_1", "project_2"]},
                "conflicts_requiring_review": [],
            },
            "projects.json": {
                "projects": [
                    {"record_id": "project_1", "name": "Synthetic Project One"},
                    {"record_id": "project_2", "name": "Synthetic Project Two"},
                ]
            },
            "skills.json": {
                "skill_groups": [
                    {"category": "programming_languages", "skills": [{"name": "Python"}]},
                    {"category": "data_tools", "skills": [{"name": "SQL"}]},
                ]
            },
            "experience.json": {
                "experiences": [{"record_id": "experience_1", "organization": "Example Org"}]
            },
            "education.json": {
                "education": [{"record_id": "education_1", "institution": "Example University"}]
            },
            "certifications.json": {
                "certifications": [{"record_id": "certification_1", "name": "Example Certificate"}]
            },
            "applications.json": {
                "applications": [
                    {
                        "application_id": "app_1",
                        "job_description_reference": "job_descriptions/app_1.txt",
                        "phase8_plan_reference": "output/reports/app_1_plan.json",
                        "selected_projects": ["project_1"],
                        "selected_skills": ["Python"],
                    },
                    {
                        "application_id": "app_2",
                        "job_description_reference": "job_descriptions/app_2.txt",
                        "selected_projects": ["project_2"],
                        "selected_skills": ["SQL"],
                    },
                ]
            },
            "document_history.json": {
                "documents": [
                    {"document_id": "doc_1", "application_id": "missing_app_1"},
                    {"document_id": "doc_2", "application_id": "missing_app_2"},
                    {"document_id": "doc_3", "application_id": "missing_app_3"},
                ]
            },
        }
        for name, payload in payloads.items():
            (data_dir / name).write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

        job_descriptions_dir = root / "job_descriptions"
        job_descriptions_dir.mkdir()
        for app_id in ("app_1", "app_2"):
            (job_descriptions_dir / f"{app_id}.txt").write_text(
                f"Synthetic job description for {app_id}.",
                encoding="utf-8",
            )

        reports_dir = root / "output" / "reports"
        reports_dir.mkdir(parents=True)
        for name in ("app_1_plan.json", "validation_1.json", "validation_2.json"):
            (reports_dir / name).write_text(
                json.dumps({"fixture": True, "report": name}),
                encoding="utf-8",
            )

    def test_a_tier_manifest_counts_and_references_are_stable(self):
        with tempfile.TemporaryDirectory(prefix="career-os-backfill-fixture-") as tmp:
            root = Path(tmp)
            self._write_fixture(root)
            manifest = build_a_tier_manifest(root)

            self.assertEqual(
                manifest["datasets"],
                {
                    "master_profile": 1,
                    "projects": 2,
                    "skills": 2,
                    "experience": 1,
                    "education": 1,
                    "certifications": 1,
                    "applications": 2,
                    "document_history": 3,
                    "job_descriptions": 2,
                    "reports": 3,
                },
            )
            self.assertEqual(manifest["application_ids"], ["app_1", "app_2"])
            self.assertEqual(len(set(manifest["application_ids"])), 2)
            self.assertEqual(manifest["project_ids"], ["project_1", "project_2"])
            self.assertEqual(len(set(manifest["project_ids"])), 2)

            for app_id in manifest["application_ids"]:
                refs = manifest["application_refs"][app_id]
                jd_ref = refs["job_description_reference"]
                self.assertTrue(jd_ref.startswith("job_descriptions/"))
                self.assertTrue((root / jd_ref).is_file())
                if refs.get("phase8_plan_reference"):
                    plan_ref = refs["phase8_plan_reference"]
                    self.assertTrue(plan_ref.startswith("output/reports/"))
                    self.assertTrue((root / plan_ref).is_file())

            history_ids = {
                doc.get("application_id") for doc in manifest["document_history"]
            }
            self.assertFalse(history_ids.issubset(set(manifest["application_ids"])))
            self.assertEqual(len(manifest["quarantined"]), 3)
            self.assertEqual(validate_manifest(manifest, root), [])

    def test_isolated_dry_run_allows_round_trip_without_external_writes(self):
        with tempfile.TemporaryDirectory(prefix="career-os-backfill-fixture-") as fixture_tmp:
            root = Path(fixture_tmp)
            self._write_fixture(root)
            files_before = {
                path.relative_to(root) for path in root.rglob("*") if path.is_file()
            }

            with tempfile.TemporaryDirectory(
                prefix="career-os-backfill-staging-"
            ) as staging_tmp:
                dry_run = run_isolated_dry_run(root, staging_root=staging_tmp)

                self.assertTrue(dry_run["dry_run_ok"])
                self.assertTrue(dry_run["staging_target"].startswith("sqlite:///"))
                self.assertEqual(dry_run["dataset_count"], 10)
                self.assertEqual(
                    dry_run["records_inserted"],
                    2 + 2 + 2 + 1 + 1 + 1 + 2 + 3,
                )
                self.assertEqual(len(dry_run["quarantined_records"]), 3)
                self.assertTrue(dry_run["round_trip_ok"])
                self.assertEqual(dry_run["duplicate_conflicts"], [])
                database_path = Path(
                    dry_run["staging_target"][len("sqlite:///"):]
                )
                self.assertEqual(
                    database_path.resolve(),
                    (Path(staging_tmp) / "backfill_dryrun.sqlite3").resolve(),
                )

            files_after = {
                path.relative_to(root) for path in root.rglob("*") if path.is_file()
            }
            self.assertEqual(files_after, files_before)


if __name__ == "__main__":
    unittest.main()
