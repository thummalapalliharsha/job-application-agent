"""Versioned, evidence-linked ResumeDocument foundation (Phase 3C.1).

This module is intentionally model/adapter/validation only. It does not edit the
Resume Workspace UI, render DOCX/PDF, write sidecars, or mutate source records.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import quote, unquote, urlsplit

import resume_generator as rg

SCHEMA_VERSION = 1
APPLICATION_ID_RE = re.compile(r"^app_[0-9a-f]{12}$")
GENERATION_ID_RE = re.compile(r"^gen_[0-9a-f]{32}$")
REVISION_ID_RE = re.compile(r"^rev_[0-9a-f]{24}$")
BLOCK_ID_RE = re.compile(r"^blk_[0-9a-f]{16}$")
REVISION_STATUSES = frozenset({"draft", "validated", "working", "stale", "finalized"})
SIDECAR_STORAGE_TEMPLATE = "output/resume_edits/{application_id}/"

# Current resume_generator.py renders these sections. Achievements are deliberately
# disabled: the canonical file is empty and the frozen generator has no rule for it.
SECTION_TITLES = {
    "contact_header": None,
    "professional_summary": "PROFESSIONAL SUMMARY",
    "skills": "SKILLS",
    "projects": "PROJECTS",
    "experience": "EXPERIENCE",
    "education": "EDUCATION",
    "certifications": "CERTIFICATIONS",
}
REQUIRED_SECTIONS = frozenset({
    "contact_header", "professional_summary", "skills", "projects",
    "education", "certifications",
})
OPTIONAL_SECTIONS = frozenset({"experience"})
DISABLED_SECTIONS = {"achievements": "No current resume_generator.py rule; canonical achievements are empty."}
SUPPORTED_SECTION_TYPES = tuple(SECTION_TITLES)

BLOCK_TYPES_BY_SECTION = {
    "contact_header": frozenset({"contact_name", "contact_details", "profile_links"}),
    "professional_summary": frozenset({"summary_paragraph"}),
    "skills": frozenset({"skill_group"}),
    "projects": frozenset({"project_entry", "project_bullet", "project_tech_stack", "project_link", "layout_paragraph"}),
    "experience": frozenset({"experience_entry", "experience_bullet"}),
    "education": frozenset({"education_line"}),
    "certifications": frozenset({"certification_entry"}),
}
BLOCK_POLICIES = {
    "contact_name": "protected",
    "contact_details": "protected",
    "profile_links": "protected",
    "summary_paragraph": "editable_source_backed",
    "skill_group": "source_backed_read_only",
    "project_entry": "editable_source_backed",
    "project_bullet": "editable_source_backed",
    "project_tech_stack": "source_backed_read_only",
    "project_link": "protected",
    "layout_paragraph": "presentation",
    "experience_entry": "editable_source_backed",
    "experience_bullet": "editable_source_backed",
    "education_line": "editable_source_backed",
    "certification_entry": "editable_source_backed",
}
EDITABLE_TEXT_BLOCK_TYPES = frozenset({
    "summary_paragraph", "project_entry", "project_bullet",
    "experience_entry", "experience_bullet", "education_line", "certification_entry",
})
ADDITIVE_BULLET_TYPES = frozenset({"project_bullet", "experience_bullet"})
FIELD_POLICY_CATEGORIES = {
    "protected": "Canonical fact; future editor may format only, not change its value.",
    "editable_source_backed": "Text may be rewritten only while retaining its canonical source references.",
    "source_backed_read_only": "Value must remain the canonical selected value; selection/order is not free-form.",
    "unsupported": "Not allowed in ResumeDocument v1; includes unsupported sections and free-form facts.",
}

# Exact section/group ordering and skill names used by the frozen generator.
SKILL_GROUPS = {
    "Programming": ("Python", "SQL", "JavaScript"),
    "Web / Frontend": ("HTML", "CSS"),
    "Libraries / Frameworks": ("Pandas", "NumPy", "Scikit-learn", "Streamlit"),
    "AI / Machine Learning": ("RAG", "Embeddings", "Generative AI", "Ollama", "XGBoost", "SMOTE", "Classification", "Regression"),
    "Databases": ("SQLite", "SQL", "ChromaDB"),
    "APIs / Integration": ("Google Gemini API", "OpenWeather API", "API integration", "Requests"),
    "Tools / Platforms": ("Git", "GitHub"),
    "Languages": ("English", "Telugu", "Hindi", "Tamil"),
}
SKILL_CATALOG_GROUPS = {**SKILL_GROUPS, "Databases": (*SKILL_GROUPS["Databases"], "MySQL")}
SKILL_STATUS_ALLOWLIST = frozenset({"verified", "candidate_provided", "partially_verified"})

# This is the only formatting surface the future editor may serialize in v1.
# No colors, font-family changes, tables, columns, images, text boxes, or raw HTML.
ALLOWED_FORMATTING = {
    "font_size_pt": frozenset({9.1, 9.2, 10.0, 11.0, 12.0, 13.0, 18.0}),
    "alignment": frozenset({"left", "center", "right", "justify"}),
    "line_spacing": frozenset({1.0, 1.1, 1.15}),
    "list_style": frozenset({"none", "bullet", "ordered"}),
}
ALLOWED_FORMATTING_KEYS = frozenset({
    "font_size_pt", "bold", "italic", "underline", "alignment",
    "line_spacing", "space_before_pt", "space_after_pt", "list_style",
    "left_indent_in", "first_line_indent_in",
})
ALLOWED_MARK_TYPES = frozenset({"bold", "italic", "underline", "link"})
UNSUPPORTED_CONTENT_TYPES = frozenset({"html", "raw_html", "table", "column", "image", "text_box", "free_form"})

PROFILE_FIELD_SOURCE_IDS = frozenset({
    "/profile/name", "/profile/contact/phone", "/profile/contact/email",
    "/profile/location", "/profile/links/linkedin", "/profile/links/github",
})

TOP_LEVEL_KEYS = frozenset({
    "application_id", "revision_id", "schema_version", "source_plan_reference",
    "source_plan_sha256", "source_generation_reference", "created_at", "status",
    "content", "source_references",
})
SECTION_KEYS = frozenset({"id", "type", "title", "required", "formatting", "blocks"})
COMMON_BLOCK_KEYS = frozenset({"id", "type", "edit_policy", "formatting", "source_refs"})
BLOCK_EXTRA_KEYS = {
    "contact_name": frozenset({"runs"}),
    "contact_details": frozenset({"runs"}),
    "profile_links": frozenset({"runs"}),
    "summary_paragraph": frozenset({"runs"}),
    "skill_group": frozenset({"label", "label_formatting", "items"}),
    "project_entry": frozenset({"project_id", "runs"}),
    "project_bullet": frozenset({"project_id", "bullet_index", "runs"}),
    "project_tech_stack": frozenset({"project_id", "label", "label_formatting", "items"}),
    "project_link": frozenset({"project_id", "runs"}),
    "layout_paragraph": frozenset(),
    "experience_entry": frozenset({"experience_id", "runs"}),
    "experience_bullet": frozenset({"experience_id", "bullet_index", "runs"}),
    "education_line": frozenset({"education_id", "line_index", "runs"}),
    "certification_entry": frozenset({"certification_id", "runs"}),
}
RUN_KEYS = frozenset({"text", "marks", "source_refs"})
SOURCE_REF_KEYS = frozenset({"source_type", "source_id"})
NESTED_ITEM_KEYS = frozenset({"id", "text", "source_refs", "edit_policy", "formatting"})


class ResumeDocumentValidationError(ValueError):
    """Raised when a ResumeDocument is malformed or contains unsupported content."""


def _fail(message: str) -> None:
    raise ResumeDocumentValidationError(message)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _plan_digest(plan: dict[str, Any]) -> str:
    return _sha256(_canonical_json(plan))


def _normalize_plan_reference(reference: Any) -> str:
    if not isinstance(reference, str) or not reference.strip():
        _fail("source_plan_reference is required")
    normalized = reference.strip().replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized) or "://" in normalized:
        _fail("source_plan_reference must be a relative project path")
    parts = PurePosixPath(normalized).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        _fail("source_plan_reference contains an unsafe path")
    if not normalized.startswith("output/reports/") or not normalized.endswith(".json"):
        _fail("source_plan_reference must reference an approved JSON plan under output/reports/")
    return normalized


def sidecar_directory(application_id: str, root: str | Path | None = None) -> Path:
    """Return the future sidecar directory path without creating it."""
    if not isinstance(application_id, str) or not APPLICATION_ID_RE.fullmatch(application_id):
        _fail("Invalid application_id for sidecar storage")
    project_root = Path(root) if root is not None else rg.ROOT
    return project_root / "output" / "resume_edits" / application_id


def _revision_id(document: dict[str, Any]) -> str:
    identity = {
        "schema_version": document.get("schema_version"),
        "application_id": document.get("application_id"),
        "source_plan_reference": document.get("source_plan_reference"),
        "source_plan_sha256": document.get("source_plan_sha256"),
        "source_generation_reference": document.get("source_generation_reference"),
        "content": document.get("content"),
        "source_references": document.get("source_references"),
    }
    return "rev_" + _sha256(_canonical_json(identity))[:24]


def _block_id(section_type: str, block_type: str, identity: str) -> str:
    value = f"{section_type}\0{block_type}\0{identity}".encode("utf-8")
    return "blk_" + hashlib.sha256(value).hexdigest()[:16]


def _source(source_type: str, source_id: str) -> dict[str, str]:
    return {"source_type": source_type, "source_id": source_id}


def _ref_key(ref: dict[str, str]) -> tuple[str, str]:
    return ref["source_type"], ref["source_id"]


def _unique_refs(*groups: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    values = {_ref_key(ref): {"source_type": ref["source_type"], "source_id": ref["source_id"]}
              for group in groups for ref in group}
    return [values[key] for key in sorted(values)]


def _skill_source_id(category: str, name: str) -> str:
    """Canonical skill locator; current skills.json has no per-skill record_id."""
    return f"skill_groups/{quote(category, safe='')}/{quote(name, safe='')}"


def _skill_records(profile: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    records = []
    for group in profile.get("skills", {}).get("skill_groups", []):
        category = group.get("category")
        if not isinstance(category, str):
            continue
        for skill in group.get("skills", []):
            if isinstance(skill, dict) and skill.get("status") in SKILL_STATUS_ALLOWLIST:
                records.append((category, skill))
    return records


def _project_technology_values(project: dict[str, Any]) -> list[str]:
    raw = project.get("technologies") or project.get("frameworks_libraries_tools") or []
    return [str(value) for value in raw if isinstance(value, str)]


def _skill_source_refs(name: str, profile: dict[str, Any], projects: list[dict[str, Any]]) -> list[dict[str, str]]:
    refs = []
    for category, skill in _skill_records(profile):
        if skill.get("name") == name:
            refs.append(_source("skill", _skill_source_id(category, name)))
    for project in projects:
        evidence_values = set(_project_technology_values(project))
        evidence_values.update(str(value) for value in project.get("demonstrated_skills", []) if isinstance(value, str))
        if name in evidence_values:
            refs.append(_source("project", project["record_id"]))
    refs = _unique_refs(refs)
    if not refs:
        _fail(f"No canonical skill/project source exists for displayed skill: {name}")
    return refs


def canonical_skill_catalog(profile: dict[str, Any], projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only skill names backed by an approved profile or selected project."""
    catalog = []
    for group, names in SKILL_CATALOG_GROUPS.items():
        for name in names:
            try:
                refs = _skill_source_refs(name, profile, projects)
            except ResumeDocumentValidationError:
                continue
            catalog.append({
                "group": group,
                "id": _block_id("skills", "skill_item", _skill_source_id(group, name)),
                "text": name,
                "source_refs": refs,
                "edit_policy": "editable_source_backed",
                "formatting": _formatting(font_size_pt=11.0, line_spacing=1.0),
            })
    return catalog


def _profile_value(profile: dict[str, Any], pointer: str) -> Any:
    if pointer not in PROFILE_FIELD_SOURCE_IDS:
        _fail(f"Unsupported canonical profile field reference: {pointer}")
    node: Any = profile.get("master_profile", {})
    for part in pointer.strip("/").split("/"):
        if not isinstance(node, dict) or part not in node:
            _fail(f"Canonical profile field is missing: {pointer}")
        node = node[part]
    return node


def _formatting(**values: Any) -> dict[str, Any]:
    return values


def _run(text: str, source_refs: Iterable[dict[str, str]] = (), marks: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    return {"text": text, "marks": [dict(mark) for mark in marks], "source_refs": _unique_refs(source_refs)}


def _block(section_type: str, block_type: str, identity: str, *, source_refs: Iterable[dict[str, str]],
           edit_policy: str | None = None, formatting: dict[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
    value = {
        "id": _block_id(section_type, block_type, identity),
        "type": block_type,
        "edit_policy": edit_policy or BLOCK_POLICIES[block_type],
        "formatting": formatting or {},
        "source_refs": _unique_refs(source_refs),
    }
    value.update(fields)
    return value


def _section(section_type: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    title = SECTION_TITLES[section_type]
    return {
        "id": "section_" + section_type,
        "type": section_type,
        "title": title,
        "required": section_type in REQUIRED_SECTIONS,
        "formatting": ({"font_size_pt": 13.0, "bold": True, "line_spacing": 1.0,
                        "space_before_pt": 5.0, "space_after_pt": 1.0} if title else {}),
        "blocks": blocks,
    }


def _plain_runs(text: str, refs: Iterable[dict[str, str]]) -> list[dict[str, Any]]:
    return [_run(text, refs)]


def _build_sections(plan: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    master = profile["master_profile"]["profile"]
    projects = rg.effective_selection(plan, profile)
    project_ids = [project["record_id"] for project in projects]
    experiences = rg.effective_experience(plan, profile, projects)
    effective_names = rg.effective_skill_names(plan, profile, projects)
    sections: list[dict[str, Any]] = []

    # Required, protected header fields. Each factual run points to its exact
    # canonical JSON field; display labels/separators carry no factual source.
    name_ref = _source("profile_field", "/profile/name")
    phone_ref = _source("profile_field", "/profile/contact/phone")
    email_ref = _source("profile_field", "/profile/contact/email")
    location_ref = _source("profile_field", "/profile/location")
    linkedin_ref = _source("profile_field", "/profile/links/linkedin")
    github_ref = _source("profile_field", "/profile/links/github")
    links = master.get("links", {})
    phone_href = "tel:" + re.sub(r"[^+\d]", "", str(master["contact"]["phone"]))
    linkedin_href = links["linkedin"] if str(links["linkedin"]).startswith("http") else "https://" + str(links["linkedin"])
    github_href = links["github"] if str(links["github"]).startswith("http") else "https://" + str(links["github"])
    header_blocks = [
        _block("contact_header", "contact_name", "name", source_refs=[name_ref],
               formatting=_formatting(font_size_pt=18.0, bold=True, alignment="center", line_spacing=1.0),
               runs=_plain_runs(str(master["name"]).upper(), [name_ref])),
        _block("contact_header", "contact_details", "contact-details", source_refs=[phone_ref, location_ref, email_ref],
               formatting=_formatting(font_size_pt=10.0, alignment="center", line_spacing=1.0, space_after_pt=1.0),
               runs=[
                   _run(str(master["contact"]["phone"]), [phone_ref], [{"type": "link", "href": phone_href}]),
                   _run(" | "), _run(str(master["location"]), [location_ref]), _run(" | "),
                   _run(str(master["contact"]["email"]), [email_ref], [{"type": "link", "href": "mailto:" + str(master["contact"]["email"])}]),
               ]),
        _block("contact_header", "profile_links", "profile-links", source_refs=[linkedin_ref, github_ref],
               formatting=_formatting(font_size_pt=10.0, alignment="center", line_spacing=1.0, space_after_pt=2.0),
               runs=[
                   _run("LinkedIn: "), _run(str(links["linkedin"]), [linkedin_ref], [{"type": "link", "href": linkedin_href}]),
                   _run(" | "), _run("GitHub: "), _run(str(links["github"]), [github_ref], [{"type": "link", "href": github_href}]),
               ]),
    ]
    sections.append(_section("contact_header", header_blocks))

    summary_refs: list[dict[str, str]] = []
    for project in projects:
        summary_refs.append(_source("project", project["record_id"]))
    for name in effective_names:
        summary_refs.extend(_skill_source_refs(name, profile, projects))
    for experience in experiences:
        summary_refs.append(_source("experience", experience["record_id"]))
    # The fixed opening phrase identifies the candidate as a Computer Science
    # fresher; retain the canonical B.Tech education record as supporting source.
    for education in profile["education"]["education"]:
        if education.get("record_id") == "education_biher_btech":
            summary_refs.append(_source("education", education["record_id"]))
    summary_refs = _unique_refs(summary_refs)
    if not summary_refs:
        _fail("Generated professional summary has no canonical provenance")
    summary_text = " ".join(rg.summary_lines(plan, profile))
    sections.append(_section("professional_summary", [
        _block("professional_summary", "summary_paragraph", "generated-summary", source_refs=summary_refs,
               edit_policy="editable_source_backed",
               formatting=_formatting(font_size_pt=11.0, alignment="justify", line_spacing=1.0),
               runs=_plain_runs(summary_text, summary_refs))
    ]))

    displayed_skill_names = set(effective_names)
    skill_blocks = []
    for label, catalog_names in SKILL_GROUPS.items():
        selected = list(catalog_names) if label == "Languages" else [name for name in catalog_names if name in displayed_skill_names]
        if not selected:
            continue
        items = []
        refs_for_group: list[dict[str, str]] = []
        for name in selected:
            refs = _skill_source_refs(name, profile, projects)
            refs_for_group.extend(refs)
            items.append({
                "id": _block_id("skills", "skill_item", _skill_source_id(label, name)),
                "text": name,
                "source_refs": refs,
                "edit_policy": "editable_source_backed",
                "formatting": _formatting(font_size_pt=11.0, line_spacing=1.0),
            })
        skill_blocks.append(_block("skills", "skill_group", label, source_refs=refs_for_group,
                                   formatting=_formatting(font_size_pt=11.0, line_spacing=1.0),
                                   label=label, label_formatting=_formatting(font_size_pt=12.0, bold=True), items=items))
    sections.append(_section("skills", skill_blocks))

    project_blocks = []
    for project in projects:
        project_id = project["record_id"]
        project_ref = _source("project", project_id)
        project_blocks.append(_block("projects", "project_entry", project_id, source_refs=[project_ref],
                                      formatting=_formatting(font_size_pt=12.0, bold=True, line_spacing=1.0),
                                      project_id=project_id, runs=_plain_runs(str(project["name"]), [project_ref])))
        for index, bullet in enumerate(rg.project_bullets(project)[:3]):
            project_blocks.append(_block("projects", "project_bullet", f"{project_id}:bullet:{index}",
                                          source_refs=[project_ref],
                                          formatting=_formatting(font_size_pt=11.0, line_spacing=1.0,
                                                                space_before_pt=0.2, space_after_pt=0.2,
                                                                list_style="bullet", left_indent_in=0.16,
                                                                first_line_indent_in=-0.12),
                                          edit_policy="editable_source_backed", project_id=project_id,
                                          bullet_index=index, runs=_plain_runs(str(bullet), [project_ref])))
        raw_technologies = _project_technology_values(project)
        stack = []
        for technology in raw_technologies:
            if technology not in stack:
                stack.append(technology)
        stack = stack[:8]
        stack_items = [{
            "id": _block_id("projects", "technology", f"{project_id}:{index}:{value}"),
            "text": value,
            "source_refs": [project_ref],
            "edit_policy": "source_backed_read_only",
            "formatting": _formatting(font_size_pt=11.0, line_spacing=1.0),
        } for index, value in enumerate(stack)]
        project_blocks.append(_block("projects", "project_tech_stack", f"{project_id}:tech-stack",
                                      source_refs=[project_ref], formatting=_formatting(font_size_pt=11.0, line_spacing=1.0),
                                      project_id=project_id, label="Tech Stack: ",
                                      label_formatting=_formatting(font_size_pt=12.0, bold=True), items=stack_items))
        github_url = project.get("github_url")
        if isinstance(github_url, str) and github_url.startswith("https://github.com/"):
            project_blocks.append(_block("projects", "project_link", f"{project_id}:link", source_refs=[project_ref],
                                          formatting=_formatting(font_size_pt=11.0, line_spacing=1.0,
                                                                space_before_pt=0.2, space_after_pt=0.2),
                                          project_id=project_id,
                                          runs=[_run("Project Link: "), _run(github_url, [project_ref], [{"type": "link", "href": github_url}])]))
    sections.append(_section("projects", project_blocks))

    if experiences:
        experience_blocks = []
        for experience in experiences:
            experience_id = experience["record_id"]
            experience_ref = _source("experience", experience_id)
            title = f"{experience['title']} — {experience['organization']} ({rg.display_date(experience['start_date'])}–{rg.display_date(experience['end_date'])})"
            experience_blocks.append(_block("experience", "experience_entry", experience_id,
                                             source_refs=[experience_ref],
                                             formatting=_formatting(font_size_pt=12.0, bold=True, line_spacing=1.0),
                                             experience_id=experience_id, runs=_plain_runs(title, [experience_ref])))
            for index, bullet in enumerate(experience.get("responsibilities", [])[:3]):
                experience_blocks.append(_block("experience", "experience_bullet", f"{experience_id}:bullet:{index}",
                                                 source_refs=[experience_ref],
                                                 formatting=_formatting(font_size_pt=11.0, line_spacing=1.0,
                                                                       space_before_pt=0.2, space_after_pt=0.2,
                                                                       list_style="bullet", left_indent_in=0.16,
                                                                       first_line_indent_in=-0.12),
                                                 edit_policy="editable_source_backed", experience_id=experience_id,
                                                 bullet_index=index, runs=_plain_runs(str(bullet), [experience_ref])))
        sections.append(_section("experience", experience_blocks))

    education_blocks = []
    allowed_education_ids = {"education_biher_btech", "education_harvest_higher_secondary", "education_harvest_secondary"}
    for education in profile["education"]["education"]:
        education_id = education["record_id"]
        if education_id not in allowed_education_ids:
            _fail(f"No current frozen-generator education rule exists for {education_id}")
        education_ref = _source("education", education_id)
        if education_id == "education_biher_btech":
            lines = [
                f"{education['institution']} — {education['degree']}",
                f"{education['field_of_study']} ({education['start_date']}–{education['end_date']}); {education['grade']}",
            ]
        elif education_id == "education_harvest_higher_secondary":
            lines = [f"{education['institution']} — Class XII — CBSE ({education['end_date']}); {education['grade']}"]
        else:
            lines = [f"{education['institution']} — Class X — CBSE ({education['end_date']}); {education['grade']}"]
        for index, line in enumerate(lines):
            education_blocks.append(_block("education", "education_line", f"{education_id}:line:{index}",
                                           source_refs=[education_ref],
                                           formatting=_formatting(font_size_pt=11.0, line_spacing=1.0),
                                           education_id=education_id, line_index=index,
                                           runs=_plain_runs(line, [education_ref])))
    sections.append(_section("education", education_blocks))

    certification_blocks = []
    for certification in rg.effective_certs(plan, profile):
        certification_id = certification["record_id"]
        certification_ref = _source("certification", certification_id)
        text = f"{certification['name']} — {certification['issuer']} ({rg.display_date(certification.get('issue_date'))})"
        certification_blocks.append(_block("certifications", "certification_entry", certification_id,
                                            source_refs=[certification_ref],
                                            formatting=_formatting(font_size_pt=11.0, line_spacing=1.0,
                                                                  space_before_pt=0.2, space_after_pt=0.2,
                                                                  list_style="bullet", left_indent_in=0.16,
                                                                  first_line_indent_in=-0.12),
                                            certification_id=certification_id,
                                            runs=_plain_runs(text, [certification_ref])))
    sections.append(_section("certifications", certification_blocks))
    return sections


def _collect_refs(value: Any) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if set(node) == SOURCE_REF_KEYS and all(isinstance(node.get(k), str) for k in SOURCE_REF_KEYS):
                found.append({"source_type": node["source_type"], "source_id": node["source_id"]})
                return
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(value)
    return _unique_refs(found)


def _approved_context(application: dict[str, Any], plan: dict[str, Any], profile: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    aid = application.get("application_id")
    if not isinstance(aid, str) or not APPLICATION_ID_RE.fullmatch(aid):
        _fail("Invalid application_id")
    if application.get("resume_generation_allowed") is not True:
        _fail("The application does not have an approved Resume Plan")
    if plan.get("approval_checkpoint", {}).get("resume_generation_allowed") is not True:
        _fail("The source Resume Plan is not approved")
    projects = rg.effective_selection(plan, profile)
    project_ids = [project.get("record_id") for project in projects]
    if not projects or any(not isinstance(record_id, str) for record_id in project_ids):
        _fail("The approved plan has no valid selected projects")
    app_project_ids = application.get("project_selection_record_ids")
    if app_project_ids is not None and app_project_ids != project_ids:
        _fail("Application project selection does not match the approved Resume Plan")
    experiences = rg.effective_experience(plan, profile, projects)
    certifications = rg.effective_certs(plan, profile)
    return projects, experiences, certifications


def build_resume_document(application: dict[str, Any], plan: dict[str, Any], profile: dict[str, Any], *,
                          created_at: str | None = None, status: str = "draft") -> dict[str, Any]:
    """Build a deterministic ResumeDocument from an approved application context.

    Skill source IDs are resolvable canonical JSON locators because the current
    skills.json format has no skill record_id. All other factual records use the
    record_id already present in their canonical file.
    """
    projects, _, _ = _approved_context(application, plan, profile)
    plan_reference = _normalize_plan_reference(application.get("phase8_plan_reference"))
    generation_reference = application.get("working_resume_generation_id") or application.get("resume_generation_id")
    if generation_reference is not None and (not isinstance(generation_reference, str) or not GENERATION_ID_RE.fullmatch(generation_reference)):
        _fail("Invalid source generation reference")
    if status not in REVISION_STATUSES:
        _fail("Invalid revision status")
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()
    document = {
        "application_id": application["application_id"],
        "revision_id": "",
        "schema_version": SCHEMA_VERSION,
        "source_plan_reference": plan_reference,
        "source_plan_sha256": _plan_digest(plan),
        "source_generation_reference": generation_reference,
        "created_at": created_at,
        "status": status,
        "content": {"sections": _build_sections(plan, profile)},
    }
    document["source_references"] = _collect_refs(document["content"])
    document["revision_id"] = _revision_id(document)
    validate_resume_document(document, application, plan, profile)
    return document


def build_resume_document_for_application(application: dict[str, Any], *, root: str | Path | None = None,
                                          profile: dict[str, Any] | None = None,
                                          created_at: str | None = None) -> dict[str, Any]:
    """Load the approved plan/profile read-only and adapt them for one application."""
    project_root = Path(root) if root is not None else rg.ROOT
    reference = _normalize_plan_reference(application.get("phase8_plan_reference"))
    root_resolved = project_root.resolve()
    plan_path = (root_resolved / Path(*PurePosixPath(reference).parts)).resolve()
    try:
        plan_path.relative_to(root_resolved)
    except ValueError:
        _fail("Resolved plan path escapes the project root")
    if not plan_path.is_file():
        _fail("Approved Resume Plan file does not exist")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    canonical_profile = profile if profile is not None else rg.profile()
    return build_resume_document(application, plan, canonical_profile, created_at=created_at)


def _resolve_skill_source(source_id: str, profile: dict[str, Any]) -> dict[str, Any] | None:
    parts = source_id.split("/")
    if len(parts) != 3 or parts[0] != "skill_groups":
        return None
    category, encoded_name = parts[1], parts[2]
    name = unquote(encoded_name)
    # Require a canonical, unambiguous URI form; this prevents alternate/fuzzy IDs.
    if quote(category, safe="") != category or quote(name, safe="") != encoded_name:
        return None
    matches = [skill for group in profile.get("skills", {}).get("skill_groups", [])
               if group.get("category") == category
               for skill in group.get("skills", [])
               if skill.get("name") == name and skill.get("status") in SKILL_STATUS_ALLOWLIST]
    return matches[0] if len(matches) == 1 else None


def _canonical_href(ref: dict[str, str], profile: dict[str, Any], project_map: dict[str, dict[str, Any]]) -> set[str]:
    source_type, source_id = _ref_key(ref)
    if source_type == "profile_field":
        value = str(_profile_value(profile, source_id))
        if source_id == "/profile/contact/phone":
            return {"tel:" + re.sub(r"[^+\d]", "", value)}
        if source_id == "/profile/contact/email":
            return {"mailto:" + value}
        if source_id in {"/profile/links/linkedin", "/profile/links/github"}:
            return {value if value.startswith("http") else "https://" + value}
    if source_type == "project" and source_id in project_map:
        value = project_map[source_id].get("github_url")
        if isinstance(value, str) and value.startswith("https://github.com/"):
            return {value}
    return set()


def _validate_source_ref(ref: Any, profile: dict[str, Any], selected_projects: set[str],
                         selected_experiences: set[str], selected_certifications: set[str],
                         education_ids: set[str]) -> None:
    if not isinstance(ref, dict) or set(ref) != SOURCE_REF_KEYS:
        _fail("Malformed source reference")
    source_type, source_id = ref.get("source_type"), ref.get("source_id")
    if not isinstance(source_type, str) or not isinstance(source_id, str) or not source_id:
        _fail("Source reference type/id must be non-empty strings")
    if source_type == "profile_field":
        if source_id not in PROFILE_FIELD_SOURCE_IDS:
            _fail(f"Unsupported profile field source reference: {source_id}")
        _profile_value(profile, source_id)
        return
    if source_type == "skill":
        if _resolve_skill_source(source_id, profile) is None:
            _fail(f"Unknown canonical skill source reference: {source_id}")
        return
    if source_type == "project":
        projects = {item.get("record_id"): item for item in profile.get("projects", {}).get("projects", [])}
        if source_id not in selected_projects or source_id not in projects or projects[source_id].get("project_status") != "completed":
            _fail(f"Project source is not selected, canonical, and completed: {source_id}")
        return
    if source_type == "experience":
        records = {item.get("record_id") for item in profile.get("experience", {}).get("experiences", [])}
        if source_id not in selected_experiences or source_id not in records:
            _fail(f"Experience source is not selected and canonical: {source_id}")
        return
    if source_type == "certification":
        records = {item.get("record_id") for item in profile.get("certifications", {}).get("certifications", [])}
        if source_id not in selected_certifications or source_id not in records:
            _fail(f"Certification source is not selected and canonical: {source_id}")
        return
    if source_type == "education":
        if source_id not in education_ids:
            _fail(f"Unknown canonical education source reference: {source_id}")
        return
    _fail(f"Unsupported source type: {source_type}")


def _validate_formatting(value: Any, where: str) -> None:
    if not isinstance(value, dict) or not set(value).issubset(ALLOWED_FORMATTING_KEYS):
        _fail(f"Unsupported formatting attributes in {where}")
    for key, item in value.items():
        if key in {"bold", "italic", "underline"}:
            if type(item) is not bool:
                _fail(f"{where}.{key} must be boolean")
        elif key in ALLOWED_FORMATTING:
            if key == "font_size_pt":
                if type(item) not in {int, float} or float(item) not in ALLOWED_FORMATTING[key]:
                    _fail(f"Unsupported font size in {where}")
            elif key == "line_spacing":
                if type(item) not in {int, float} or float(item) not in ALLOWED_FORMATTING[key]:
                    _fail(f"Unsupported line spacing in {where}")
            elif key == "alignment":
                if item not in ALLOWED_FORMATTING[key]:
                    _fail(f"Unsupported alignment in {where}")
            elif key == "list_style":
                if item not in ALLOWED_FORMATTING[key]:
                    _fail(f"Unsupported list style in {where}")
        elif key in {"space_before_pt", "space_after_pt"}:
            if type(item) not in {int, float} or not math.isfinite(float(item)) or not 0 <= float(item) <= 6:
                _fail(f"Unsupported paragraph spacing in {where}")
        elif key == "left_indent_in":
            if type(item) not in {int, float} or not 0 <= float(item) <= 1:
                _fail(f"Unsupported left indent in {where}")
        elif key == "first_line_indent_in":
            if type(item) not in {int, float} or not -0.25 <= float(item) <= 0.25:
                _fail(f"Unsupported first-line indent in {where}")


def _validate_marks(marks: Any, run_refs: list[dict[str, str]], profile: dict[str, Any],
                    project_map: dict[str, dict[str, Any]], where: str) -> None:
    if not isinstance(marks, list):
        _fail(f"{where}.marks must be a list")
    seen = set()
    for mark in marks:
        if not isinstance(mark, dict) or mark.get("type") not in ALLOWED_MARK_TYPES:
            _fail(f"Unsupported text mark in {where}")
        kind = mark["type"]
        if kind in seen:
            _fail(f"Duplicate text mark in {where}")
        seen.add(kind)
        if kind == "link":
            if set(mark) != {"type", "href"} or not isinstance(mark.get("href"), str):
                _fail(f"Malformed link mark in {where}")
            href = mark["href"]
            try:
                scheme = urlsplit(href).scheme.lower()
            except ValueError:
                _fail(f"Malformed hyperlink in {where}")
            if scheme not in {"https", "mailto", "tel"}:
                _fail(f"Unsupported hyperlink scheme in {where}")
            allowed = set().union(*(_canonical_href(ref, profile, project_map) for ref in run_refs)) if run_refs else set()
            if href not in allowed:
                _fail(f"Hyperlink is not a canonical profile/project link in {where}")
        elif set(mark) != {"type"}:
            _fail(f"Unexpected attributes on {kind} mark in {where}")


def _validate_runs(runs: Any, block_refs: list[dict[str, str]], profile: dict[str, Any],
                   project_map: dict[str, dict[str, Any]], selected_projects: set[str],
                   selected_experiences: set[str], selected_certifications: set[str],
                   education_ids: set[str], where: str) -> str:
    if not isinstance(runs, list) or not runs:
        _fail(f"{where}.runs must be a non-empty list")
    text_parts = []
    seen_refs = []
    for index, run in enumerate(runs):
        if not isinstance(run, dict) or set(run) != RUN_KEYS:
            _fail(f"Malformed text run in {where}")
        text = run.get("text")
        if not isinstance(text, str) or len(text) > 10000 or any(ord(ch) < 32 and ch not in "\t\n\r" for ch in text):
            _fail(f"Invalid text value in {where}")
        refs = run.get("source_refs")
        if not isinstance(refs, list):
            _fail(f"Run source_refs must be a list in {where}")
        for ref in refs:
            _validate_source_ref(ref, profile, selected_projects, selected_experiences,
                                 selected_certifications, education_ids)
            seen_refs.append(ref)
        if not set(map(tuple, (_ref_key(r) for r in refs))).issubset(set(_ref_key(r) for r in block_refs)):
            _fail(f"Run references exceed block provenance in {where}")
        _validate_marks(run.get("marks"), refs, profile, project_map, f"{where}.runs[{index}]")
        text_parts.append(text)
    if _unique_refs(seen_refs) != block_refs:
        _fail(f"Block provenance does not match its text runs in {where}")
    return "".join(text_parts)


def _without_formatting(block: dict[str, Any]) -> dict[str, Any]:
    copy = dict(block)
    copy.pop("formatting", None)
    copy.pop("label_formatting", None)
    return copy


def _block_map(sections: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {block["id"]: block for section in sections for block in section["blocks"]}


def _validate_document_content(document: dict[str, Any], application: dict[str, Any],
                              plan: dict[str, Any], profile: dict[str, Any]) -> None:
    projects, experiences, certifications = _approved_context(application, plan, profile)
    selected_project_ids = {x["record_id"] for x in projects}
    selected_experience_ids = {x["record_id"] for x in experiences}
    selected_certification_ids = {x["record_id"] for x in certifications}
    education_records = profile.get("education", {}).get("education", [])
    education_ids = {x.get("record_id") for x in education_records}
    project_map = {x.get("record_id"): x for x in profile.get("projects", {}).get("projects", [])}

    if not isinstance(document, dict) or set(document) != TOP_LEVEL_KEYS:
        _fail("ResumeDocument has missing or unsupported top-level fields")
    if type(document.get("schema_version")) is not int or document["schema_version"] != SCHEMA_VERSION:
        _fail("Unsupported ResumeDocument schema_version")
    if document.get("application_id") != application.get("application_id") or not APPLICATION_ID_RE.fullmatch(str(document.get("application_id", ""))):
        _fail("ResumeDocument application_id is invalid or does not match the application")
    if document.get("source_plan_reference") != _normalize_plan_reference(application.get("phase8_plan_reference")):
        _fail("ResumeDocument source plan does not match this application")
    if document.get("source_plan_sha256") != _plan_digest(plan):
        _fail("ResumeDocument source plan digest does not match the approved plan")
    expected_generation = application.get("working_resume_generation_id") or application.get("resume_generation_id")
    if document.get("source_generation_reference") != expected_generation:
        _fail("ResumeDocument generation reference does not match the application")
    if expected_generation is not None and (not isinstance(expected_generation, str) or not GENERATION_ID_RE.fullmatch(expected_generation)):
        _fail("Invalid application generation reference")
    if not isinstance(document.get("status"), str) or document["status"] not in REVISION_STATUSES:
        _fail("Invalid revision status")
    created_at = document.get("created_at")
    if not isinstance(created_at, str):
        _fail("created_at must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        _fail("created_at must be an ISO-8601 timestamp")
    if parsed.tzinfo is None:
        _fail("created_at must include a timezone")
    if document.get("revision_id") != _revision_id(document) or not REVISION_ID_RE.fullmatch(str(document.get("revision_id", ""))):
        _fail("revision_id is malformed or does not match the document content")

    content = document.get("content")
    if not isinstance(content, dict) or set(content) != {"sections"} or not isinstance(content.get("sections"), list):
        _fail("Malformed content root")
    sections = content["sections"]
    effective_names = rg.effective_skill_names(plan, profile, projects)
    expected_types = ["contact_header", "professional_summary", "skills", "projects"]
    if experiences:
        expected_types.append("experience")
    expected_types.extend(["education", "certifications"])
    actual_types = [section.get("type") if isinstance(section, dict) else None for section in sections]
    if actual_types != expected_types:
        _fail("ResumeDocument sections are missing, unsupported, or out of current generator order")
    if any(section_type in DISABLED_SECTIONS for section_type in actual_types):
        _fail("Achievements are unsupported by current resume rules")

    expected_sections = _build_sections(plan, profile)
    all_ids: set[str] = set()
    for index, (section, expected_section) in enumerate(zip(sections, expected_sections)):
        if not isinstance(section, dict) or set(section) != SECTION_KEYS:
            _fail(f"Malformed section at index {index}")
        section_type = section.get("type")
        if section_type not in SUPPORTED_SECTION_TYPES:
            _fail(f"Unsupported section type: {section_type}")
        if section.get("id") != "section_" + section_type:
            _fail(f"Invalid section identity for {section_type}")
        title = section.get("title")
        if title is not None and (not isinstance(title, str) or not title.strip() or len(title) > 60
                                  or any(not char.isprintable() or char in "<>" for char in title)):
            _fail(f"Invalid presentation-only heading for {section_type}")
        if section.get("required") is not (section_type in REQUIRED_SECTIONS):
            _fail(f"Invalid required flag for section {section_type}")
        _validate_formatting(section.get("formatting"), f"section {section_type}")
        if not isinstance(section.get("blocks"), list):
            _fail(f"Section blocks must be a list: {section_type}")
        expected_blocks = {block["id"]: block for block in expected_section["blocks"]}
        actual_blocks = section["blocks"]
        for block in actual_blocks:
            if not isinstance(block, dict):
                _fail(f"Malformed block in {section_type}")
            block_type = block.get("type")
            if block_type in UNSUPPORTED_CONTENT_TYPES or block_type not in BLOCK_TYPES_BY_SECTION[section_type]:
                _fail(f"Unsupported block type {block_type!r} in {section_type}")
            if block_type == "layout_paragraph":
                if set(block) != COMMON_BLOCK_KEYS or not isinstance(block.get("id"), str) or not BLOCK_ID_RE.fullmatch(block["id"]):
                    _fail("Malformed layout paragraph")
                if block.get("edit_policy") != "presentation" or block.get("formatting") != {} or block.get("source_refs") != []:
                    _fail("Layout paragraphs must remain presentation-only and provenance-free")
                if block["id"] in all_ids:
                    _fail("Duplicate stable block id")
                all_ids.add(block["id"])
                continue
            if set(block) != COMMON_BLOCK_KEYS | BLOCK_EXTRA_KEYS[block_type]:
                _fail(f"Malformed or unsupported fields in {block_type}")
            if not isinstance(block.get("id"), str) or not BLOCK_ID_RE.fullmatch(block["id"]):
                _fail(f"Invalid stable block id in {section_type}")
            if block["id"] in all_ids:
                _fail("Duplicate stable block id")
            all_ids.add(block["id"])
            expected_block = expected_blocks.get(block["id"])
            additive_bullet = expected_block is None and block_type in ADDITIVE_BULLET_TYPES
            new_skill_group = expected_block is None and block_type == "skill_group"
            if expected_block is None and not (additive_bullet or new_skill_group):
                _fail(f"Unknown stable block ID in {section_type}")
            allowed_policies = {BLOCK_POLICIES[block_type]}
            if block_type in EDITABLE_TEXT_BLOCK_TYPES:
                allowed_policies.add("protected")  # accept an existing v1 sidecar until it is edited
            if block.get("edit_policy") not in allowed_policies:
                _fail(f"Invalid editing policy for {block_type}")
            _validate_formatting(block.get("formatting"), f"block {block_type}")
            refs = block.get("source_refs")
            if not isinstance(refs, list) or not refs or refs != _unique_refs(refs):
                _fail(f"Missing, duplicated, or unsorted provenance for {block_type}")
            for ref in refs:
                _validate_source_ref(ref, profile, selected_project_ids, selected_experience_ids,
                                     selected_certification_ids, education_ids)
            block_text = _validate_runs(block.get("runs"), refs, profile, project_map,
                                        selected_project_ids, selected_experience_ids,
                                        selected_certification_ids, education_ids,
                                        f"{section_type}.{block_type}") if "runs" in block else None
            if block_type == "skill_group":
                _validate_formatting(block.get("label_formatting"), "skill_group.label_formatting")
                label = block.get("label")
                if label not in SKILL_GROUPS or block["id"] != _block_id("skills", "skill_group", label):
                    _fail("Unsupported skill group identity")
                if expected_block is not None and expected_block.get("label") != label:
                    _fail("Skill group identity changed")
                if not isinstance(block.get("items"), list) or not block["items"]:
                    _fail("A displayed skill group must contain at least one supported skill")
                candidates = {item["id"]: item for item in canonical_skill_catalog(profile, projects) if item["group"] == label}
                item_refs = []
                item_ids = set()
                for item in block["items"]:
                    if not isinstance(item, dict) or set(item) != NESTED_ITEM_KEYS:
                        _fail("Malformed skill item")
                    if not isinstance(item.get("id"), str) or item["id"] not in candidates:
                        _fail("Skill is not in the canonical evidence catalog")
                    if item["id"] in item_ids or item["id"] in all_ids:
                        _fail("Duplicate skill item")
                    item_ids.add(item["id"]); all_ids.add(item["id"])
                    canonical = candidates[item["id"]]
                    if item.get("source_refs") != canonical["source_refs"]:
                        _fail("Skill provenance differs from its canonical profile/project evidence")
                    if item.get("edit_policy") not in {"source_backed_read_only", "editable_source_backed"}:
                        _fail("Skill item has an unsupported edit policy")
                    if not isinstance(item.get("text"), str) or not item["text"].strip() or len(item["text"]) > 160:
                        _fail("Skill text must be non-empty and within the supported limit")
                    _validate_formatting(item.get("formatting"), "skill_group.item")
                    for ref in item["source_refs"]:
                        _validate_source_ref(ref, profile, selected_project_ids, selected_experience_ids,
                                             selected_certification_ids, education_ids)
                        item_refs.append(ref)
                if _unique_refs(item_refs) != refs:
                    _fail("Skill group provenance does not match its selected items")
            elif block_type == "project_tech_stack":
                _validate_formatting(block.get("label_formatting"), "project_tech_stack.label_formatting")
                if not isinstance(block.get("items"), list):
                    _fail("project_tech_stack.items must be a list")
                expected_items = {item["id"]: item for item in expected_block["items"]}
                item_refs = []
                for item in block["items"]:
                    if not isinstance(item, dict) or set(item) != NESTED_ITEM_KEYS:
                        _fail("Malformed item in project_tech_stack")
                    if not isinstance(item.get("id"), str) or item["id"] not in expected_items or item["id"] in all_ids:
                        _fail("Unknown or duplicate project technology item")
                    all_ids.add(item["id"])
                    expected_item = expected_items[item["id"]]
                    if item != expected_item:
                        _fail("Project technology items are source-backed read-only")
                    for ref in item["source_refs"]:
                        _validate_source_ref(ref, profile, selected_project_ids, selected_experience_ids,
                                             selected_certification_ids, education_ids)
                        item_refs.append(ref)
                if _unique_refs(item_refs) != refs or refs != expected_block["source_refs"]:
                    _fail("Project technology provenance changed")
                if not isinstance(block.get("label"), str) or block.get("label") != "Tech Stack: ":
                    _fail("Unsupported project technology label")
                project = project_map.get(block.get("project_id"))
                if not project or refs != [_source("project", block["project_id"])]:
                    _fail("Project technology source does not match its project")
                raw = _project_technology_values(project)
                canonical_stack = []
                for value in raw:
                    if value not in canonical_stack:
                        canonical_stack.append(value)
                if [item["text"] for item in block["items"]] != canonical_stack[:8]:
                    _fail("Project technology stack differs from canonical project data")
            else:
                if block_type in EDITABLE_TEXT_BLOCK_TYPES:
                    if additive_bullet:
                        parent_key = "project_id" if block_type == "project_bullet" else "experience_id"
                        parent_type = "project" if block_type == "project_bullet" else "experience"
                        parent_id = block.get(parent_key)
                        if type(block.get("bullet_index")) is not int or not 0 <= block["bullet_index"] <= 4:
                            _fail("New source-backed bullets require an unused stable index from 0 through 4")
                        if refs != [_source(parent_type, parent_id)]:
                            _fail("A new bullet must cite exactly its own canonical project or experience")
                        if (block_type == "project_bullet" and parent_id not in selected_project_ids) or (
                            block_type == "experience_bullet" and parent_id not in selected_experience_ids
                        ):
                            _fail("A new bullet cannot create an unselected project or experience")
                    else:
                        actual_immutable = _without_formatting(block)
                        expected_immutable = _without_formatting(expected_block)
                        actual_immutable.pop("runs", None)
                        expected_immutable.pop("runs", None)
                        # Existing v1 sidecars marked these source-backed facts protected.
                        actual_immutable["edit_policy"] = "editable_source_backed"
                        expected_immutable["edit_policy"] = "editable_source_backed"
                        if actual_immutable != expected_immutable:
                            _fail(f"Unsupported metadata/provenance change in editable {block_type}")
                    if block_type == "summary_paragraph" and not block_text.strip():
                        _fail("Professional summary cannot be empty")
                    if block_type in ADDITIVE_BULLET_TYPES and not block_text.strip():
                        _fail(f"Editable factual bullet cannot be empty: {block_type}")
                    if any(run["text"].strip() and not run["source_refs"] for run in block["runs"]):
                        _fail(f"Every factual text run must retain provenance in {block_type}")
                else:
                    if expected_block is None or _without_formatting(block) != _without_formatting(expected_block):
                        _fail(f"Protected/source-backed content changed in {block_type}")
        # Protected blocks remain mandatory; evidence-backed bullets and skill choices can change.
        actual_by_id = {block["id"]: block for block in actual_blocks}
        for expected_block in expected_section["blocks"]:
            if (expected_block["edit_policy"] != "editable_source_backed"
                    and expected_block["type"] != "skill_group"
                    and expected_block["id"] not in actual_by_id):
                _fail(f"Required protected block is missing: {expected_block['type']}")
        if section_type == "contact_header" and [b["type"] for b in actual_blocks] != ["contact_name", "contact_details", "profile_links"]:
            _fail("Required protected contact information is incomplete or out of order")
        if section_type == "professional_summary" and sum(b["type"] == "summary_paragraph" for b in actual_blocks) != 1:
            _fail("Exactly one source-backed summary paragraph is required")
        if section_type == "skills":
            groups = [block for block in actual_blocks if block["type"] == "skill_group"]
            labels = [block["label"] for block in groups]
            expected_labels = [block["label"] for block in expected_section["blocks"] if block["type"] == "skill_group"]
            if not groups or len(labels) != len(set(labels)) or labels != expected_labels:
                _fail("Canonical skill groups must remain present in their approved order; edit individual skill entries instead")
            order = {label: index for index, label in enumerate(SKILL_GROUPS)}
            if labels != sorted(labels, key=order.__getitem__):
                _fail("Skill groups must remain in the approved canonical order")
        if section_type == "projects":
            entry_ids = [b.get("project_id") for b in actual_blocks if b["type"] == "project_entry"]
            if entry_ids != [project["record_id"] for project in projects]:
                _fail("Selected project IDs/order differ from the approved application")
            _validate_project_block_order(actual_blocks, projects)
        if section_type == "experience":
            entry_ids = [b.get("experience_id") for b in actual_blocks if b["type"] == "experience_entry"]
            if entry_ids != [experience["record_id"] for experience in experiences]:
                _fail("Experience IDs/order differ from the approved plan")
            _validate_experience_block_order(actual_blocks, experiences)
        if section_type == "education":
            _validate_education_block_order(actual_blocks, expected_section["blocks"])
        if section_type == "certifications":
            expected_cert_ids = {block["certification_id"] for block in expected_section["blocks"]}
            actual_cert_ids = [block.get("certification_id") for block in actual_blocks]
            if set(actual_cert_ids) != expected_cert_ids or len(actual_cert_ids) != len(expected_cert_ids):
                _fail("All and only the existing canonical certification entries must remain")

    expected_refs = _collect_refs(document["content"])
    if not isinstance(document.get("source_references"), list) or document["source_references"] != expected_refs:
        _fail("Document-level provenance index does not match block provenance")
    total_text = sum(len(_block_text(block)) for section in sections for block in section["blocks"])
    if total_text > 50000:
        _fail("ResumeDocument exceeds the allowed content size")


def _block_text(block: dict[str, Any]) -> str:
    if "runs" in block:
        return "".join(run.get("text", "") for run in block["runs"] if isinstance(run, dict))
    if block.get("type") in {"skill_group", "project_tech_stack"}:
        return ", ".join(item.get("text", "") for item in block.get("items", []))
    return ""


def _validate_project_block_order(blocks: list[dict[str, Any]], projects: list[dict[str, Any]]) -> None:
    factual_blocks = [block for block in blocks if block.get("type") != "layout_paragraph"]
    cursor = 0
    for project in projects:
        project_id = project["record_id"]
        if cursor >= len(factual_blocks) or factual_blocks[cursor].get("type") != "project_entry" or factual_blocks[cursor].get("project_id") != project_id:
            _fail("Project blocks are not grouped in approved project order")
        cursor += 1
        seen_bullet_indexes = set()
        while cursor < len(factual_blocks) and factual_blocks[cursor].get("type") == "project_bullet" and factual_blocks[cursor].get("project_id") == project_id:
            index = factual_blocks[cursor].get("bullet_index")
            if type(index) is not int or not 0 <= index <= 4 or index in seen_bullet_indexes:
                _fail("Project bullet reference/index is invalid")
            seen_bullet_indexes.add(index)
            cursor += 1
        if len(seen_bullet_indexes) > 5:
            _fail("A project may contain at most five source-backed bullets")
        expected_order = ["project_tech_stack"]
        if cursor >= len(factual_blocks) or factual_blocks[cursor].get("type") != "project_tech_stack" or factual_blocks[cursor].get("project_id") != project_id:
            _fail("Canonical project tech stack is required")
        cursor += 1
        if cursor < len(factual_blocks) and factual_blocks[cursor].get("type") == "project_link" and factual_blocks[cursor].get("project_id") == project_id:
            cursor += 1
    if cursor != len(factual_blocks):
        _fail("Unexpected or unsupported project block")


def _validate_experience_block_order(blocks: list[dict[str, Any]], experiences: list[dict[str, Any]]) -> None:
    cursor = 0
    for experience in experiences:
        experience_id = experience["record_id"]
        if cursor >= len(blocks) or blocks[cursor].get("type") != "experience_entry" or blocks[cursor].get("experience_id") != experience_id:
            _fail("Experience blocks are not grouped in approved order")
        cursor += 1
        seen_indexes = set()
        while cursor < len(blocks) and blocks[cursor].get("type") == "experience_bullet" and blocks[cursor].get("experience_id") == experience_id:
            index = blocks[cursor].get("bullet_index")
            if type(index) is not int or not 0 <= index <= 4 or index in seen_indexes:
                _fail("Experience bullet reference/index is invalid")
            seen_indexes.add(index)
            cursor += 1
        if len(seen_indexes) > 5:
            _fail("An experience may contain at most five source-backed bullets")
    if cursor != len(blocks):
        _fail("Unexpected or unsupported experience block")


def _validate_education_block_order(blocks: list[dict[str, Any]], expected_blocks: list[dict[str, Any]]) -> None:
    expected: dict[str, list[int]] = {}
    for block in expected_blocks:
        expected.setdefault(block["education_id"], []).append(block["line_index"])
    actual: dict[str, list[int]] = {}
    group_order: list[str] = []
    closed: set[str] = set()
    for block in blocks:
        if block.get("type") != "education_line":
            _fail("Education section accepts only existing education lines")
        education_id = block.get("education_id")
        if education_id not in actual:
            if education_id in closed:
                _fail("Education entry lines must stay together when entries are reordered")
            actual[education_id] = []
            group_order.append(education_id)
        actual[education_id].append(block.get("line_index"))
        # An entry is closed when the next block begins another canonical record.
        index = blocks.index(block)
        if index + 1 < len(blocks) and blocks[index + 1].get("education_id") != education_id:
            closed.add(education_id)
    if set(actual) != set(expected) or any(actual[record_id] != expected[record_id] for record_id in expected):
        _fail("Education entries and their source-backed lines cannot be removed or split")


def validate_resume_document(document: dict[str, Any], application: dict[str, Any],
                             plan: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed model validation; does not assert that arbitrary prose is true."""
    _validate_document_content(document, application, plan, profile)
    return {
        "valid": True,
        "schema_version": SCHEMA_VERSION,
        "application_id": document["application_id"],
        "revision_id": document["revision_id"],
        "source_reference_count": len(document["source_references"]),
        "claim_truth_semantically_verified": False,
    }


def resume_document_paragraphs(document: dict[str, Any]) -> list[str]:
    """Return the visible plain-text paragraphs defined by this model (no rendering)."""
    paragraphs: list[str] = []
    for section in document["content"]["sections"]:
        if section["title"]:
            paragraphs.append(section["title"])
        for block in section["blocks"]:
            kind = block["type"]
            if kind in {"contact_name", "contact_details", "profile_links", "summary_paragraph",
                        "project_entry", "project_link", "experience_entry", "education_line"}:
                paragraphs.append("".join(run["text"] for run in block["runs"]))
            elif kind == "skill_group":
                paragraphs.append(f"{block['label']}: " + ", ".join(item["text"] for item in block["items"]))
            elif kind == "project_bullet":
                paragraphs.append("• " + "".join(run["text"] for run in block["runs"]))
            elif kind == "project_tech_stack":
                paragraphs.append(block["label"] + ", ".join(item["text"] for item in block["items"]))
            elif kind == "experience_bullet":
                paragraphs.append("• " + "".join(run["text"] for run in block["runs"]))
            elif kind == "certification_entry":
                paragraphs.append("• " + "".join(run["text"] for run in block["runs"]))
    return paragraphs
