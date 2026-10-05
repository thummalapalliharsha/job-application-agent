#!/usr/bin/env python3
"""Isolated DOCX/PDF rendering regressions for the additive Phase 3C.3 renderer."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import career_os_api as api
import resume_document_model as rdm
import resume_document_renderer as renderer
import resume_generator as rg

AID = "app_14a66f897623"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


class ResumeDocumentRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = api.get_application(AID)
        if not cls.app:
            raise RuntimeError(f"Existing Rex.zone application not found: {AID}")
        cls.profile = rg.profile()
        cls.plan_path = api.resolve_ref(cls.app["phase8_plan_reference"])
        cls.plan = json.loads(cls.plan_path.read_text(encoding="utf-8"))
        cls.document = rdm.build_resume_document(cls.app, cls.plan, cls.profile)
        protected = [
            ROOT / "resume_generator.py",
            ROOT / "templates" / "ats_resume_template.docx",
            ROOT / "data" / "applications.json",
            ROOT / "data" / "master_profile.json",
            ROOT / "data" / "skills.json",
            ROOT / "data" / "projects.json",
            ROOT / "data" / "experience.json",
            ROOT / "data" / "education.json",
            ROOT / "data" / "certifications.json",
            ROOT / "data" / "achievements.json",
            ROOT / cls.app["working_resume_docx_path"],
            ROOT / cls.app["working_resume_pdf_path"],
            ROOT / cls.app["resume_docx_path"],
            ROOT / cls.app["resume_pdf_path"],
            ROOT / cls.app["cover_letter_reference"],
        ]
        cls.protected_hashes = {path: sha(path) for path in protected if path.is_file()}

    def test_real_rex_zone_model_renders_one_page_ats_docx_and_pdf_in_temp(self):
        with tempfile.TemporaryDirectory(prefix="resume-document-render-") as temp:
            directory = Path(temp)
            docx = directory / "candidate.docx"
            pdf = directory / "candidate.pdf"
            result = renderer.render_resume_document(
                self.document, self.app, self.plan, self.profile,
                docx, pdf, directory / "conversion",
            )
            self.assertTrue(docx.is_file() and docx.stat().st_size > 0)
            self.assertTrue(pdf.is_file() and pdf.stat().st_size > 0)
            self.assertEqual(result["page_count"], 1)
            self.assertTrue(result["extracted_text"].strip())

            report = rg.validate(docx, self.plan, self.profile, directory / "validation.json")
            self.assertEqual(report["final_status"], "PASS", report)
            self.assertEqual(report["page_count"], 1)
            self.assertTrue(report["contact_validation"]["passed"])
            self.assertTrue(report["hyperlink_validation"]["passed"])
            self.assertTrue(report["project_link_validation"]["passed"])
            self.assertTrue(report["project_order_validation"]["passed"])
            self.assertTrue(report["placeholder_validation"]["passed"])
            self.assertTrue(report["ats_validation"]["text_extractable"])

            actual = normalize(result["extracted_text"])
            missing = [paragraph for paragraph in rdm.resume_document_paragraphs(self.document)
                       if normalize(paragraph) not in actual]
            self.assertEqual(missing, [], f"Model text missing from rendered PDF: {missing}")

            with zipfile.ZipFile(docx) as package:
                xml = package.read("word/document.xml").decode("utf-8")
                relationships = package.read("word/_rels/document.xml.rels").decode("utf-8")
            self.assertNotIn("<w:tbl", xml)
            self.assertNotIn("<w:txbxContent", xml)
            self.assertNotIn("<wp:anchor", xml)
            self.assertNotIn("<w:drawing", xml)
            self.assertNotIn("/image", relationships)
            targets = rg.hyperlink_targets(docx)
            self.assertTrue(any("linkedin.com" in target for target in targets))
            self.assertTrue(any("github.com" in target for target in targets))
            self.assertTrue(any(target.startswith("mailto:") for target in targets))
            self.assertTrue(any(target.startswith("tel:") for target in targets))
            self.assertTrue(any("text_to_sql_project" in target for target in targets))

    def test_render_rejects_model_bound_to_another_application(self):
        wrong_application = dict(self.app, application_id="app_000000000000")
        with tempfile.TemporaryDirectory(prefix="resume-document-reject-") as temp:
            directory = Path(temp)
            with self.assertRaises(rdm.ResumeDocumentValidationError):
                renderer.render_resume_document(
                    self.document, wrong_application, self.plan, self.profile,
                    directory / "candidate.docx", directory / "candidate.pdf", directory / "convert",
                )
            self.assertFalse((directory / "candidate.docx").exists())
            self.assertFalse((directory / "candidate.pdf").exists())

    def test_real_application_data_and_protected_artifacts_are_unchanged(self):
        for path, original_hash in self.protected_hashes.items():
            self.assertEqual(sha(path), original_hash, f"Protected file changed: {path.relative_to(ROOT)}")
        self.assertEqual(api.get_application(AID)["company_name"], "Rex.zone")


if __name__ == "__main__":
    unittest.main(verbosity=2)
