# Project Context & Agent Handoff

Permanent handoff document for AI Career OS / Career Command Center.

---

## 1. Current Project Status

The codebase is functional.

The current session audited and completed four DataNova application issues:

1. Cover letter PDF generation and downloads.
2. Single-page ATS resume space utilization with truthful JD-relevant content.
3. Standardized application-specific artifact naming convention (`artifact_stem`).
4. JD-aware cover letter tailoring to prevent stale content from previous applications.

All four issues were implemented and verified.

The project is currently uncommitted. The current changes include application code, canonical project/application data, the DataNova test JD, and project documentation.

---

## 2. Component Health Matrix

| Component / Module | Status | Description / Notes |
| :--- | :--- | :--- |
| `resume_generator.py` | **FROZEN** | SHA-256 verified. Strictly protected ATS 1-page generator. |
| `templates/ats_resume_template.docx` | **FROZEN** | Protected layout template. |
| `jd_resume_planner.py` | **WORKING** | Phase 8 JD requirement parser, evidence matcher, and resume planner. |
| `profile_update_agent.py` | **WORKING** | Phase 7 approval-gated profile updater. |
| `resume_document_model.py` | **WORKING** | Phase 3C ResumeDocument schema, AST validator, and block policies. |
| `resume_document_renderer.py` | **WORKING** | Phase 3C AST-to-DOCX/PDF renderer with rollback safety. |
| `career_os_api.py` | **WORKING** | Phase 3C API endpoints with security hardening and document persistence. |
| `application_assistant.py` | **WORKING** | Artifact naming helper, cover-letter generation, JD-aware tailoring, and application workflows. |
| `app.py` (UI) | **WORKING** | Resume/cover-letter generation, PDF conversion, finalization, downloads, and application workflow are implemented. |

---

## 3. Important Frozen Components & Hashes

- **`resume_generator.py`**:
  `85d8e0c9989995b1f6cdba80e9a96a7ddc99ec629a92fe445cedc6c58f5cf48b`

  Rule: Do NOT modify `resume_generator.py` unless explicitly approved.

- **`templates/ats_resume_template.docx`**:
  Protected template file.

- **Canonical Profile Data (`data/*.json`)**:
  `master_profile.json`, `skills.json`, `projects.json`, `experience.json`, `certifications.json`, `education.json`, `achievements.json`.

  Rule: These are authoritative sources of truth. Never invent facts or inject unsupported claims.

---

## 4. Current Modified & Untracked Files

### Modified Files

- `app.py`
  - Uses `artifact_stem()` for application-specific resume artifacts.
  - Uses dynamic resume and cover-letter filenames.
  - Generates cover-letter DOCX/PDF artifacts.
  - Uses Working/Final lifecycle references.

- `application_assistant.py`
  - Added `artifact_stem(app, kind, lifecycle, suffix=None)`.
  - Fixed `generate_cover_letter()` loop control flow.
  - Added JD-aware cover-letter generation.
  - Supports analytics and AI/LLM evaluation domains without stale cross-application wording.

- `career_os_api.py`
  - Uses standardized artifact naming for resume document saves.
  - Retains backend security hardening.

- `data/applications.json`
  - Contains the DataNova test application `app_7956079ee1de`.
  - Contains application-specific JD and artifact references.

- `data/projects.json`
  - Contains the verified evidence-enriched functionality for
    `project_bank_customer_clustering_dashboard`.

### Untracked Files

- `PROJECT_CONTEXT.md`
- `job_descriptions/app_7956079ee1de_junior_data_analyst_fresher.txt`

Generated `.opencode/` files were removed and must not be committed.

---

## 5. Completed Issues

### Issue 1: Cover Letter PDF Generation & Download

- **Completed**: Cover-letter Markdown source is converted to DOCX and PDF.
- **Completed**: Working and Final PDF references are stored.
- **Completed**: UI download buttons serve PDF files.
- **Completed**: Application-specific filenames are used.
- **Completed**: Markdown source remains preserved internally.
- **Verified** on DataNova application `app_7956079ee1de`.
- Working and Final PDFs were generated and verified as readable and text-extractable.

### Issue 2: Single-Page ATS Resume Space Utilization

- **Completed**: Improved canonical evidence for
  `project_bank_customer_clustering_dashboard`.
- Expanded the project's first three functionality entries using verified project evidence.
- Preserved important existing functionality including:
  - density-based outlier detection
  - PCA outputs
  - supervised train/validation/test preparation
- **Completed**: DataNova Working resume regenerated.
- **Verified**: Resume is exactly one page.
- **Verified**: ATS and truth/provenance validation pass.
- **Verified**: `resume_generator.py` remained unchanged.

### Issue 3: Application-Specific File Naming

- **Completed**: `artifact_stem(app, kind, lifecycle, suffix=None)` standardizes artifact naming.
- Convention:

  `{company}_{role}_{application_id}_{Resume|CoverLetter}_{Working|Final}[_{suffix}]`

- Integrated into:
  - `application_assistant.py`
  - `career_os_api.py`
  - `app.py`
- DataNova artifacts follow the standardized naming convention.
- Existing historical application references remain preserved.

### Issue 4: Cover Letter JD Tailoring

- **Completed**: Removed hardcoded Rex.zone/LLM-evaluation wording from generic cover-letter generation.
- **Completed**: Added JD-aware `is_ai_eval` / `is_analytics` branching.
- Intro focus, skills relevance, and closing target now adapt to the JD domain.
- DataNova letter was regenerated.
- Verified stale terms are absent:
  - training-data quality
  - prompt and QA evaluation
  - language-model outputs
  - NLP/LLM-oriented analysis
  - evaluation and calibration workflows
  - AI/ML teams
- Verified DataNova analytics terms are present:
  - data cleaning
  - exploratory data analysis
  - reporting
  - Python
  - SQL
  - Pandas
  - NumPy
- Existing Rex.zone cover-letter artifact remains unchanged.
- `resume_generator.py` remains frozen.

---

## 6. DataNova Test Details

**Application ID:** `app_7956079ee1de`

**Company:** DataNova Analytics

**Role:** Junior Data Analyst — Fresher

**Application status:** `resume_ready`

### Generated Artifacts

Resume:

- `output/resumes/datanova_analytics_junior_data_analyst_fresher_app_7956079ee1de_Resume_Working.docx`
- `output/resumes/datanova_analytics_junior_data_analyst_fresher_app_7956079ee1de_Resume_Working.pdf`
- `output/resumes/datanova_analytics_junior_data_analyst_fresher_app_7956079ee1de_Resume_Final.docx`
- `output/resumes/datanova_analytics_junior_data_analyst_fresher_app_7956079ee1de_Resume_Final.pdf`

Cover Letter:

- `output/cover_letters/datanova_analytics_junior_data_analyst_fresher_app_7956079ee1de_CoverLetter_Working.md`
- `output/cover_letters/datanova_analytics_junior_data_analyst_fresher_app_7956079ee1de_CoverLetter_Working.docx`
- `output/cover_letters/datanova_analytics_junior_data_analyst_fresher_app_7956079ee1de_CoverLetter_Working.pdf`
- `output/cover_letters/datanova_analytics_junior_data_analyst_fresher_app_7956079ee1de_CoverLetter_Final.docx`
- `output/cover_letters/datanova_analytics_junior_data_analyst_fresher_app_7956079ee1de_CoverLetter_Final.pdf`

Reports:

- `output/reports/app_7956079ee1de_phase8_plan.json`
- `output/reports/app_7956079ee1de_resume_validation.json`

---

## 7. Validation Results

### Resume

- Exactly 1 page: PASS
- DOCX/PDF generation: PASS
- ATS validation: PASS
- Truth/provenance validation: PASS
- Unknown/planned projects excluded: PASS
- IMDb not treated as experience: PASS
- Ediglobe and EduSkills kept separate: PASS
- PDF text extraction/readability: PASS

### Cover Letter

- Working PDF: PASS
- Final PDF: PASS
- PDF text extraction: PASS
- DataNova analytics tailoring: PASS
- Stale Rex.zone wording removed from DataNova: PASS
- Existing Rex.zone artifact preserved: PASS

### Filename Convention

All new DataNova artifacts follow:

`<company_slug>_<role_slug>_<application_id>_<Kind>_<Lifecycle>.<ext>`

### Frozen Generator

SHA-256:

`85d8e0c9989995b1f6cdba80e9a96a7ddc99ec629a92fe445cedc6c58f5cf48b`

Status: **FROZEN / VERIFIED**

---

## 8. Test Results & Known Limitations

Relevant tests completed successfully include:

- `test_document_history.py`
- `test_resume_document_model.py`
- `test_resume_document_renderer.py`
- `test_resume_document_save.py`
- `test_profile_update_agent.py`
- `test_phase8_jd_intelligence.py`
- `test_resume_project_edit.py`

`test_application_assistant.py`:

- 17/18 tests passed.
- Test 7 (`approve_resume` status transition) remains a pre-existing unrelated failure.
- Cover-letter tests 8 and 9 passed.

Known portability/legacy test limitations:

- `test_manual_project_selection.py` contains an obsolete string assertion.
- `test_phase10_ui.py` uses a hardcoded Linux path and fails in the local Windows environment.
- Do not modify production code solely to satisfy obsolete tests.

---

## 9. Critical Project Rules

1. **Anti-Hallucination:** Never invent candidate experience, skills, metrics, degrees, or claims.
2. **Source of Truth:** `data/*.json` files are canonical.
3. **Approval Gating:** Resume/profile generation and application status transitions require explicit user confirmation.
4. **No Automated Submission:** Never automate browser portals, CAPTCHA bypass, or email sending.
5. **Frozen Resume Generator:** Never modify `resume_generator.py` without explicit authorization.
6. **One-Page ATS Mandate:** Generated resumes must strictly equal one page.
7. **Artifact Immutability:** Never rename or delete historical output artifacts.
8. **Filename Convention:** New artifacts must use `artifact_stem()`.
9. **JD Tailoring:** Cover letters must be based on the actual JD, approved plan, and canonical evidence.
10. **Security:** Preserve backend local-only access, request validation, artifact restrictions, and traversal protections.
11. **Git:** Do not commit generated output, caches, `.opencode/`, secrets, or environment files.

---

## 10. Current Next Steps

1. Review the final Git diff.
2. Confirm only intended files are modified/untracked.
3. Stage only approved project files.
4. Commit the verified DataNova changes.
5. Confirm the working tree is clean after commit.
6. Perform the final manual UI test of the DataNova application workflow.

No further application-code changes are required unless the final regression/manual UI check identifies a real issue.

---

## 11. Change History

- **Phase 6:** Hardened deterministic ATS resume generator and validation pipeline.
- **Phase 7:** Human-in-the-loop profile update agent.
- **Phase 8:** Semantic JD intelligence and evidence-grounded resume planner.
- **Phase 9A:** Application assistant and cover-letter generator.
- **Phase 10:** Streamlit UI.
- **Phase 3C:** Versioned, evidence-linked ResumeDocument model, renderer, and REST API.
- **Current Session:** Standardized artifact naming, cover-letter PDF generation, resume evidence enrichment, JD-aware cover-letter tailoring, DataNova validation, and project handoff documentation.