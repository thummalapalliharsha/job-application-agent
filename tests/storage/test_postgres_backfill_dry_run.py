import json
import tempfile
import unittest
from pathlib import Path

from postgres_backfill_dry_run import build_a_tier_manifest, run_isolated_dry_run


class PostgresBackfillDryRunTests(unittest.TestCase):
    def test_a_tier_manifest_counts_and_references_are_stable(self):
        root = Path(__file__).resolve().parents[2]
        manifest = build_a_tier_manifest(root)

        self.assertEqual(manifest["datasets"]["master_profile"], 1)
        self.assertEqual(manifest["datasets"]["projects"], 13)
        self.assertEqual(manifest["datasets"]["skills"], 8)
        self.assertEqual(manifest["datasets"]["experience"], 2)
        self.assertEqual(manifest["datasets"]["education"], 3)
        self.assertEqual(manifest["datasets"]["certifications"], 6)
        self.assertEqual(manifest["datasets"]["applications"], 7)
        self.assertEqual(manifest["datasets"]["document_history"], 2)
        self.assertEqual(manifest["datasets"]["job_descriptions"], 15)
        self.assertEqual(manifest["datasets"]["reports"], 69)

        self.assertEqual(len(manifest["application_ids"]), 7)
        self.assertEqual(len(set(manifest["application_ids"])), 7)
        self.assertEqual(len(manifest["project_ids"]), 13)
        self.assertEqual(len(set(manifest["project_ids"])), 13)

        for app_id in manifest["application_ids"]:
            ref = manifest["application_refs"][app_id]["job_description_reference"]
            self.assertTrue(ref.startswith("job_descriptions/"))
            self.assertTrue((root / ref).exists())
            if manifest["application_refs"][app_id].get("phase8_plan_reference"):
                plan_ref = manifest["application_refs"][app_id]["phase8_plan_reference"]
                self.assertTrue(plan_ref.startswith("output/reports/"))
                self.assertTrue((root / plan_ref).exists())

        history_ids = {doc.get("application_id") for doc in manifest["document_history"]}
        self.assertFalse(history_ids.issubset(set(manifest["application_ids"])))
        self.assertEqual(len(manifest["quarantined"]), 3)

    def test_isolated_dry_run_allows_round_trip_without_external_writes(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix="career-os-dryrun-") as tmp:
            dry_run = run_isolated_dry_run(root, staging_root=tmp)

            self.assertTrue(dry_run["dry_run_ok"])
            self.assertTrue(dry_run["staging_target"].startswith("sqlite://"))
            self.assertEqual(dry_run["dataset_count"], 10)
            self.assertEqual(dry_run["records_inserted"], 7 + 13 + 8 + 2 + 3 + 6 + 15 + 69)
            self.assertEqual(len(dry_run["quarantined_records"]), 3)
            self.assertEqual(dry_run["round_trip_ok"], True)
            self.assertEqual(dry_run["duplicate_conflicts"], [])


if __name__ == "__main__":
    unittest.main()
