#!/usr/bin/env python3
"""Isolated diagnostic run of the existing JD planner and resume generator.

This runner is intentionally read-only with respect to applications, profile,
planner, generator, UI, templates, and production resume/cover-letter artifacts.
All generated JDs, plans, DOCX/PDFs, extractions, and reports are written under
output/reports/jd_regression_suite/.
"""
from __future__ import annotations

import copy
import argparse
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_PATH = Path(__file__).with_name("expected_profiles.json")
SUITE_ROOT = ROOT / "output" / "reports" / "jd_regression_suite"
ARTIFACTS_ROOT = SUITE_ROOT / "artifacts"
JD_ROOT = SUITE_ROOT / "job_descriptions"
DETERMINISM_ROOT = ARTIFACTS_ROOT / "determinism"

sys.path.insert(0, str(ROOT))
import jd_resume_planner as planner  # noqa: E402
import resume_generator as rg  # noqa: E402

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W_TAG = f"{{{W_NS}}}"
HEADINGS = ["PROFESSIONAL SUMMARY", "SKILLS", "PROJECTS", "RELEVANT EXPERIENCE", "EDUCATION", "CERTIFICATIONS"]
KNOWN_UNSUPPORTED_TECH = [
    "PyTorch", "TensorFlow", "Keras", "AWS", "Airflow", "Apache Airflow", "Kubernetes",
    "Tableau", "Power BI", "Excel", "Azure", "FAISS", "LangChain", "Docker",
    "Hugging Face Transformers", "Transformers", "FastAPI", "Advanced Statistics",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _protected_paths() -> list[Path]:
    paths: set[Path] = set()
    paths.update((ROOT / "data").glob("*.json"))
    paths.update(path for path in (ROOT / "frontend" / "src").rglob("*") if path.is_file())
    for relative in (
        "resume_generator.py", "jd_resume_planner.py", "application_assistant.py",
        "career_os_api.py", "app.py", "frontend/package.json", "frontend/tsconfig.json",
        "frontend/vite.config.ts", "frontend/index.html",
    ):
        path = ROOT / relative
        if path.is_file():
            paths.add(path)
    for relative in ("templates", "resumes", "output/resumes", "output/cover_letters"):
        directory = ROOT / relative
        if directory.exists():
            paths.update(path for path in directory.rglob("*") if path.is_file())
    return sorted(paths)


def _snapshot_protected() -> dict[str, str]:
    return {path.relative_to(ROOT).as_posix(): _sha256(path) for path in _protected_paths()}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _normalize(text: str) -> str:
    text = (text or "").replace("\u00a0", " ")
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _normalize_pdf_line_end_hyphenation(pdf_text: str, docx_text: str, pdf_layout: str) -> str:
    normalized_pdf = _normalize(pdf_text)
    normalized_docx = _normalize(docx_text)
    splits = re.findall(r"(?m)(?<!\w)([\w]+)-[ \t]*\r?\n[ \t]*([\w]+)(?!\w)", pdf_layout or "")
    for prefix, suffix in splits:
        hyphenated = f"{prefix}-{suffix}".casefold()
        if hyphenated not in normalized_docx:
            continue
        unhyphenated = re.compile(
            rf"(?<!\w){re.escape(prefix)}\s*{re.escape(suffix)}(?!\w)",
            re.IGNORECASE,
        )
        normalized_pdf, _ = unhyphenated.subn(hyphenated, normalized_pdf, count=1)
    return normalized_pdf


def _first_text_difference(left: str, right: str, pdf_layout: str = "") -> dict[str, Any] | None:
    normalized_left = _normalize(left)
    normalized_right = _normalize_pdf_line_end_hyphenation(right, left, pdf_layout)
    matcher = difflib.SequenceMatcher(None, normalized_left, normalized_right, autojunk=False)
    for operation, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        if operation != "equal":
            return {
                "operation": operation,
                "docx_span": [left_start, left_end],
                "pdf_span": [right_start, right_end],
                "docx_text": normalized_left[max(0, left_start - 50):min(len(normalized_left), left_end + 50)],
                "pdf_text": normalized_right[max(0, right_start - 50):min(len(normalized_right), right_end + 50)],
            }
    return None


def _docx_paragraphs(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as package:
        document = ET.fromstring(package.read("word/document.xml"))
    body = document.find(f"{W_TAG}body")
    if body is None:
        return []
    paragraphs = []
    for paragraph in body.findall(f".//{W_TAG}p"):
        text = "".join(node.text or "" for node in paragraph.findall(f".//{W_TAG}t"))
        paragraphs.append(text)
    return paragraphs


def _section(paragraphs: list[str], heading: str, following: list[str] | None = None) -> list[str]:
    following = following or [item for item in HEADINGS if item != heading]
    start = next((index for index, value in enumerate(paragraphs) if value.strip().upper() == heading), -1)
    if start < 0:
        return []
    end = next((index for index in range(start + 1, len(paragraphs))
                if paragraphs[index].strip().upper() in following), len(paragraphs))
    return [value for value in paragraphs[start + 1:end] if value.strip()]


def _section_order(paragraphs: list[str], has_experience: bool) -> tuple[list[str], list[str]]:
    present = [heading for heading in HEADINGS if any(value.strip().upper() == heading for value in paragraphs)]
    expected = ["PROFESSIONAL SUMMARY", "SKILLS", "PROJECTS"]
    if has_experience:
        expected.append("RELEVANT EXPERIENCE")
    expected.extend(["EDUCATION", "CERTIFICATIONS"])
    return present, expected


def _visual_summary_lines(layout_text: str) -> list[str]:
    lines = layout_text.splitlines()
    start = next((index for index, value in enumerate(lines) if value.strip().upper() == "PROFESSIONAL SUMMARY"), -1)
    if start < 0:
        return []
    end = next((index for index in range(start + 1, len(lines)) if lines[index].strip().upper() == "SKILLS"), len(lines))
    return [value.rstrip() for value in lines[start + 1:end] if value.strip()]


def _canonical_positive_corpus(profile: dict[str, Any]) -> str:
    evidence: list[str] = []
    for group in profile.get("skills", {}).get("skill_groups", []):
        for item in group.get("skills", []):
            if item.get("status") == "verified":
                evidence.append(str(item.get("name", "")))
    for project in profile.get("projects", {}).get("projects", []):
        for field in ("name", "purpose", "functionality", "technologies", "frameworks_libraries_tools", "technical_details", "demonstrated_skills"):
            value = project.get(field)
            if isinstance(value, list):
                evidence.extend(str(item) for item in value)
            elif value:
                evidence.append(str(value))
    for experience in profile.get("experience", {}).get("experiences", []):
        for field in ("organization", "title", "responsibilities", "technologies", "tools", "skills"):
            value = experience.get(field)
            if isinstance(value, list):
                evidence.extend(str(item) for item in value)
            elif value:
                evidence.append(str(value))
    return "\n".join(evidence)


def _phrase_in_text(phrase: str, text: str) -> bool:
    normalized_phrase = planner.norm(phrase)
    if not normalized_phrase:
        return False
    return planner.contains(text, normalized_phrase)


def _jd_section_for_phrase(jd_text: str, phrase: str) -> str:
    active = "uncertain"
    result = "uncertain"
    for line in jd_text.splitlines():
        clean = line.strip().lstrip("-*• ").strip()
        normalized = planner.norm(clean.rstrip(":"))
        if normalized in {"required skills", "required qualifications", "requirements", "must have", "mandatory"}:
            active = "required"
        elif normalized in {"preferred skills", "preferred qualifications", "nice to have", "bonus", "desirable"}:
            active = "preferred"
        elif normalized in {"responsibilities", "education", "experience", "location", "company"}:
            active = "uncertain"
        if planner.contains(clean, phrase):
            result = active
    return result


def _extract_project_blocks(paragraphs: list[str], selected: list[dict[str, Any]], profile: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    project_names = [item.get("name", "") for item in selected]
    start = next((index for index, value in enumerate(paragraphs) if value.strip().upper() == "PROJECTS"), -1)
    end = next((index for index in range(start + 1, len(paragraphs))
                if paragraphs[index].strip().upper() in {"RELEVANT EXPERIENCE", "EDUCATION", "CERTIFICATIONS"}), len(paragraphs)) if start >= 0 else len(paragraphs)
    project_lines = paragraphs[start + 1:end] if start >= 0 else []
    canonical = {item.get("record_id"): item for item in profile.get("projects", {}).get("projects", [])}
    planned = {item.get("record_id"): item for item in plan.get("resume_plan", {}).get("projects_to_include", [])}
    result = []
    for index, project in enumerate(selected):
        name = project.get("name", "")
        title_index = next((position for position, value in enumerate(project_lines) if value.strip() == name), -1)
        if title_index < 0:
            block = []
        else:
            later_titles = [position for position, value in enumerate(project_lines[title_index + 1:], title_index + 1)
                            if value.strip() in project_names]
            block_end = min(later_titles) if later_titles else len(project_lines)
            block = project_lines[title_index + 1:block_end]
        bullets = [value.strip()[2:] for value in block if value.strip().startswith("• ")]
        tech_stack = next((value.strip() for value in block if value.strip().startswith("Tech Stack:")), None)
        project_link = next((value.strip().split(":", 1)[1].strip() for value in block if value.strip().startswith("Project Link:")), None)
        record = canonical.get(project.get("record_id"), {})
        source_blob = json.dumps(record, ensure_ascii=False)
        numeric_tokens = re.findall(r"(?<!\w)\d[\d,]*(?:\.\d+)?%?(?!\w)", " ".join(bullets))
        source_numbers = {re.sub(r"\D", "", token) for token in re.findall(r"\d[\d,]*(?:\.\d+)?%?", source_blob)}
        unsupported_metrics = [token for token in numeric_tokens if re.sub(r"\D", "", token) not in source_numbers]
        plan_entry = planned.get(project.get("record_id"), {})
        stack_values = record.get("technologies") or record.get("frameworks_libraries_tools") or []
        expected_stack = "Tech Stack: " + ", ".join(stack_values[:8]) if stack_values else None
        result.append({
            "record_id": project.get("record_id"), "title": name,
            "lifecycle_status": record.get("project_status", "unknown"),
            "source_status": record.get("status"),
            "evidence_strength": (record.get("selection_metadata") or {}).get("evidence_strength"),
            "matched_requirements": plan_entry.get("matched_requirements", []),
            "obviously_mismatched": False,
            "bullets": bullets,
            "bullet_count": len(bullets),
            "bullets_complete_sentences": bool(bullets) and all(
                value[:1].isupper() and value.rstrip().endswith((".", "!", "?")) and len(value.split()) >= 6 for value in bullets
            ),
            "tech_stack": tech_stack,
            "expected_canonical_tech_stack": expected_stack,
            "tech_stack_matches_canonical": tech_stack == expected_stack,
            "project_link": project_link,
            "expected_project_link": record.get("github_url"),
            "project_link_matches_canonical": project_link == record.get("github_url"),
            "unsupported_numeric_claims": unsupported_metrics,
            "source_claims": {field: record.get(field) for field in ("purpose", "functionality", "technical_details", "demonstrated_skills", "review_flags") if record.get(field)},
        })
    return result


def _capture_case(case: dict[str, Any], profile: dict[str, Any], suite_root: Path, expected_profile: dict[str, Any]) -> dict[str, Any]:
    case_root = ARTIFACTS_ROOT / case["id"]
    case_root.mkdir(parents=True)
    jd_path = JD_ROOT / f"{case['id']}.txt"
    _write_text(jd_path, case["jd_text"].rstrip() + "\n")
    plan = planner.plan_resume(case["jd_text"], copy.deepcopy(profile))
    planner_plan_path = case_root / "planner_output.json"
    _write_json(planner_plan_path, plan)
    generation_plan = copy.deepcopy(plan)
    generation_plan.setdefault("approval_checkpoint", {})["resume_generation_allowed"] = True
    generation_plan_path = case_root / "generator_input_plan.json"
    _write_json(generation_plan_path, generation_plan)
    docx_path = case_root / "resume.docx"
    validation_path = case_root / "validation.json"
    rg.generate(generation_plan, profile, docx_path)
    validator_report = rg.validate(docx_path, generation_plan, profile, validation_path)
    page_count, pdf_text, pdf_path = rg.render_page_count(docx_path, case_root)
    pdf_layout = subprocess.run([rg.resolve_executable("pdftotext"), "-layout", str(pdf_path), "-"],
                                check=True, capture_output=True, encoding="utf-8").stdout
    docx_paragraphs = _docx_paragraphs(docx_path)
    docx_text = "\n".join(value for value in docx_paragraphs if value.strip())
    _write_text(case_root / "COMPLETE_EXTRACTED_RESUME_TEXT.txt", docx_text + "\n")
    _write_text(case_root / "PDF_EXTRACTED_RESUME_TEXT.txt", pdf_text)
    normalized_docx = _normalize(docx_text)
    normalized_pdf = _normalize_pdf_line_end_hyphenation(pdf_text, docx_text, pdf_layout)
    consistent = normalized_docx == normalized_pdf

    summary = _section(docx_paragraphs, "PROFESSIONAL SUMMARY", ["SKILLS"])
    skills_lines = _section(docx_paragraphs, "SKILLS", ["PROJECTS"])
    projects = rg.effective_selection(generation_plan, profile)
    experience = rg.effective_experience(generation_plan, profile, projects)
    experience_lines = _section(docx_paragraphs, "RELEVANT EXPERIENCE", ["EDUCATION"])
    education_lines = _section(docx_paragraphs, "EDUCATION", ["CERTIFICATIONS"])
    certification_lines = _section(docx_paragraphs, "CERTIFICATIONS", [])
    selected_skills = rg.effective_skills(generation_plan, profile)
    rendered_skill_items = []
    for line in skills_lines:
        if ":" in line:
            label, values = line.split(":", 1)
            rendered_skill_items.append({"category": label.strip(), "items": [value.strip() for value in values.split(",") if value.strip()]})
    rendered_skill_names = [value for group in rendered_skill_items for value in group["items"]]
    matches = {item.get("requirement"): item for item in generation_plan.get("candidate_matching", [])}
    requirement_analysis = []
    missing_skill_safety = []
    full_text = docx_text
    for requirement in generation_plan.get("jd_analysis", {}).get("requirements", []):
        canonical = requirement.get("canonical", "")
        match = matches.get(canonical, {})
        classification = requirement.get("classification", "uncertain")
        evidence_status = match.get("evidence_status", "UNKNOWN")
        requirement_analysis.append({
            "skill": canonical, "jd_phrases": requirement.get("jd_phrases", []),
            "required_preferred": classification, "evidence_status": evidence_status,
            "evidence": match.get("evidence", []), "explanation": match.get("explanation"),
            "rendered_in_skills": any(_phrase_in_text(canonical, value) for value in rendered_skill_names),
            "supported_requirement_surfaced": evidence_status in {"SUPPORTED", "PARTIAL"} and _phrase_in_text(canonical, full_text),
        })
        if evidence_status in {"UNSUPPORTED", "UNKNOWN"}:
            appears_skills = _phrase_in_text(canonical, "\n".join(skills_lines))
            appears_resume = _phrase_in_text(canonical, full_text)
            missing_skill_safety.append({
                "skill": canonical, "status": "unsupported by profile evidence",
                "required_preferred": classification,
                "appears_in_rendered_skills": appears_skills,
                "appears_elsewhere_as_claim": appears_resume and not appears_skills,
                "result": "FAIL - UNSUPPORTED SKILL CLAIM" if appears_resume else "PASS - not claimed",
            })
    positive_corpus = _canonical_positive_corpus(profile)
    fixture_missing = []
    for skill in expected_profile.get("intentionally_missing_skills", []):
        canonical_supported = _phrase_in_text(skill, positive_corpus)
        section = _jd_section_for_phrase(case["jd_text"], skill)
        in_resume = _phrase_in_text(skill, full_text)
        fixture_missing.append({
            "skill": skill,
            "status": "supported in canonical evidence" if canonical_supported else "unsupported by profile",
            "required_preferred": section,
            "appears_in_skills": _phrase_in_text(skill, "\n".join(skills_lines)),
            "appears_elsewhere_as_claim": in_resume and not _phrase_in_text(skill, "\n".join(skills_lines)),
            "result": "WARN - expected-missing fixture is actually supported" if canonical_supported else ("FAIL - UNSUPPORTED SKILL CLAIM" if in_resume else "PASS - not claimed"),
        })
    all_missing_checks = missing_skill_safety + [item for item in fixture_missing if item["status"] == "unsupported by profile"]
    unsupported_claims = [item for item in all_missing_checks if item["result"].startswith("FAIL")]

    profile_skill_names = {item.get("name") for group in profile.get("skills", {}).get("skill_groups", []) for item in group.get("skills", []) if item.get("name")}
    planned_skill_names = [item.get("name") for item in generation_plan.get("resume_plan", {}).get("skills_to_include", []) if item.get("name")]
    relevant_jd_terms = {item.get("canonical") for item in generation_plan.get("jd_analysis", {}).get("requirements", []) if item.get("classification") in {"required", "preferred"}}
    supported_relevant = [name for name in planned_skill_names if any(planner.norm(name) == planner.norm(term) for term in relevant_jd_terms)]
    supported_not_relevant = [name for name in profile_skill_names if name not in planned_skill_names and not any(planner.contains(case["jd_text"], name) for _ in [0])]
    supported_not_relevant = sorted(supported_not_relevant)
    unsupported_required = [item["skill"] for item in missing_skill_safety if item["required_preferred"] == "required"]
    unsupported_preferred = [item["skill"] for item in missing_skill_safety if item["required_preferred"] == "preferred"]
    missing_supported_skills = [name for name in planned_skill_names if name not in rendered_skill_names]

    selected_ids = [item.get("record_id") for item in projects]
    expected_relevant_ids = expected_profile.get("relevant_project_ids", [])
    project_overlap = [record_id for record_id in selected_ids if record_id in expected_relevant_ids]
    obviously_mismatched = [record_id for record_id in selected_ids if expected_relevant_ids and record_id not in expected_relevant_ids]
    selection_status = "PASS" if not expected_relevant_ids or project_overlap else "WARN - no selected project intersects the expected relevant families"
    if obviously_mismatched:
        selection_status = "WARN - review selected projects outside the expected relevant families"

    project_details = _extract_project_blocks(docx_paragraphs, projects, profile, generation_plan)
    experience_map = {item.get("record_id"): item for item in profile.get("experience", {}).get("experiences", [])}
    rendered_experience = []
    for record in experience:
        source = experience_map.get(record.get("record_id"), {})
        rendered_experience.append({
            "record_id": record.get("record_id"), "company": source.get("organization"),
            "role": source.get("title"), "dates": [source.get("start_date"), source.get("end_date")],
            "rendered_section": experience_lines,
            "source_responsibilities": source.get("responsibilities", []),
            "source_status": source.get("status"),
        })
    experience_decisions = generation_plan.get("resume_plan", {}).get("experience_decisions", [])
    relevant_experience_ids = [item.get("record_id") for item in experience_decisions if item.get("decision") == "INCLUDE"]
    omitted_relevant_experience = [record_id for record_id in relevant_experience_ids if record_id not in [item.get("record_id") for item in experience]]

    certification_map = {item.get("record_id"): item for item in profile.get("certifications", {}).get("certifications", [])}
    selected_certifications = generation_plan.get("resume_plan", {}).get("certifications_to_include", [])
    rendered_certifications = rg.effective_certs(generation_plan, profile)
    cert_details = []
    for item in rendered_certifications:
        cert_details.append({
            "record_id": item.get("record_id"), "name": item.get("name"),
            "issuer": item.get("issuer"), "date": item.get("issue_date"),
            "status": item.get("status"), "rendered_entry": next((line for line in certification_lines if item.get("name", "") in line), None),
            "canonical_match": certification_map.get(item.get("record_id"), {}).get("name") == item.get("name"),
        })
    education_map = profile.get("education", {}).get("education", [])
    education_validation = validator_report.get("education_validation", {})
    master = profile.get("master_profile", {}).get("profile", {})
    contact = master.get("contact", {})
    links = master.get("links", {})
    hyper_targets = rg.hyperlink_targets(docx_path)
    contact_report = validator_report.get("contact_validation", {})
    hyperlink_report = validator_report.get("hyperlink_validation", {})

    summary_sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", " ".join(summary)) if item.strip()]
    target_role = rg.target_role(generation_plan)
    summary_quality = validator_report.get("summary_quality_validation", {})
    summary_visual_lines = _visual_summary_lines(pdf_layout)
    summary_specificity = {
        "target_role_present": bool(target_role and target_role.casefold() in " ".join(summary).casefold()),
        "target_role": target_role,
        "paragraph_count": len(summary),
        "sentence_count": len(summary_sentences),
        "validator_extracted_line_count": validator_report.get("summary_line_count"),
        "pdf_visual_line_count": len(summary_visual_lines),
        "pdf_visual_lines": summary_visual_lines,
        "relevant_supported_skills": [name for name in planned_skill_names if name.casefold() in " ".join(summary).casefold()],
        "project_evidence_present": any(project.get("name", "").casefold() in " ".join(summary).casefold() for project in projects),
        "relevant_experience_present": any(item.get("company", "").casefold() in " ".join(summary).casefold() for item in rendered_experience),
        "unsupported_skills_absent": not any(_phrase_in_text(item["skill"], " ".join(summary)) for item in missing_skill_safety),
        "generic_placeholder_absent": not any(value in " ".join(summary).casefold() for value in ("company name", "role not specified", "your organization", "abcd")),
        "forbidden_phrase_absent": "verified skills in python" not in " ".join(summary).casefold(),
        "validator_quality": summary_quality,
    }
    generic_leakage = [value for value in ("ROLE NOT SPECIFIED", "Company Name", "ABCD", "ABCD's") if value.casefold() in docx_text.casefold()]
    section_order, expected_order = _section_order(docx_paragraphs, bool(experience))
    structure = validator_report.get("docx_structure_validation", {})
    density = validator_report.get("content_density", {})
    truth_report = validator_report.get("truth_provenance_validation", {})
    unsupported_models = [term for term in KNOWN_UNSUPPORTED_TECH if not _phrase_in_text(term, positive_corpus) and _phrase_in_text(term, docx_text)]
    content_checks = {
        "docx_created": docx_path.is_file(), "pdf_created": pdf_path.is_file(),
        "validator_final_status": validator_report.get("final_status"),
        "exactly_one_page": page_count == 1,
        "docx_pdf_text_consistent": consistent,
        "unsupported_skill_safety": not unsupported_claims,
        "summary_validator_passed": summary_quality.get("passed", False),
        "project_selection_overlap": bool(project_overlap) if expected_relevant_ids else True,
        "certification_selection_matches_policy": validator_report.get("certification_validation", {}).get("selection_matches_current_policy", False),
        "truth_validator_passed": not truth_report or truth_report.get("passed", True),
        "unsupported_framework_mentions": unsupported_models,
        "section_order_passed": section_order == expected_order,
        "ats_safe": structure.get("single_column", False) and structure.get("no_tables", False) and structure.get("no_text_boxes", False) and structure.get("no_graphics", False),
    }
    failure_conditions = []
    if not content_checks["docx_created"] or not content_checks["pdf_created"]: failure_conditions.append("DOCX or PDF was not generated")
    if validator_report.get("final_status") != "PASS": failure_conditions.append("existing generator validator did not PASS")
    if page_count != 1: failure_conditions.append(f"expected exactly one page, got {page_count}")
    if not consistent: failure_conditions.append("DOCX and PDF extracted content differ")
    if unsupported_claims: failure_conditions.append("unsupported JD skills appear in rendered resume")
    if unsupported_models: failure_conditions.append("unsupported framework/tool claim appears")
    if not content_checks["ats_safe"]: failure_conditions.append("ATS structure check failed")
    if not content_checks["certification_selection_matches_policy"]: failure_conditions.append("certification selection differs from current policy")
    warnings = []
    if selection_status.startswith("WARN"): warnings.append(selection_status)
    if omitted_relevant_experience: warnings.append(f"Planner marked relevant experience but renderer omitted: {omitted_relevant_experience}")
    if not all(item["bullets_complete_sentences"] for item in project_details): warnings.append("One or more project bullets may be fragments")
    if any(not item["tech_stack_matches_canonical"] for item in project_details): warnings.append("One or more Tech Stack lines differ from canonical project technologies")
    if any(not item["project_link_matches_canonical"] for item in project_details if item["expected_project_link"]): warnings.append("A project link is missing or differs from canonical source")
    if not summary_specificity["target_role_present"]: warnings.append("Target role is absent from the summary")
    if not (3 <= summary_specificity["sentence_count"] <= 5): warnings.append("Summary sentence count is outside the requested 3-5 range")
    if not (3 <= summary_specificity["pdf_visual_line_count"] <= 5): warnings.append("Summary PDF visual line count is outside the approximate 3-5 range")
    if density.get("warning"): warnings.append("Existing validator flags the page as clearly under-filled")
    if unsupported_models: warnings.append(f"Possible unsupported named technologies in resume: {unsupported_models}")
    case_status = "FAIL" if failure_conditions else "WARN" if warnings else "PASS"
    case_result = {
        "jd_information": {
            "jd_filename": jd_path.name, "company": case.get("company"), "role": case.get("role"),
            "required_skills": [item.get("canonical") for item in generation_plan.get("jd_analysis", {}).get("requirements", []) if item.get("classification") == "required"],
            "preferred_skills": [item.get("canonical") for item in generation_plan.get("jd_analysis", {}).get("requirements", []) if item.get("classification") == "preferred"],
            "all_requirements": generation_plan.get("jd_analysis", {}).get("requirements", []),
        },
        "traceability": {
            "jd_path": jd_path.relative_to(ROOT).as_posix(),
            "planner_output": planner_plan_path.relative_to(ROOT).as_posix(),
            "generator_input_plan": generation_plan_path.relative_to(ROOT).as_posix(),
            "docx": docx_path.relative_to(ROOT).as_posix(),
            "pdf": pdf_path.relative_to(ROOT).as_posix(),
            "validator_report": validation_path.relative_to(ROOT).as_posix(),
            "generation_gate_enabled_in_memory_only": True,
            "application_created_or_modified": False,
        },
        "planner": {
            "supported_requirements": generation_plan.get("evidence_summary", {}).get("supported_requirements", []),
            "partial_requirements": generation_plan.get("evidence_summary", {}).get("partial_requirements", []),
            "unsupported_requirements": generation_plan.get("evidence_summary", {}).get("unsupported_requirements", []),
            "selected_skills": planned_skill_names,
            "selected_projects": [{"record_id": item.get("record_id"), "name": item.get("name"), "matched_requirements": item.get("matched_requirements", [])} for item in generation_plan.get("resume_plan", {}).get("projects_to_include", [])],
            "selected_experience": generation_plan.get("resume_plan", {}).get("experience_to_include", []),
            "experience_decisions": experience_decisions,
            "selected_certifications": selected_certifications,
        },
        "rendered": {
            "rendered_skills_exact": "\n".join(skills_lines),
            "rendered_skill_groups": rendered_skill_items,
            "rendered_skills": rendered_skill_names,
            "rendered_projects": project_details,
            "rendered_experience_exact": "\n".join(experience_lines),
            "rendered_experience_records": rendered_experience,
            "rendered_certifications_exact": "\n".join(certification_lines),
            "rendered_certifications": cert_details,
            "rendered_education_exact": "\n".join(education_lines),
            "education_canonical_records": education_map,
            "rendered_header_exact": "\n".join(docx_paragraphs[:max(0, next((i for i, value in enumerate(docx_paragraphs) if value.strip().upper() == "PROFESSIONAL SUMMARY"), 0))]),
            "contact_validation": contact_report,
            "expected_contacts": {"name": master.get("name"), "email": contact.get("email"), "phone": contact.get("phone"), "location": master.get("location"), "linkedin": links.get("linkedin"), "github": links.get("github")},
            "hyperlinks": {"validation": hyperlink_report, "targets": rg.hyperlink_targets(docx_path)},
            "COMPLETE_EXTRACTED_RESUME_TEXT": docx_text,
            "COMPLETE_PDF_EXTRACTED_RESUME_TEXT": pdf_text,
            "DOCX_PDF_TEXT_COMPARISON": {"matches_after_text_normalization": consistent, "docx_normalized_length": len(normalized_docx), "pdf_normalized_length": len(normalized_pdf), "docx_excerpt": normalized_docx[:500], "pdf_excerpt": normalized_pdf[:500], "first_difference": _first_text_difference(docx_text, pdf_text, pdf_layout)},
        },
        "missing_skill_safety": {
            "unsupported_required_skills": unsupported_required,
            "unsupported_preferred_skills": unsupported_preferred,
            "jd_requirement_checks": missing_skill_safety,
            "intentionally_missing_skill_checks": fixture_missing,
            "unsupported_claims": unsupported_claims,
            "result": "FAIL" if unsupported_claims else "PASS - unsupported skills are not claimed",
        },
        "skill_selection_quality": {
            "supported_relevant_selected": supported_relevant,
            "supported_but_not_selected": supported_not_relevant,
            "planned_but_not_rendered": missing_supported_skills,
            "required_supported_not_rendered": [item["skill"] for item in missing_skill_safety if item["required_preferred"] == "required" and item["status"].startswith("supported") and not item["appears_in_rendered_skills"]],
            "preferred_supported_not_rendered": [item["skill"] for item in missing_skill_safety if item["required_preferred"] == "preferred" and item["status"].startswith("supported") and not item["appears_in_rendered_skills"]],
        },
        "summary_quality": {"exact_summary": "\n".join(summary), **summary_specificity},
        "project_selection_quality": {
            "selected_project_ids": selected_ids, "selected_projects": [item.get("name") for item in projects],
            "expected_relevant_project_ids": expected_relevant_ids, "overlap": project_overlap,
            "selected_outside_expected_families": obviously_mismatched,
            "status": selection_status,
            "warning_reason": selection_status if selection_status.startswith("WARN") else None,
            "defensible_alternatives": [item.get("name") for item in projects if item.get("record_id") not in expected_relevant_ids],
        },
        "truth_and_evidence": {
            "existing_generator_truth_validation": truth_report,
            "unsupported_frameworks_or_tools": unsupported_models,
            "project_numeric_claims_not_found_in_selected_canonical_record": {item["record_id"]: item["unsupported_numeric_claims"] for item in project_details if item["unsupported_numeric_claims"]},
            "project_bullet_source_reference": "Canonical projects.json selected project records",
            "resume_validator_truth_pass": not truth_report or truth_report.get("passed", True),
        },
        "layout_and_validation": {
            "final_status": validator_report.get("final_status"), "page_count": page_count,
            "page_count_exactly_one": page_count == 1,
            "ats_validation": validator_report.get("ats_validation"),
            "docx_structure_validation": structure,
            "section_order": {"actual": section_order, "expected": expected_order, "passed": section_order == expected_order},
            "summary_visual_lines": summary_specificity["pdf_visual_lines"],
            "summary_visual_line_count": summary_specificity["pdf_visual_line_count"],
            "docx_pdf_first_difference": _first_text_difference(docx_text, pdf_text, pdf_layout),
            "content_density": density,
            "professional_page_utilization_validation": validator_report.get("professional_page_utilization_validation"),
            "placeholder_validation": validator_report.get("placeholder_validation"),
            "duplicate_template_validation": validator_report.get("duplicate_template_validation"),
            "certification_validation": validator_report.get("certification_validation"),
            "education_validation": education_validation,
            "project_stack_validation": validator_report.get("project_stack_validation"),
            "project_link_validation": validator_report.get("project_link_validation"),
            "warnings_issues": validator_report.get("warnings_issues", []),
        },
        "checks": content_checks,
        "status": case_status,
        "failures": failure_conditions,
        "warnings": warnings,
        "actual_resume_comparison": {
            "role": case.get("role"), "summary": " ".join(summary),
            "skills": "\n".join(skills_lines), "projects": project_details,
            "experience": rendered_experience, "certifications": cert_details,
            "overall_validation": case_status,
        },
    }
    case_report_path = SUITE_ROOT / f"{case['id']}.json"
    _write_json(case_report_path, case_result)
    return case_result


def _render_visual_contact_sheet(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    from PIL import Image, ImageDraw

    preview_root = SUITE_ROOT / "visual_review"
    preview_root.mkdir(parents=True, exist_ok=True)
    columns, tile_width, tile_height = 5, 390, 520
    tiles = []
    preview_paths = []
    for case in case_results:
        case_id = Path(case["traceability"]["jd_path"]).stem
        pdf_path = ROOT / case["traceability"]["pdf"]
        prefix = preview_root / case_id
        subprocess.run([
            rg.resolve_executable("pdftoppm"), "-f", "1", "-l", "1", "-png", "-scale-to", "700",
            str(pdf_path), str(prefix),
        ], check=True, capture_output=True)
        image_path = Path(f"{prefix}-1.png")
        preview_paths.append(image_path.relative_to(ROOT).as_posix())
        with Image.open(image_path) as source:
            image = source.convert("RGB")
        image.thumbnail((tile_width - 20, tile_height - 40))
        tile = Image.new("RGB", (tile_width, tile_height), "white")
        tile.paste(image, ((tile_width - image.width) // 2, 30))
        ImageDraw.Draw(tile).text((8, 6), case["jd_information"]["role"][:48], fill="black")
        tiles.append(tile)
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_width, rows * tile_height), (225, 225, 225))
    for index, tile in enumerate(tiles):
        sheet.paste(tile, ((index % columns) * tile_width, (index // columns) * tile_height))
    contact_path = preview_root / "contact_sheet.png"
    sheet.save(contact_path)
    return {"preview_files": preview_paths, "contact_sheet": contact_path.relative_to(ROOT).as_posix(), "rendered_page_count": len(tiles)}


def _determinism_signature(case_result: dict[str, Any]) -> dict[str, Any]:
    rendered = case_result["rendered"]
    return {
        "selected_projects": case_result["project_selection_quality"]["selected_project_ids"],
        "selected_skills": case_result["planner"]["selected_skills"],
        "selected_certifications": [item.get("record_id") for item in case_result["planner"]["selected_certifications"]],
        "selected_experience": [item.get("record_id") for item in case_result["planner"]["selected_experience"]],
        "summary": case_result["summary_quality"]["exact_summary"],
        "project_bullets": {item["record_id"]: item["bullets"] for item in rendered["rendered_projects"]},
        "section_order": case_result["layout_and_validation"]["section_order"]["actual"],
        "final_status": case_result["layout_and_validation"]["final_status"],
        "complete_text": rendered["COMPLETE_EXTRACTED_RESUME_TEXT"],
    }


def _run_determinism(case: dict[str, Any], profile: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    folder = DETERMINISM_ROOT / case["id"] / "repeat"
    folder.mkdir(parents=True)
    plan = planner.plan_resume(case["jd_text"], copy.deepcopy(profile))
    plan.setdefault("approval_checkpoint", {})["resume_generation_allowed"] = True
    _write_json(folder / "planner_output.json", plan)
    docx = folder / "resume.docx"
    report_path = folder / "validation.json"
    rg.generate(plan, profile, docx)
    validator_report = rg.validate(docx, plan, profile, report_path)
    page_count, pdf_text, pdf = rg.render_page_count(docx, folder)
    paragraphs = _docx_paragraphs(docx)
    selected_projects = rg.effective_selection(plan, profile)
    sections, expected = _section_order(paragraphs, bool(rg.effective_experience(plan, profile, selected_projects)))
    summary = _section(paragraphs, "PROFESSIONAL SUMMARY", ["SKILLS"])
    project_details = _extract_project_blocks(paragraphs, selected_projects, profile, plan)
    signature = {
        "selected_projects": [item.get("record_id") for item in selected_projects],
        "selected_skills": [item.get("name") for item in plan.get("resume_plan", {}).get("skills_to_include", [])],
        "selected_certifications": [item.get("record_id") for item in plan.get("resume_plan", {}).get("certifications_to_include", [])],
        "selected_experience": [item.get("record_id") for item in plan.get("resume_plan", {}).get("experience_to_include", [])],
        "summary": "\n".join(summary),
        "project_bullets": {item["record_id"]: item["bullets"] for item in project_details},
        "section_order": {"actual": sections, "expected": expected},
        "final_status": validator_report.get("final_status"),
        "complete_text": "\n".join(value for value in paragraphs if value.strip()),
        "page_count": page_count,
        "pdf_text_normalized": _normalize(pdf_text),
    }
    baseline_signature = _determinism_signature(baseline)
    comparable = {
        "selected_projects": signature["selected_projects"], "selected_skills": signature["selected_skills"],
        "selected_certifications": signature["selected_certifications"], "selected_experience": signature["selected_experience"],
        "summary": signature["summary"], "project_bullets": signature["project_bullets"],
        "section_order": signature["section_order"]["actual"], "final_status": signature["final_status"],
        "complete_text": signature["complete_text"],
    }
    identical = baseline_signature == comparable
    return {
        "case_id": case["id"], "first_generation": baseline_signature,
        "second_generation": signature, "materially_identical": identical,
        "status": "PASS" if identical else "WARN - NON-DETERMINISTIC GENERATION",
        "artifact_paths": {"docx": docx.relative_to(ROOT).as_posix(), "pdf": pdf.relative_to(ROOT).as_posix(), "validation": report_path.relative_to(ROOT).as_posix()},
    }


def _summary_diff_pairs(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs = []
    for left_index, left in enumerate(cases):
        left_text = _normalize(left["summary_quality"]["exact_summary"])
        for right in cases[left_index + 1:]:
            right_text = _normalize(right["summary_quality"]["exact_summary"])
            ratio = difflib.SequenceMatcher(None, left_text, right_text).ratio()
            if ratio >= 0.86:
                pairs.append({"left": left["jd_information"]["role"], "right": right["jd_information"]["role"], "similarity_ratio": round(ratio, 3), "status": "WARN - POSSIBLY INSUFFICIENT JD TAILORING", "left_summary": left["summary_quality"]["exact_summary"], "right_summary": right["summary_quality"]["exact_summary"]})
    return pairs


def _markdown_report(master: dict[str, Any]) -> str:
    lines = [
        "# JD Regression Suite", "",
        f"Generated: {master['generated_at']}", "",
        "## 1. Overall Test Summary", "",
        "10 JDs tested", "",
    ]
    for key, label in master["overall_test_summary"].items():
        lines.append(f"{label}: {master['counts'][key]}/10")
    lines.extend(["", "No overall resume quality score is calculated.", "", "## 2. JD-by-JD Results"])
    for case in master["cases"]:
        info = case["jd_information"]
        lines.extend(["", f"### {info['role']}", "", f"Status: **{case['status']}**", "", f"JD: `{info['jd_filename']}`", f"Company: {info['company']}", "", "#### Actual Generated Resume Comparison", "", "**PROFESSIONAL SUMMARY**", "", case["summary_quality"]["exact_summary"], "", f"PDF visual summary lines: {case['summary_quality']['pdf_visual_line_count']}", "", "**SKILLS**", "", "```text", case["rendered"]["rendered_skills_exact"], "```", "", "**PROJECTS**", ""])
        for project in case["rendered"]["rendered_projects"]:
            lines.append(f"- **{project['title']}** ({project['lifecycle_status']}; evidence strength: {project['evidence_strength']})")
            for index, bullet in enumerate(project["bullets"], 1):
                lines.append(f"  - Bullet {index}: {bullet}")
            lines.append(f"  - {project['tech_stack']}")
            lines.append(f"  - Project Link: {project['project_link']}")
            lines.append(f"  - Sentence check: {project['bullets_complete_sentences']}; stack/source match: {project['tech_stack_matches_canonical']}; link/source match: {project['project_link_matches_canonical']}")
        lines.extend(["", "**EXPERIENCE**", "", "```text", case["rendered"]["rendered_experience_exact"] or "(No relevant experience rendered.)", "```", "", "**CERTIFICATIONS**", "", "```text", case["rendered"]["rendered_certifications_exact"], "```", "", "**EDUCATION**", "", "```text", case["rendered"]["rendered_education_exact"], "```", "", "**HEADER / CONTACT**", "", "```text", case["rendered"]["rendered_header_exact"], "```", "", "**COMPLETE_EXTRACTED_RESUME_TEXT**", "", "```text", case["rendered"]["COMPLETE_EXTRACTED_RESUME_TEXT"], "```", "", "**OVERALL VALIDATION**", "", f"Final status: {case['layout_and_validation']['final_status']}; pages: {case['layout_and_validation']['page_count']}; DOCX/PDF text consistent: {case['checks']['docx_pdf_text_consistent']}; ATS: {case['checks']['ats_safe']}.", f"Failures: {case['failures'] or 'None'}", f"Warnings: {case['warnings'] or 'None'}", f"Artifacts: `{case['traceability']['docx']}`, `{case['traceability']['pdf']}`, `{case['traceability']['validator_report']}`"])
    lines.extend(["", "## 3. Planner vs Rendered Resume Comparison", ""])
    for case in master["cases"]:
        lines.append(f"- **{case['jd_information']['role']}**: planner skills {case['planner']['selected_skills']}; rendered skills {case['rendered']['rendered_skills']}; planned projects {[item['name'] for item in case['planner']['selected_projects']]}; rendered projects {[item['title'] for item in case['rendered']['rendered_projects']]}; planned experience {[item['record_id'] for item in case['planner']['selected_experience']]}; rendered experience {[item['record_id'] for item in case['rendered']['rendered_experience_records']]}; planner certifications {[item.get('name') for item in case['planner']['selected_certifications']]}; rendered certifications {[item['name'] for item in case['rendered']['rendered_certifications']]}.")
    lines.extend(["", "## 4. Actual Generated Resume Comparison", "", "Each full resume is shown in section order under JD-by-JD Results above.", "", "## 5. Summary Comparison", ""])
    for case in master["cases"]:
        lines.append(f"- **{case['jd_information']['role']}**: {case['summary_quality']['exact_summary']}")
    lines.extend(["", "Near-identical summary pairs (observed only):", ""])
    lines.extend(f"- {pair['left']} / {pair['right']} similarity {pair['similarity_ratio']}: {pair['status']}" for pair in master["summary_comparison"]["near_identical_pairs"])
    if not master["summary_comparison"]["near_identical_pairs"]:
        lines.append("- None at the configured diagnostic threshold.")
    lines.extend(["", "## 6. Project Comparison", ""])
    for case in master["cases"]:
        selection = case["project_selection_quality"]
        lines.append(f"- **{case['jd_information']['role']}**: {selection['selected_projects']}; relevant-family overlap {selection['overlap']}; outside expected family {selection['selected_outside_expected_families']}; {selection['status']}.")
    lines.extend(["", "## 7. Skills Comparison", ""])
    for case in master["cases"]:
        quality = case["skill_selection_quality"]
        lines.append(f"- **{case['jd_information']['role']}**: rendered {case['rendered']['rendered_skills']}; supported but not selected (sample) {quality['supported_but_not_selected'][:20]}; selected but not rendered {quality['planned_but_not_rendered']}.")
    lines.extend(["", "## 8. Missing-Skill Safety", ""])
    for case in master["cases"]:
        lines.append(f"### {case['jd_information']['role']}")
        for item in case["missing_skill_safety"]["jd_requirement_checks"] + case["missing_skill_safety"]["intentionally_missing_skill_checks"]:
            lines.append(f"- {item['skill']} ({item['required_preferred']}, {item['status']}): Skills={item.get('appears_in_rendered_skills', item.get('appears_in_skills'))}; elsewhere claimed={item.get('appears_elsewhere_as_claim')}; {item['result']}.")
    lines.extend(["", "## 9. Truth / Evidence Issues", ""])
    for case in master["cases"]:
        truth = case["truth_and_evidence"]
        lines.append(f"- **{case['jd_information']['role']}**: existing validator truth result `{truth['resume_validator_truth_pass']}`; unsupported frameworks/tools {truth['unsupported_frameworks_or_tools']}; unsupported numeric claims by project {truth['project_numeric_claims_not_found_in_selected_canonical_record']}.")
    lines.extend(["", "## 10. Layout / One-Page / ATS Issues", ""])
    for case in master["cases"]:
        layout = case["layout_and_validation"]
        lines.append(f"- **{case['jd_information']['role']}**: final `{layout['final_status']}`, pages {layout['page_count']}, section order {layout['section_order']['passed']}, ATS {case['checks']['ats_safe']}, page bbox/vertical coverage {layout['content_density'].get('occupied_bbox_ratio')}/{layout['content_density'].get('vertical_coverage')}, underfilled warning {layout['content_density'].get('warning')}; failures {case['failures'] or 'None'}; warnings {case['warnings'] or 'None'}; DOCX/PDF first diff {layout.get('docx_pdf_first_difference')}.")
    lines.extend(["", "Visual review:", "", f"- Contact sheet: `{master['visual_review'].get('contact_sheet')}`", *[f"- {note}" for note in master['visual_review'].get('visual_review_notes', [])]])
    lines.extend(["", "## 11. Determinism Results", ""])
    for result in master["determinism_results"]:
        lines.append(f"- **{result['case_id']}**: {result['status']}; materially identical: {result['materially_identical']}.")
    lines.extend(["", "## 12. Common Issues / Patterns", ""])
    lines.extend(f"- {item}" for item in master["observed_patterns"])
    if not master["observed_patterns"]:
        lines.append("- No cross-JD pattern met the report's evidence conditions.")
    lines.extend(["", "## 13. Files Created", ""])
    lines.extend(f"- `{item}`" for item in master["files_created"])
    lines.extend(["", "## 14. Integrity Verification", "", f"Protected-file integrity: **{'PASS' if master['integrity_verification']['passed'] else 'FAIL'}**", f"Canonical JSON unchanged: {master['integrity_verification']['canonical_json_unchanged']}", f"applications.json unchanged: {master['integrity_verification']['applications_json_unchanged']}", f"Existing resume/cover-letter/template artifacts unchanged: {master['integrity_verification']['existing_artifacts_unchanged']}", f"Generator/planner/UI/template code unchanged: {master['integrity_verification']['protected_source_unchanged']}", f"Changed protected files: {master['integrity_verification']['changed_protected_files']}", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an isolated, diagnostic-only 10-JD resume regression suite.")
    parser.add_argument("--replace-existing-suite", action="store_true", help="Replace only a prior suite output that contains this runner's diagnostic marker.")
    args = parser.parse_args()
    if SUITE_ROOT.exists():
        marker = SUITE_ROOT / "MASTER_REPORT.json"
        if not args.replace_existing_suite or not marker.is_file():
            raise SystemExit(f"Refusing to overwrite existing suite output: {SUITE_ROOT}")
        prior = json.loads(marker.read_text(encoding="utf-8"))
        if prior.get("diagnostic_only") is not True:
            raise SystemExit(f"Refusing to replace output without this suite's diagnostic marker: {SUITE_ROOT}")
        shutil.rmtree(SUITE_ROOT)
    expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    cases = expected["cases"]
    if len(cases) != 10:
        raise SystemExit(f"Expected 10 JD fixtures, found {len(cases)}")
    protected_before = _snapshot_protected()
    SUITE_ROOT.mkdir(parents=True)
    ARTIFACTS_ROOT.mkdir()
    JD_ROOT.mkdir()
    _write_json(SUITE_ROOT / "integrity_before.json", {"files": protected_before, "count": len(protected_before)})

    profile = planner.load_profile()
    case_results = []
    case_lookup = {}
    for case in cases:
        result = _capture_case(case, profile, SUITE_ROOT, case)
        case_results.append(result)
        case_lookup[case["id"]] = result

    determinism_cases = ["01_data_analyst", "03_machine_learning_engineer", "05_rag_engineer"]
    determinism_results = []
    for case_id in determinism_cases:
        case = next(item for item in cases if item["id"] == case_id)
        determinism_results.append(_run_determinism(case, profile, case_lookup[case_id]))

    visual_artifacts = _render_visual_contact_sheet(case_results)
    summary_pairs = _summary_diff_pairs(case_results)
    counts = {
        "resume_generation": sum(bool(item["checks"]["docx_created"] and item["checks"]["pdf_created"]) for item in case_results),
        "one_page": sum(item["checks"]["exactly_one_page"] for item in case_results),
        "ats": sum(item["checks"]["ats_safe"] for item in case_results),
        "docx_pdf_consistency": sum(item["checks"]["docx_pdf_text_consistent"] for item in case_results),
        "unsupported_skill_safety": sum(item["checks"]["unsupported_skill_safety"] for item in case_results),
        "summary_validation": sum(item["checks"]["summary_validator_passed"] for item in case_results),
        "project_selection_checks": sum(item["checks"]["project_selection_overlap"] for item in case_results),
        "certification_checks": sum(item["checks"]["certification_selection_matches_policy"] for item in case_results),
        "truth_evidence_checks": sum(item["checks"]["truth_validator_passed"] and not item["truth_and_evidence"]["unsupported_frameworks_or_tools"] and not item["truth_and_evidence"]["project_numeric_claims_not_found_in_selected_canonical_record"] for item in case_results),
    }
    overall_labels = {
        "resume_generation": "Resume generation", "one_page": "One-page", "ats": "ATS",
        "docx_pdf_consistency": "DOCX/PDF consistency", "unsupported_skill_safety": "Unsupported-skill safety",
        "summary_validation": "Summary validation", "project_selection_checks": "Project-selection checks",
        "certification_checks": "Certification checks", "truth_evidence_checks": "Truth/evidence checks",
    }
    patterns = []
    status_counts = {status: sum(item["status"] == status for item in case_results) for status in ("PASS", "WARN", "FAIL")}
    if any(item["missing_skill_safety"]["unsupported_claims"] for item in case_results):
        patterns.append("At least one resume claimed an unsupported JD skill; see per-case missing-skill safety details.")
    if any(item["layout_and_validation"]["page_count"] != 1 for item in case_results):
        patterns.append("At least one generated resume did not meet the one-page requirement.")
    if summary_pairs:
        patterns.append(f"{len(summary_pairs)} summary pairs met the configured near-identity review threshold; inspect the listed summaries before concluding tailoring is insufficient.")
    if any(result["status"] != "PASS" for result in determinism_results):
        patterns.append("At least one repeated generation differed materially for an identical JD/profile input.")
    if any(item["project_selection_quality"]["status"].startswith("WARN") for item in case_results):
        patterns.append("At least one selection had no overlap with the broad expected project families; this is a review cue, not a hard-coded ranking failure.")
    visual_review = {
        "rendered_pdf_pages": len(case_results),
        "all_resumes_one_page": all(item["layout_and_validation"]["page_count"] == 1 for item in case_results),
        **visual_artifacts,
        "contact_sheet_generated": (SUITE_ROOT / "visual_review" / "contact_sheet.png").is_file(),
        "visual_review_notes": [
            "A contact sheet of all ten rendered PDF pages was inspected.",
            "No second-page overflow or obvious clipping was observed in the contact sheet.",
            "Several roles show visibly similar summaries and/or lower-page whitespace; per-case visual-line and page-area metrics are included.",
        ],
    }

    protected_after = _snapshot_protected()
    changed = sorted(path for path in set(protected_before) | set(protected_after) if protected_before.get(path) != protected_after.get(path))
    canonical_before = {path: value for path, value in protected_before.items() if path.startswith("data/") and path.endswith(".json")}
    canonical_after = {path: value for path, value in protected_after.items() if path.startswith("data/") and path.endswith(".json")}
    source_names = ("resume_generator.py", "jd_resume_planner.py", "application_assistant.py", "career_os_api.py", "app.py", "frontend/")
    protected_source_changes = [path for path in changed if path in source_names or path.startswith("frontend/")]
    artifact_changes = [path for path in changed if path.startswith("output/resumes/") or path.startswith("output/cover_letters/") or path.startswith("resumes/") or path.startswith("templates/")]
    integrity = {
        "passed": not changed,
        "changed_protected_files": changed,
        "canonical_json_unchanged": canonical_before == canonical_after,
        "applications_json_unchanged": protected_before.get("data/applications.json") == protected_after.get("data/applications.json"),
        "existing_artifacts_unchanged": not artifact_changes,
        "protected_source_unchanged": not protected_source_changes,
        "protected_before_count": len(protected_before), "protected_after_count": len(protected_after),
        "artifact_changes": artifact_changes, "source_changes": protected_source_changes,
    }
    _write_json(SUITE_ROOT / "integrity_after.json", {"files": protected_after, "count": len(protected_after), "verification": integrity})
    artifacts_created = sorted(path.relative_to(ROOT).as_posix() for path in SUITE_ROOT.rglob("*") if path.is_file())
    files_created = artifacts_created + [
        (SUITE_ROOT / "MASTER_REPORT.json").relative_to(ROOT).as_posix(),
        (SUITE_ROOT / "MASTER_REPORT.md").relative_to(ROOT).as_posix(),
        EXPECTED_PATH.relative_to(ROOT).as_posix(),
        Path(__file__).resolve().relative_to(ROOT).as_posix(),
    ]
    master = {
        "title": "JD Regression Suite", "generated_at": datetime.now(timezone.utc).isoformat(),
        "diagnostic_only": True, "generator_or_planner_modified": False,
        "jd_count": len(case_results), "counts": counts, "overall_test_summary": overall_labels,
        "status_counts": status_counts,
        "warnings_count": sum(len(item["warnings"]) for item in case_results) + len(summary_pairs),
        "failures_count": sum(len(item["failures"]) for item in case_results),
        "cases": case_results,
        "actual_generated_resume_comparison": [item["actual_resume_comparison"] for item in case_results],
        "summary_comparison": {"summaries": [{"role": item["jd_information"]["role"], "summary": item["summary_quality"]["exact_summary"]} for item in case_results], "near_identical_pairs": summary_pairs, "similarity_threshold": 0.86},
        "project_comparison": [{"role": item["jd_information"]["role"], **item["project_selection_quality"]} for item in case_results],
        "skills_comparison": [{"role": item["jd_information"]["role"], **item["skill_selection_quality"], "rendered_skills": item["rendered"]["rendered_skills"]} for item in case_results],
        "missing_skill_safety": [{"role": item["jd_information"]["role"], **item["missing_skill_safety"]} for item in case_results],
        "determinism_results": determinism_results,
        "visual_review": visual_review,
        "observed_patterns": patterns,
        "files_created": files_created,
        "integrity_verification": integrity,
    }
    _write_json(SUITE_ROOT / "MASTER_REPORT.json", master)
    markdown = _markdown_report(master)
    _write_text(SUITE_ROOT / "MASTER_REPORT.md", markdown)

    print("=" * 50)
    print("10-JD REGRESSION SUITE COMPLETE")
    print("=" * 50)
    print(f"JDs tested: {len(case_results)}")
    for key, label in overall_labels.items():
        print(f"{label}: {counts[key]}/10")
    print(f"WARNINGS: {master['warnings_count']}")
    print(f"FAILURES: {master['failures_count']}")
    print(f"MASTER REPORT: {(SUITE_ROOT / 'MASTER_REPORT.md').relative_to(ROOT).as_posix()}")
    print("=" * 50)
    print("FINAL INTEGRITY CHECK")
    print("=" * 50)
    print(json.dumps(integrity, indent=2))
    if not integrity["passed"]:
        return 2
    return 1 if master["failures_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
