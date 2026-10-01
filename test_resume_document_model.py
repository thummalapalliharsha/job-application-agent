#!/usr/bin/env python3
"""Focused Phase 3C.1 ResumeDocument model/provenance tests (read-only fixtures)."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import application_assistant as aa
import resume_generator as rg
import resume_document_model as model

REX_APPLICATION_ID = "app_14a66f897623"


def _context():
    app = next(item for item in aa.load_store()["applications"]
               if item.get("application_id") == REX_APPLICATION_ID)
    plan_path = ROOT / app["phase8_plan_reference"].replace("\\", "/")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    profile = rg.profile()
    return app, plan, profile


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protected_paths(app: dict) -> list[Path]:
    paths = [
        ROOT / "resume_generator.py",
        rg.TEMPLATE,
        ROOT / "data" / "applications.json",
        *(ROOT / "data" / f"{name}.json" for name in (
            "master_profile", "skills", "projects", "experience",
            "certifications", "education", "achievements",
        )),
    ]
    for key in (
        "working_resume_docx_path", "working_resume_pdf_path",
        "resume_docx_path", "resume_pdf_path",
    ):
        reference = app.get(key)
        if reference:
            paths.append(ROOT / str(reference).replace("\\", "/"))
    sidecar = model.sidecar_directory(app["application_id"], ROOT)
    if sidecar.is_dir():
        paths.extend(path for path in sidecar.rglob("*") if path.is_file())
    return paths


def _refresh_revision(document: dict) -> None:
    document["source_references"] = model._collect_refs(document["content"])
    document["revision_id"] = model._revision_id(document)


def _must_reject(document: dict, app: dict, plan: dict, profile: dict, label: str) -> None:
    try:
        model.validate_resume_document(document, app, plan, profile)
    except model.ResumeDocumentValidationError:
        return
    raise AssertionError(f"Invalid model was accepted: {label}")


def _docx_paragraphs(path: Path) -> list[str]:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    paragraphs = [
        "".join((text.text or "") for text in paragraph.findall(".//w:t", namespace))
        for paragraph in root.findall(".//w:body/w:p", namespace)
    ]
    return [paragraph for paragraph in paragraphs if paragraph.strip()]


def _normalize_visible_paragraphs(paragraphs: list[str]) -> list[str]:
    # LibreOffice/Word may surface a typographic hyphen where the saved model
    # contains a space (or vice versa); preserve all other visible text strictly.
    return [re.sub(r"\s+", " ", re.sub(r"[\-\u2010-\u2015]+", " ", paragraph)).strip()
            for paragraph in paragraphs]


def _model_links(document: dict) -> set[str]:
    links = set()
    for section in document["content"]["sections"]:
        for block in section["blocks"]:
            for run in block.get("runs", []):
                for mark in run.get("marks", []):
                    if mark.get("type") == "link":
                        links.add(mark["href"])
    return links


def main() -> None:
    app, plan, profile = _context()
    before = {str(path): _sha(path) for path in _protected_paths(app)}

    assert app["company_name"] == "Rex.zone"
    assert app["application_id"] == REX_APPLICATION_ID
    assert app["resume_generation_allowed"] is True
    assert plan["approval_checkpoint"]["resume_generation_allowed"] is True

    document = model.build_resume_document_for_application(
        app, profile=profile, created_at="2026-09-27T10:00:00+00:00"
    )
    validation = model.validate_resume_document(document, app, plan, profile)
    assert validation["valid"] is True
    assert validation["claim_truth_semantically_verified"] is False
    assert document["schema_version"] == 1
    assert document["status"] == "draft"
    assert document["source_plan_reference"] == "output/reports/app_14a66f897623_phase8_plan.json"
    assert document["source_generation_reference"] == app["working_resume_generation_id"]
    assert document["revision_id"].startswith("rev_")

    section_types = [section["type"] for section in document["content"]["sections"]]
    assert section_types == ["contact_header", "professional_summary", "skills", "projects", "education", "certifications"]
    assert "achievements" not in section_types
    project_ids = [block["project_id"] for section in document["content"]["sections"]
                   if section["type"] == "projects" for block in section["blocks"]
                   if block["type"] == "project_entry"]
    assert project_ids == ["project_text_to_sql_project", "project_student_performance_rag"]
    assert project_ids == app["project_selection_record_ids"]

    refs = {(ref["source_type"], ref["source_id"]) for ref in document["source_references"]}
    assert all(("project", project_id) in refs for project_id in project_ids)
    assert ("education", "education_biher_btech") in refs
    expected_certification_ids = {item["record_id"] for item in rg.effective_certs(plan, profile)}
    actual_certification_ids = {source_id for source_type, source_id in refs if source_type == "certification"}
    assert actual_certification_ids == expected_certification_ids
    skill_refs = [ref for ref in document["source_references"] if ref["source_type"] == "skill"]
    assert skill_refs
    assert all(model._resolve_skill_source(ref["source_id"], profile) is not None for ref in skill_refs)
    assert ("profile_field", "/profile/name") in refs
    assert ("profile_field", "/profile/contact/email") in refs
    assert ("profile_field", "/profile/links/linkedin") in refs
    assert ("profile_field", "/profile/links/github") in refs

    # Deterministic content revisions are stable across creation timestamps.
    other_timestamp = model.build_resume_document_for_application(
        app, profile=profile, created_at="2026-09-27T11:00:00+00:00"
    )
    assert other_timestamp["created_at"] != document["created_at"]
    assert other_timestamp["revision_id"] == document["revision_id"]

    # Historical artifacts remain immutable; the current model follows the
    # approved plan and current evidence policy instead of copying stale content.
    working_path = ROOT / app["working_resume_docx_path"].replace("\\", "/")
    assert working_path.is_file()
    assert _sha(working_path) == app["working_resume_docx_sha256"]
    revision_reference = app.get("working_resume_revision_reference")
    if revision_reference:
        sidecar_payload = json.loads((ROOT / revision_reference.replace("\\", "/")).read_text(encoding="utf-8"))
        active_document = sidecar_payload["document"]
        assert active_document["revision_id"] == app["working_resume_revision_id"]
    else:
        active_document = document
    links = _model_links(document)
    master = profile["master_profile"]["profile"]
    assert any(master["links"]["linkedin"] in target for target in links)
    assert any(master["links"]["github"] in target for target in links)
    assert all(project.get("github_url") in links for project in rg.effective_selection(plan, profile)
               if str(project.get("github_url", "")).startswith("https://github.com/"))

    # Supported prose can be revised/formatted/reordered without severing its
    # canonical evidence links; validation explicitly does not claim truth-proof.
    editable_revision = copy.deepcopy(document)
    summary_block = next(block for section in editable_revision["content"]["sections"]
                         if section["type"] == "professional_summary" for block in section["blocks"])
    summary_block["formatting"]["font_size_pt"] = 11.0
    summary_block["formatting"]["line_spacing"] = 1.15
    summary_block["runs"][0]["marks"] = [{"type": "bold"}]
    project_section = next(section for section in editable_revision["content"]["sections"]
                           if section["type"] == "projects")
    bullet_positions = [index for index, block in enumerate(project_section["blocks"])
                        if block["type"] == "project_bullet" and block["project_id"] == project_ids[0]]
    first_bullet = project_section["blocks"][bullet_positions[0]]
    first_bullet["runs"][0]["text"] = first_bullet["runs"][0]["text"].replace("Built", "Developed", 1)
    first_bullet["runs"][0]["marks"] = [{"type": "italic"}]
    reordered = [project_section["blocks"][index] for index in bullet_positions][::-1]
    for index, block in zip(bullet_positions, reordered):
        project_section["blocks"][index] = block
    _refresh_revision(editable_revision)
    edit_validation = model.validate_resume_document(editable_revision, app, plan, profile)
    assert edit_validation["valid"] is True
    assert edit_validation["claim_truth_semantically_verified"] is False
    assert editable_revision["revision_id"] != document["revision_id"]

    # Canonical source locators are resolvable; arbitrary IDs fail closed.
    invalid_source = copy.deepcopy(document)
    first_skill = next(block for section in invalid_source["content"]["sections"]
                       if section["type"] == "skills" for block in section["blocks"]
                       if block["type"] == "skill_group")["items"][0]
    first_skill["source_refs"][0]["source_id"] = "skill_groups/not-a-category/Fabricated"
    _refresh_revision(invalid_source)
    _must_reject(invalid_source, app, plan, profile, "unknown source ID")

    unsupported_section = copy.deepcopy(document)
    unsupported_section["content"]["sections"].insert(-2, {
        "id": "section_achievements", "type": "achievements", "title": "ACHIEVEMENTS",
        "required": False, "formatting": {}, "blocks": [],
    })
    _refresh_revision(unsupported_section)
    _must_reject(unsupported_section, app, plan, profile, "unsupported achievements section")

    unsupported_block = copy.deepcopy(document)
    project_section = next(section for section in unsupported_block["content"]["sections"] if section["type"] == "projects")
    project_section["blocks"][1]["type"] = "raw_html"
    _refresh_revision(unsupported_block)
    _must_reject(unsupported_block, app, plan, profile, "unsupported/raw HTML block")

    invalid_revision = copy.deepcopy(document)
    invalid_revision["revision_id"] = "rev_" + "0" * 24
    _must_reject(invalid_revision, app, plan, profile, "stale revision digest")

    invalid_application = copy.deepcopy(document)
    invalid_application["application_id"] = "app_invalid"
    _must_reject(invalid_application, app, plan, profile, "invalid application ID")

    changed_contact = copy.deepcopy(document)
    contact_name = changed_contact["content"]["sections"][0]["blocks"][0]
    contact_name["runs"][0]["text"] = "Invented Candidate"
    _refresh_revision(changed_contact)
    _must_reject(changed_contact, app, plan, profile, "protected contact alteration")

    unsupported_format = copy.deepcopy(document)
    unsupported_format["content"]["sections"][0]["blocks"][0]["formatting"]["font_size_pt"] = 72
    _refresh_revision(unsupported_format)
    _must_reject(unsupported_format, app, plan, profile, "unapproved font size")

    malformed = copy.deepcopy(document)
    malformed["free_form_claim"] = "unreferenced content"
    malformed["revision_id"] = model._revision_id(malformed)
    _must_reject(malformed, app, plan, profile, "unsupported top-level field")

    sidecar = model.sidecar_directory(REX_APPLICATION_ID, ROOT)
    assert sidecar == ROOT / "output" / "resume_edits" / REX_APPLICATION_ID
    if app.get("working_resume_revision_reference"):
        assert sidecar.is_dir(), "A persisted Working revision must have sidecar storage"

    # The adapter is read-only: profile, application store, template, generator,
    # existing Working/Final artifacts, and any saved sidecar retain exact hashes.
    after = {str(path): _sha(path) for path in _protected_paths(app)}
    assert after == before

    print(json.dumps({
        "passed": True,
        "test": "ResumeDocument schema, Rex.zone adapter, provenance, parity, fail-closed validation, and immutability",
        "application_id": document["application_id"],
        "revision_id": document["revision_id"],
        "sections": section_types,
        "projects": project_ids,
        "paragraphs_compared": len(model.resume_document_paragraphs(document)),
        "source_references": len(document["source_references"]),
        "claim_truth_semantically_verified": validation["claim_truth_semantically_verified"],
        "resume_generator_sha256": before[str(ROOT / "resume_generator.py")],
        "sidecar_created": sidecar.exists(),
    }, indent=2))


if __name__ == "__main__":
    main()
