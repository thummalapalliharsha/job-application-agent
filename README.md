# AI Career OS / Career Command Center

AI Career OS is a local-first, human-in-the-loop workspace for analyzing job descriptions, building ATS-compliant one-page resumes, generating tailored cover letters, and tracking job applications without automated portal submissions.

---

## Architecture

The system is built as a modular local Python/Streamlit architecture:

```text
┌─────────────────────────────────────────────────────────────┐
│                    Streamlit UI (app.py)                    │
│     Dashboard • New Application • Resume • Cover Letter     │
└──────────────┬───────────────────────────────┬──────────────┘
               │                               │
       ┌───────▼──────────────┐        ┌───────▼──────────────┐
       │ jd_resume_planner.py │        │ application_assistant│
       │ (Phase 8 JD Analysis)│        │ (Phase 9A Lifecycle) │
       └───────┬──────────────┘        └───────┬──────────────┘
               │                               │
       ┌───────▼──────────────┐        ┌───────▼──────────────┐
       │  resume_generator.py │        │   career_os_api.py   │
       │ (Phase 6 Frozen ATS) │        │ (Phase 3C Doc Model) │
       └──────────────────────┘        └──────────────────────┘
```

- **UI Layer (`app.py`)**: Local Streamlit application managing page routing, previews, downloads, and interactive approvals.
- **JD Intelligence (`jd_resume_planner.py`)**: Analyzes JD text, extracts requirements, classifies evidence against canonical candidate data, and formulates resume plans.
- **Resume Generation (`resume_generator.py`)**: Frozen, deterministic generator assembling strict 1-page ATS resumes in DOCX and converting to PDF.
- **Document Model & Editing (`resume_document_model.py`, `resume_document_renderer.py`, `career_os_api.py`)**: Fine-grained block editing with truth-grounding rules and rollback safety.
- **Application Management (`application_assistant.py`)**: Tracks application status, duplicate detection, notes, checklists, and cover letter generation.
- **Profile Updates (`profile_update_agent.py`)**: Human-in-the-loop, approval-gated profile modifications.

---

## Folder Structure

```text
job-application-agent/
├── app.py                         # Streamlit web application UI
├── application_assistant.py       # Application lifecycle & cover letter logic
├── career_os_api.py               # API interface & resume document payload management
├── jd_resume_planner.py           # Phase 8 JD parsing & resume planning
├── profile_update_agent.py        # Phase 7 natural-language profile updater
├── resume_document_model.py       # Phase 3C ResumeDocument schema & validators
├── resume_document_renderer.py    # Phase 3C AST-to-DOCX/PDF renderer
├── resume_document_validation.py  # Phase 3C document validation rules
├── resume_generator.py            # Phase 6 FROZEN ATS resume generator
├── data/                          # Canonical profile, skills, projects, applications JSON
├── job_descriptions/              # Saved JD text snapshots
├── output/
│   ├── cover_letters/             # Generated Markdown, DOCX, and PDF cover letters
│   ├── reports/                   # Validation and planning JSON reports
│   └── resumes/                   # Working and final DOCX/PDF resumes
├── templates/                     # ats_resume_template.docx (protected)
└── resumes/                       # Protected source resume references
```

---

## Tech Stack

- **Core**: Python 3.12+ / 3.13
- **Frontend / UI**: Streamlit, Spline Viewer (3D hero component), HTML/CSS
- **Document Processing**: `python-docx` (Word processing), LibreOffice / Windows Word COM (PDF conversion)
- **Data Serialization**: JSON-backed local storage (`data/*.json`)
- **Testing**: Python `unittest` / `pytest`

---

## Main Workflows

1. **Analyze Job Description**:
   - Paste job description in **New Application**.
   - Review requirement extraction (required, preferred, uncertain) and candidate evidence matches.
   - Create a tracked application (sets status to `awaiting_resume_approval`).
2. **Resume Generation & Approval**:
   - Open **Resume Workspace** and explicitly approve the Phase 8 plan.
   - Generate working resume (DOCX + PDF) and verify 1-page ATS compliance.
   - Review and finalize into a immutable final artifact.
3. **Cover Letter Generation**:
   - Open **Cover Letter Workspace** to generate a truthful, JD-tailored cover letter.
   - Edit draft if needed (restricted to evidence-backed assertions).
   - Finalize and convert to PDF.
4. **Application Package & Manual Submission**:
   - Review consolidated readiness checklist in **Application Package**.
   - Manually submit materials via the employer's official portal.
   - Explicitly confirm manual submission to transition status to `applied`.

---

## Local Run Commands

Run the Streamlit application:

```bash
streamlit run app.py
```

Run headless JD planning:

```bash
python jd_resume_planner.py --jd job_descriptions/<file>.txt --output output/reports/<aid>_plan.json
```

---

## Testing

Run unit and integration test suites:

```bash
# Run unittest discovery
python -m unittest discover -s . -p "test_*.py"

# Or run individual test modules
python test_document_history.py
python test_manual_project_selection.py
python test_phase8_jd_intelligence.py
python test_profile_update_agent.py
python test_resume_document_model.py
python test_resume_document_renderer.py
python test_resume_document_save.py
python test_resume_project_edit.py
```

---

## Security & Privacy Hardening

- **Local-First & Offline Capable**: Data remains in local JSON files; no candidate data is sent to unauthorized external APIs.
- **Strict Human-in-the-Loop**: Profile mutations, plan approvals, and status transitions require explicit user confirmation.
- **Anti-Hallucination Constraints**: Resume generator and planners strictly pull from canonical profile data (`data/*.json`).
- **No Stored Credentials**: No portal passwords, tokens, or automated browser login mechanisms exist.

---

## Important Limitations

- **No Automated Application Submission**: The system never logs into job boards, fills forms, solves CAPTCHAs, or submits applications automatically.
- **Frozen Generator**: `resume_generator.py` is frozen and protected by hash verification to guarantee ATS formatting invariants.
- **Strict 1-Page Constraint**: Resumes that exceed 1 page fail validation and cannot be finalized.
