#!/usr/bin/env python3
"""Read-only API checks for the Phase 3C.2 ResumeDocument editor boundary."""
from __future__ import annotations

import copy
import hashlib
import unittest

import career_os_api as api
import resume_document_model as rdm

AID = "app_14a66f897623"


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


class ResumeDocumentEditorApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = api.get_application(AID)
        if not cls.app:
            raise RuntimeError(f"Required existing application not found: {AID}")
        cls.store_path = api.ROOT / "data" / "applications.json"
        cls.protected_files = {cls.store_path: file_digest(cls.store_path)}
        for key in ("working_resume_docx_path", "working_resume_pdf_path", "resume_reference", "resume_pdf_reference"):
            reference = cls.app.get(key)
            if reference:
                path = api.resolve_ref(reference).resolve()
                try:
                    path.relative_to(api.ROOT.resolve())
                except ValueError:
                    continue
                if path.is_file():
                    cls.protected_files[path] = file_digest(path)

    def document(self):
        result = api.resume_document_payload(AID)
        self.assertEqual(result.get("decision"), "ready", result)
        self.assertEqual(result.get("company_name"), "Rex.zone")
        self.assertEqual(result["document"]["application_id"], AID)
        return result["document"]

    def validate(self, document):
        return api.validate_resume_document_payload(AID, {"document": document})

    def test_get_builds_selected_rex_zone_document_without_creating_an_application(self):
        result = api.resume_document_payload(AID)
        self.assertEqual(result["decision"], "ready")
        self.assertEqual(result["application_id"], AID)
        self.assertEqual(result["company_name"], "Rex.zone")
        self.assertEqual(result["document"]["schema_version"], 1)
        self.assertTrue(result["document"]["source_generation_reference"])

    def test_unchanged_document_validates_and_is_explicitly_not_persisted(self):
        result = self.validate(self.document())
        self.assertEqual(result["decision"], "valid", result)
        self.assertTrue(result["valid"])
        self.assertIs(result["persisted"], False)
        self.assertEqual(result["validation"]["application_id"], AID)

    def test_source_backed_text_rewrite_is_accepted_with_original_provenance(self):
        document = self.document()
        section = next(section for section in document["content"]["sections"] if section["type"] == "projects")
        block = next(block for block in section["blocks"]
                     if block.get("type") == "project_bullet"
                     and "natural-language" in "".join(run.get("text", "") for run in block.get("runs", []))
                     or block.get("type") == "project_bullet"
                     and "natural language" in "".join(run.get("text", "") for run in block.get("runs", [])))
        block_id = block["id"]
        original_refs = copy.deepcopy(block["source_refs"])
        original_text = "".join(run.get("text", "") for run in block.get("runs", []))
        replacement = "natural language" if "natural-language" in original_text else "natural-language"
        search = "natural-language" if "natural-language" in original_text else "natural language"
        block["runs"][0]["text"] = block["runs"][0]["text"].replace(search, replacement, 1)
        result = self.validate(document)
        self.assertEqual(result["decision"], "valid", result)
        rewritten_section = next(section for section in result["document"]["content"]["sections"] if section["type"] == "projects")
        rewritten = next(block for block in rewritten_section["blocks"] if block["id"] == block_id)
        self.assertEqual(rewritten["source_refs"], original_refs)
        self.assertEqual(rewritten["runs"][0]["source_refs"], original_refs)
        self.assertIn(replacement, rewritten["runs"][0]["text"])

    def test_supported_project_bullet_reordering_is_accepted(self):
        document = self.document()
        section = next(section for section in document["content"]["sections"] if section["type"] == "projects")
        bullets = [i for i, block in enumerate(section["blocks"]) if block["type"] == "project_bullet" and block["project_id"] == section["blocks"][0]["project_id"]]
        self.assertGreaterEqual(len(bullets), 2)
        section["blocks"][bullets[0]], section["blocks"][bullets[1]] = section["blocks"][bullets[1]], section["blocks"][bullets[0]]
        result = self.validate(document)
        self.assertEqual(result["decision"], "valid", result)

    def test_removing_an_existing_source_backed_project_bullet_is_accepted(self):
        document = self.document()
        section = next(section for section in document["content"]["sections"] if section["type"] == "projects")
        index = next(i for i, block in enumerate(section["blocks"]) if block["type"] == "project_bullet")
        section["blocks"].pop(index)
        document["source_references"] = rdm._collect_refs(document["content"])
        result = self.validate(document)
        self.assertEqual(result["decision"], "valid", result)

    def test_canonical_project_link_on_its_source_backed_bullet_is_accepted(self):
        document = self.document()
        section = next(section for section in document["content"]["sections"] if section["type"] == "projects")
        bullet = next(block for block in section["blocks"] if block["type"] == "project_bullet")
        link_block = next(block for block in section["blocks"] if block["type"] == "project_link" and block["project_id"] == bullet["project_id"])
        href = next(mark["href"] for run in link_block["runs"] for mark in run["marks"] if mark["type"] == "link")
        bullet["runs"][0]["marks"] = [{"type": "link", "href": href}]
        result = self.validate(document)
        self.assertEqual(result["decision"], "valid", result)

    def test_new_stable_block_identity_cannot_add_an_unmodeled_fact(self):
        document = self.document()
        section = next(section for section in document["content"]["sections"] if section["type"] == "projects")
        index = next(i for i, block in enumerate(section["blocks"]) if block["type"] == "project_bullet")
        added = copy.deepcopy(section["blocks"][index])
        added["id"] = "blk_ffffffffffffffff"
        section["blocks"].insert(index + 1, added)
        result = self.validate(document)
        self.assertEqual(result["decision"], "invalid")

    def test_supported_formatting_presets_are_accepted(self):
        document = self.document()
        section = next(section for section in document["content"]["sections"] if section["type"] == "projects")
        bullet = next(block for block in section["blocks"] if block["type"] == "project_bullet")
        bullet["formatting"].update({"font_size_pt": 12.0, "line_spacing": 1.1, "alignment": "center", "list_style": "ordered"})
        result = self.validate(document)
        self.assertEqual(result["decision"], "valid", result)

    def test_expanded_source_backed_fields_skills_reordering_headings_and_spacing_validate(self):
        loaded = api.resume_document_payload(AID)
        document = copy.deepcopy(loaded["document"])
        sections = {section["type"]: section for section in document["content"]["sections"]}

        summary = sections["professional_summary"]
        summary["title"] = "SUMMARY AND PROFILE"
        summary["formatting"].update({"space_before_pt": 1.5, "space_after_pt": 2.0})
        summary["blocks"][0]["formatting"]["font_size_pt"] = 10.0
        summary["blocks"][0]["runs"][0]["text"] = summary["blocks"][0]["runs"][0]["text"].replace("Artificial Intelligence", "artificial intelligence", 1)

        projects = sections["projects"]
        projects["title"] = "SELECTED PROJECTS"
        projects["formatting"].update({"space_before_pt": 2.0, "space_after_pt": 1.5})
        project_entries = [block for block in projects["blocks"] if block["type"] == "project_entry"]
        project_entries[0]["runs"][0]["text"] = project_entries[0]["runs"][0]["text"].swapcase()
        project_entries[0]["formatting"].update({"space_before_pt": 2.0, "space_after_pt": 3.0})
        project_bullets = [block for block in projects["blocks"] if block["type"] == "project_bullet" and block["project_id"] == project_entries[0]["project_id"]]
        project_bullets[0]["formatting"]["space_after_pt"] = 1.5
        project_bullets[1]["formatting"]["space_before_pt"] = 0.5

        catalog = loaded.get("skill_catalog", [])
        mysql = next((item for item in catalog if item["group"] == "Databases" and item["text"] == "MySQL"), None)
        self.assertIsNotNone(mysql, "MySQL must be offered only when canonical evidence exists")
        databases = next(block for block in sections["skills"]["blocks"] if block["type"] == "skill_group" and block["label"] == "Databases")
        databases["items"].append({key: copy.deepcopy(value) for key, value in mysql.items() if key != "group"})
        databases["items"][0]["text"] = databases["items"][0]["text"].swapcase()
        databases["items"].reverse()
        databases["source_refs"] = rdm._unique_refs(ref for item in databases["items"] for ref in item["source_refs"])

        education = sections["education"]
        education_ids = list(dict.fromkeys(block["education_id"] for block in education["blocks"]))
        education["blocks"] = [block for record_id in reversed(education_ids) for block in education["blocks"] if block["education_id"] == record_id]
        cgpa_line = next(block for block in education["blocks"] if "CGPA:" in "".join(run["text"] for run in block["runs"]))
        cgpa_line["runs"][0]["text"] = cgpa_line["runs"][0]["text"].replace("CGPA:", "CGPA", 1)
        cgpa_line["formatting"].update({"font_size_pt": 10.0, "line_spacing": 1.1})

        certifications = sections["certifications"]
        certifications["blocks"].reverse()
        certifications["blocks"][0]["runs"][0]["text"] = certifications["blocks"][0]["runs"][0]["text"].swapcase()

        # Add a supported duplicate wording as a new, stable-index bullet; source and
        # parent identity remain exactly those of the canonical selected project.
        source_bullet = project_bullets[-1]
        new_bullet = copy.deepcopy(source_bullet)
        new_bullet["id"] = "blk_ffffffffffffffff"
        new_bullet["bullet_index"] = next(index for index in range(5) if index not in {block["bullet_index"] for block in project_bullets})
        new_bullet["runs"] = [{"text": project_entries[0]["runs"][0]["text"], "marks": [], "source_refs": copy.deepcopy(new_bullet["source_refs"])}]
        insert_at = projects["blocks"].index(source_bullet) + 1
        projects["blocks"].insert(insert_at, new_bullet)
        document["source_references"] = rdm._collect_refs(document["content"])

        result = self.validate(document)
        self.assertEqual(result["decision"], "valid", result)
        self.assertTrue(result["valid"])
        self.assertFalse(result["persisted"])

        unsupported = copy.deepcopy(result["document"])
        project_title = next(block for section in unsupported["content"]["sections"] for block in section["blocks"] if block["type"] == "project_entry")
        project_title["runs"][0]["text"] += " InventedPlatform"
        rejected = self.validate(unsupported)
        self.assertEqual(rejected["decision"], "invalid")
        self.assertTrue(any(error["code"] == "unsupported_vocabulary" for error in rejected.get("claim_validation", {}).get("errors", [])))

        unsafe_spacing = copy.deepcopy(result["document"])
        unsafe_spacing["content"]["sections"][0]["formatting"]["space_after_pt"] = 7.0
        self.assertEqual(self.validate(unsafe_spacing)["decision"], "invalid")

    def test_protected_contact_data_cannot_be_edited(self):
        document = self.document()
        header = next(section for section in document["content"]["sections"] if section["type"] == "contact_header")
        header["blocks"][0]["runs"][0]["text"] = "CHANGED CONTACT NAME"
        result = self.validate(document)
        self.assertEqual(result["decision"], "invalid")
        self.assertFalse(result["valid"])

    def test_untrusted_hyperlink_is_rejected(self):
        document = self.document()
        summary = next(section for section in document["content"]["sections"] if section["type"] == "professional_summary")["blocks"][0]
        summary["runs"][0]["marks"] = [{"type": "link", "href": "javascript:alert(1)"}]
        result = self.validate(document)
        self.assertEqual(result["decision"], "invalid")

    def test_unsupported_block_identity_and_formatting_are_rejected(self):
        document = self.document()
        project = next(section for section in document["content"]["sections"] if section["type"] == "projects")
        bullet = next(block for block in project["blocks"] if block["type"] == "project_bullet")
        bullet["formatting"]["font_size_pt"] = 14.0
        result = self.validate(document)
        self.assertEqual(result["decision"], "invalid")

    def test_unknown_application_is_not_created(self):
        result = api.resume_document_payload("app_000000000000")
        self.assertEqual(result, {"decision": "not_found"})
        validation = api.validate_resume_document_payload("app_000000000000", {"document": {}})
        self.assertEqual(validation, {"decision": "not_found"})

    @classmethod
    def tearDownClass(cls):
        for path, before in cls.protected_files.items():
            if file_digest(path) != before:
                raise AssertionError(f"Read-only editor API changed protected data/artifact: {path}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
