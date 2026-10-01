#!/usr/bin/env python3
"""Atomic save/finalization-guard tests using an isolated copy of real Rex.zone data."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import application_assistant as aa
import career_os_api as api
import resume_document_model as rdm
import resume_document_renderer as renderer
import resume_generator as rg

AID = "app_14a66f897623"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def isolated_real_rex_store(test_case):
    """Copy only the real app/store/plan/artifacts to a temp root; no fake records."""
    with tempfile.TemporaryDirectory(prefix="resume-document-save-test-") as temporary:
        root = Path(temporary)
        data_dir = root / "data"
        (root / "output" / "reports").mkdir(parents=True)
        data_dir.mkdir()
        source_store = ROOT / "data" / "applications.json"
        store_bytes = source_store.read_bytes()
        (data_dir / "applications.json").write_bytes(store_bytes)
        store = json.loads(store_bytes.decode("utf-8"))
        app = next(item for item in store["applications"] if item["application_id"] == AID)
        plan_source = ROOT / app["phase8_plan_reference"]
        plan_target = root / app["phase8_plan_reference"]
        plan_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(plan_source, plan_target)
        protected_refs = [
            app.get("working_resume_docx_path"), app.get("working_resume_pdf_path"),
            app.get("resume_docx_path"), app.get("resume_pdf_path"),
        ]
        protected: dict[Path, str] = {}
        for reference in protected_refs:
            if not reference:
                continue
            source = ROOT / reference
            if source.is_file():
                target = root / reference
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                protected[target] = sha(target)
        original_data_root, original_api_root = aa.DATA, api.ROOT
        try:
            aa.DATA = data_dir
            api.ROOT = root
            yield root, protected, store_bytes
        finally:
            aa.DATA = original_data_root
            api.ROOT = original_api_root


def current_model():
    loaded = api.resume_document_payload(AID)
    if loaded.get("decision") != "ready":
        raise AssertionError(loaded)
    return loaded


def supported_copyedit(document):
    edited = json.loads(json.dumps(document))
    candidates = [block for section in edited["content"]["sections"] for block in section["blocks"]
                  if block.get("type") == "project_bullet"]
    target = next((block for block in candidates if "natural-language" in "".join(r.get("text", "") for r in block.get("runs", []))), None)
    if not target:
        raise AssertionError("The expected source-backed Rex.zone Text-to-SQL bullet was not present")
    target["runs"][0]["text"] = target["runs"][0]["text"].replace("natural-language", "natural language", 1)
    return edited


def active_refs(app):
    return app.get("working_resume_docx_path"), app.get("working_resume_pdf_path")


class ResumeDocumentSaveTests(unittest.TestCase):
    def test_valid_edit_stages_validates_and_atomically_activates_revision(self):
        with isolated_real_rex_store(self) as (root, protected, original_store):
            loaded = current_model()
            baseline_revision = loaded["document"]["revision_id"]
            payload = {"base_revision_id": baseline_revision, "document": supported_copyedit(loaded["document"])}
            result = api.save_resume_document_payload(AID, payload)
            self.assertEqual(result.get("decision"), "saved", result)
            self.assertTrue(result.get("persisted"))
            self.assertEqual(result["validation"]["final_status"], "PASS")
            self.assertEqual(result["validation"]["page_count"], 1)
            self.assertTrue(result["working"]["revision_id"].startswith("rev_"))

            store_path = root / "data" / "applications.json"
            current_store = json.loads(store_path.read_text(encoding="utf-8"))
            app = next(item for item in current_store["applications"] if item["application_id"] == AID)
            self.assertEqual(app["company_name"], "Rex.zone")
            self.assertEqual(app["application_id"], AID)
            self.assertEqual(app["working_resume_revision_id"], result["working"]["revision_id"])
            self.assertTrue(app["working_resume_validated"])
            self.assertFalse(app["resume_working_artifact_stale"])
            self.assertEqual(app["working_resume_docx_sha256"], sha(root / app["working_resume_docx_path"]))
            self.assertEqual(app["working_resume_pdf_sha256"], sha(root / app["working_resume_pdf_path"]))
            self.assertEqual(app["resume_reference"], next(item for item in json.loads(original_store.decode("utf-8"))["applications"] if item["application_id"] == AID).get("resume_reference"))
            self.assertEqual(app["resume_pdf_reference"], next(item for item in json.loads(original_store.decode("utf-8"))["applications"] if item["application_id"] == AID).get("resume_pdf_reference"))
            self.assertEqual(len(current_store["applications"]), len(json.loads(original_store.decode("utf-8"))["applications"]))

            report_path = root / app["working_resume_validation_reference"]
            sidecar_path = root / app["working_resume_revision_reference"]
            report = json.loads(report_path.read_text(encoding="utf-8"))
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            self.assertEqual(report["final_status"], "PASS")
            self.assertEqual(report["application_id"], AID)
            self.assertEqual(report["revision_id"], app["working_resume_revision_id"])
            self.assertEqual(sidecar["application_id"], AID)
            self.assertEqual(sidecar["revision_id"], app["working_resume_revision_id"])
            self.assertEqual(sidecar["document"]["revision_id"], app["working_resume_revision_id"])
            self.assertTrue(sidecar["change_ledger"])
            saved_text = " ".join(run["text"] for section in sidecar["document"]["content"]["sections"] for block in section["blocks"] for run in block.get("runs", []))
            self.assertIn("natural language", saved_text)
            for path, original_hash in protected.items():
                self.assertEqual(sha(path), original_hash, f"Previous/final artifact changed: {path.relative_to(root)}")

            reloaded = current_model()
            self.assertTrue(reloaded["persisted"])
            self.assertEqual(reloaded["document"]["revision_id"], result["working"]["revision_id"])
            self.assertIn("natural language", " ".join(r["text"] for section in reloaded["document"]["content"]["sections"] for block in section["blocks"] for r in block.get("runs", [])))

            guard = api.validate_working_revision_for_finalization(AID, app)
            self.assertEqual(guard.get("decision"), "ready", guard)
            stale = dict(app, resume_working_artifact_stale=True)
            self.assertEqual(api.validate_working_revision_for_finalization(AID, stale)["decision"], "stale_working")
            modified = dict(app, working_resume_pdf_sha256="0" * 64)
            self.assertEqual(api.validate_working_revision_for_finalization(AID, modified)["decision"], "artifact_modified")

            # Re-saving the unchanged active revision is idempotent and creates no files.
            files_before = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
            same = api.save_resume_document_payload(AID, {"base_revision_id": reloaded["document"]["revision_id"], "document": reloaded["document"]})
            self.assertEqual(same.get("decision"), "saved", same)
            self.assertTrue(same.get("idempotent"))
            files_after = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
            self.assertEqual(files_after, files_before)

    def test_expanded_edit_capabilities_render_and_validate_in_isolated_store(self):
        with isolated_real_rex_store(self) as (root, protected, original_store):
            loaded = current_model()
            document = json.loads(json.dumps(loaded["document"]))
            sections = {section["type"]: section for section in document["content"]["sections"]}

            summary = sections["professional_summary"]
            summary["title"] = "SUMMARY AND PROFILE"
            summary["formatting"].update({"space_before_pt": 1.0, "space_after_pt": 2.0})
            summary["blocks"][0]["runs"][0]["text"] = summary["blocks"][0]["runs"][0]["text"].replace("Computer Science", "computer science", 1)

            catalog_entry = next(item for item in loaded.get("skill_catalog", [])
                                 if item.get("group") == "Databases" and item.get("text") == "MySQL")
            database_group = next(block for block in sections["skills"]["blocks"]
                                  if block.get("type") == "skill_group" and block.get("label") == "Databases")
            database_group["items"].append({key: json.loads(json.dumps(value)) for key, value in catalog_entry.items() if key != "group"})
            database_group["source_refs"] = rdm._unique_refs(ref for item in database_group["items"] for ref in item["source_refs"])

            projects = sections["projects"]
            projects["title"] = "SELECTED PROJECTS"
            projects["formatting"].update({"space_before_pt": 2.0, "space_after_pt": 1.0})
            project_title = next(block for block in projects["blocks"] if block["type"] == "project_entry")
            project_title["runs"][0]["text"] = project_title["runs"][0]["text"].swapcase()
            project_title["formatting"].update({"space_before_pt": 2.0, "space_after_pt": 3.0})
            first_bullet = next(block for block in projects["blocks"]
                                if block["type"] == "project_bullet" and block["project_id"] == project_title["project_id"])
            first_bullet["runs"][0]["text"] = first_bullet["runs"][0]["text"].replace("natural-language", "natural language", 1)
            first_bullet["formatting"]["space_after_pt"] = 1.5

            education_line = next(block for block in sections["education"]["blocks"]
                                  if "CGPA:" in "".join(run["text"] for run in block.get("runs", [])))
            education_line["runs"][0]["text"] = education_line["runs"][0]["text"].replace("CGPA:", "CGPA", 1)
            education_line["formatting"]["font_size_pt"] = 11.0
            certification_entries = sections["certifications"]["blocks"]
            certification_texts = []
            if certification_entries:
                certification_entry = certification_entries[0]
                certification_entry["runs"][0]["text"] = certification_entry["runs"][0]["text"].swapcase()
                certification_texts.append(certification_entry["runs"][0]["text"])
            document["source_references"] = rdm._collect_refs(document["content"])

            saved = api.save_resume_document_payload(AID, {
                "base_revision_id": loaded["document"]["revision_id"],
                "document": document,
            })
            self.assertEqual(saved.get("decision"), "saved", saved)
            self.assertEqual(saved["validation"]["final_status"], "PASS")
            self.assertEqual(saved["validation"]["page_count"], 1)
            self.assertTrue(all(saved["validation"]["checks"].values()), saved["validation"]["checks"])

            app = api.get_application(AID)
            docx_path, pdf_path = root / app["working_resume_docx_path"], root / app["working_resume_pdf_path"]
            self.assertTrue(docx_path.is_file() and pdf_path.is_file())
            from docx import Document
            docx_text = "\n".join(paragraph.text for paragraph in Document(str(docx_path)).paragraphs)
            pdf_extract = subprocess.run([rg.resolve_executable("pdftotext"), str(pdf_path), "-"],
                                          check=True, capture_output=True, encoding="utf-8").stdout
            for text in ("MySQL", "SELECTED PROJECTS", project_title["runs"][0]["text"],
                         "Computer Science", "natural language", "CGPA", *certification_texts):
                self.assertIn(text.casefold(), docx_text.casefold())
                self.assertIn(text.casefold(), pdf_extract.casefold())
            validation_report = json.loads((root / app["working_resume_validation_reference"]).read_text(encoding="utf-8"))
            self.assertTrue(validation_report["ats_validation"]["text_extractable"])
            self.assertTrue(validation_report["checks"]["truth_provenance"])
            self.assertEqual(validation_report["page_count"], 1)
            self.assertEqual(len(json.loads((root / "data" / "applications.json").read_text(encoding="utf-8"))["applications"]),
                             len(json.loads(original_store.decode("utf-8"))["applications"]))
            for path, original_hash in protected.items():
                self.assertEqual(sha(path), original_hash, f"Previous/final artifact changed: {path.relative_to(root)}")

    def test_unsupported_claim_and_stale_base_fail_without_mutation(self):
        with isolated_real_rex_store(self) as (root, protected, original_store):
            loaded = current_model()
            document = supported_copyedit(loaded["document"])
            result = api.save_resume_document_payload(AID, {"base_revision_id": loaded["document"]["revision_id"], "document": document})
            self.assertEqual(result.get("decision"), "saved", result)
            app = api.get_application(AID)
            current = current_model()
            active_before = active_refs(app)
            hashes_before = {path.relative_to(root).as_posix(): sha(path) for path in root.rglob("*") if path.is_file()}
            store_before = (root / "data" / "applications.json").read_bytes()

            invalid = json.loads(json.dumps(current["document"]))
            bullet = next(block for section in invalid["content"]["sections"] for block in section["blocks"] if block.get("type") == "project_bullet")
            bullet["runs"][0]["text"] += " with 10000 enterprise clients"
            rejected = api.save_resume_document_payload(AID, {"base_revision_id": current["document"]["revision_id"], "document": invalid})
            self.assertEqual(rejected.get("decision"), "validation_failed", rejected)
            self.assertTrue(rejected.get("previous_working_preserved"))
            self.assertTrue(rejected.get("errors"))
            self.assertEqual((root / "data" / "applications.json").read_bytes(), store_before)
            self.assertEqual(active_refs(api.get_application(AID)), active_before)
            hashes_after = {path.relative_to(root).as_posix(): sha(path) for path in root.rglob("*") if path.is_file()}
            self.assertEqual(hashes_after, hashes_before)

            stale = api.save_resume_document_payload(AID, {"base_revision_id": "rev_000000000000000000000000", "document": current["document"]})
            self.assertEqual(stale.get("decision"), "stale_revision")
            self.assertEqual((root / "data" / "applications.json").read_bytes(), store_before)

    def test_renderer_failure_rolls_back_and_preserves_previous_working_and_final(self):
        with isolated_real_rex_store(self) as (root, protected, original_store):
            loaded = current_model()
            doc = supported_copyedit(loaded["document"])
            before_store = (root / "data" / "applications.json").read_bytes()
            before_files = {path.relative_to(root).as_posix(): sha(path) for path in root.rglob("*") if path.is_file()}
            with patch.object(renderer, "render_resume_document", side_effect=RuntimeError("simulated renderer failure")):
                result = api.save_resume_document_payload(AID, {"base_revision_id": loaded["document"]["revision_id"], "document": doc})
            self.assertEqual(result.get("decision"), "error")
            self.assertTrue(result.get("previous_working_preserved"))
            self.assertEqual((root / "data" / "applications.json").read_bytes(), before_store)
            after_files = {path.relative_to(root).as_posix(): sha(path) for path in root.rglob("*") if path.is_file()}
            self.assertEqual(after_files, before_files)
            for path, original_hash in protected.items():
                self.assertEqual(sha(path), original_hash)

    def test_finalization_api_blocks_stale_working_without_creating_final_artifact(self):
        with isolated_real_rex_store(self) as (root, protected, original_store):
            loaded = current_model()
            saved = api.save_resume_document_payload(AID, {"base_revision_id": loaded["document"]["revision_id"], "document": supported_copyedit(loaded["document"])})
            self.assertEqual(saved.get("decision"), "saved", saved)
            store_path = root / "data" / "applications.json"
            store = json.loads(store_path.read_text(encoding="utf-8"))
            app = next(item for item in store["applications"] if item["application_id"] == AID)
            final_docx_ref, final_pdf_ref = app.get("resume_docx_path"), app.get("resume_pdf_path")
            final_hashes = {ref: sha(root / ref) for ref in [final_docx_ref, final_pdf_ref] if ref and (root / ref).is_file()}
            app["resume_working_artifact_stale"] = True
            store_path.write_text(json.dumps(store, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            blocked = api.finalize_resume(AID)
            self.assertEqual(blocked.get("decision"), "stale_working", blocked)
            self.assertEqual({ref: sha(root / ref) for ref in final_hashes}, final_hashes)
            self.assertEqual(active_refs(api.get_application(AID)), (saved["working"]["docx_reference"], saved["working"]["pdf_reference"]))
            self.assertEqual(len(list((root / "output" / "resumes").glob("*_Final*.docx"))), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
