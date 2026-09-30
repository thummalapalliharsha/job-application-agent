"""Deterministic save-time policy checks for source-backed ResumeDocument edits.

This module deliberately does not claim to understand or prove semantic truth.
It blocks unsupported new vocabulary, quantities, technologies, and protected
structure while retaining the model's exact source-reference requirements.
"""
from __future__ import annotations

import re
from typing import Any

import resume_document_model as rdm

_WORD_RE = re.compile(r"\d[\d,]*(?:\.\d+)?%?|[a-z]+(?:['’][a-z]+)?", re.IGNORECASE)

# Function words and non-assertive connective words are allowed in a paraphrase.
# New content-bearing words must already occur in the baseline block or in the
# canonical record(s) cited by that block. This is intentionally conservative.
_SAFE_GRAMMAR = frozenset("""
a an and are as at be been being but by can could did do does doing down during
 each few for from further had has have having he her hers herself him himself
 his how i if in into is it its itself just more most my myself no nor not of
 off on once only or other our ours ourselves out over own same she should so
 some such than that the their theirs them themselves then there these they
 this those through to too under until up very was we were what when where which
 while who whom why will with would you your yours yourself yourselves also either
 neither both each every all any about after before below between beyond per via
 using used use
""".split())


def _text(block: dict[str, Any]) -> str:
    return "".join(run.get("text", "") for run in block.get("runs", []) if isinstance(run, dict))


def _tokens(text: str) -> set[str]:
    result = set()
    for token in _WORD_RE.findall(text or ""):
        normalized = token.casefold().replace(",", "")
        if normalized:
            result.add(normalized)
    return result


def _scalar_text(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, str):
        values.append(value)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        values.append(str(value))
    elif isinstance(value, dict):
        for child in value.values():
            values.extend(_scalar_text(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            values.extend(_scalar_text(child))
    return values


def _source_record(ref: dict[str, str], profile: dict[str, Any]) -> Any:
    kind, source_id = ref["source_type"], ref["source_id"]
    if kind == "profile_field":
        return rdm._profile_value(profile, source_id)
    if kind == "skill":
        return rdm._resolve_skill_source(source_id, profile) or {}
    files = {
        "project": "projects",
        "experience": "experience",
        "education": "education",
        "certification": "certifications",
    }
    container = files.get(kind)
    if not container:
        return {}
    root = profile.get(container, {})
    key = {"projects": "projects", "experience": "experiences", "education": "education", "certifications": "certifications"}[container]
    records = root.get(key, []) if isinstance(root, dict) else []
    id_key = "record_id"
    return next((record for record in records if isinstance(record, dict) and record.get(id_key) == source_id), {})


def _blocks(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {block["id"]: block for section in document["content"]["sections"] for block in section["blocks"]}


def _skill_items(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for section in document["content"]["sections"]
            if section.get("type") == "skills" for block in section["blocks"]
            if block.get("type") == "skill_group" for item in block.get("items", [])}


def _unsupported_vocabulary(text: str, original_text: str, refs: list[dict[str, str]], profile: dict[str, Any]) -> list[str]:
    evidence = set(_SAFE_GRAMMAR)
    evidence.update(_tokens(original_text))
    try:
        for ref in refs:
            evidence.update(token for value in _scalar_text(_source_record(ref, profile)) for token in _tokens(value))
    except (KeyError, TypeError, ValueError):
        return ["<unresolvable source>"]
    return sorted(_tokens(text) - evidence)


def validate_edit_policy(candidate: dict[str, Any], baseline: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Reject structural/protected edits and new factual vocabulary without provenance.

    The ResumeDocument model validator must run before this function. The
    baseline must be a freshly loaded, approved ResumeDocument for the same app.
    """
    errors: list[dict[str, str]] = []
    base_sections = {section["id"]: section for section in baseline["content"]["sections"]}
    candidate_sections = {section["id"]: section for section in candidate["content"]["sections"]}
    if list(candidate_sections) != list(base_sections):
        errors.append({"code": "section_identity", "message": "Resume sections or their order changed. Restore the approved section structure."})

    base_blocks = _blocks(baseline)
    base_items = _skill_items(baseline)
    candidate_items = _skill_items(candidate)
    for item_id, item in candidate_items.items():
        before = base_items.get(item_id)
        original_text = before.get("text", "") if before else ""
        unsupported = _unsupported_vocabulary(item.get("text", ""), original_text, item.get("source_refs", []), profile)
        if unsupported:
            errors.append({
                "code": "unsupported_skill_vocabulary",
                "message": f"Skill {item_id} adds wording not found in its canonical evidence: {', '.join(unsupported[:12])}.",
            })

    for section in candidate["content"]["sections"]:
        original_section = base_sections.get(section["id"])
        if not original_section:
            continue
        for block in section["blocks"]:
            original = base_blocks.get(block["id"])
            if block.get("type") == "layout_paragraph":
                continue
            if block.get("type") == "skill_group":
                continue
            block_type = block.get("type")
            if block_type not in rdm.EDITABLE_TEXT_BLOCK_TYPES:
                if original is None:
                    errors.append({"code": "unrecognized_added_block", "message": f"Added block {block.get('id')} is not an allowed source-backed bullet or skill group."})
                    continue
                if block != original:
                    errors.append({"code": "protected_content", "message": f"Protected content ({block.get('type')}) was changed. Restore the canonical value and formatting."})
                continue
            original_text = _text(original) if original else ""
            edited_text = _text(block)
            unsupported = _unsupported_vocabulary(edited_text, original_text, block.get("source_refs", []), profile)
            if unsupported:
                errors.append({
                    "code": "unsupported_vocabulary",
                    "message": (
                        f"{block.get('type')} {block['id']} adds wording not found in its original text or cited canonical evidence: "
                        f"{', '.join(unsupported[:12])}. Remove those additions or use source-supported wording."
                    ),
                })

    return {
        "valid": not errors,
        "errors": errors,
        "policy": "source-bound lexical, numeric, and protected-structure checks",
        "claim_truth_semantically_verified": False,
        "human_review_required": True,
    }
