# AI Career Command Center

This repository contains a local-first, human-in-the-loop job-application assistant. Phase 10 adds a Streamlit graphical interface around the completed Phase 6 resume generator, Phase 7 profile-update agent, Phase 8 JD intelligence planner, and Phase 9A application assistant.

## Launch

From the project directory:

```bash
streamlit run app.py
```

The UI opens as the **AI Career Command Center** with a dark, professional interface and subtle depth/glass styling.

## Main pages

- **Dashboard:** application metrics, pipeline, recent applications, and pending actions.
- **New Application / JD Analysis:** enter a job URL, company, and JD; invoke Phase 8; inspect evidence and the Resume Plan; create a tracked application only after review.
- **Resume Workspace:** approve the plan, create a working DOCX through Phase 6, validate it, finalize it, convert it to PDF, and optionally save it to document history.
- **Cover Letter Workspace:** create a source-supported working cover letter through Phase 9A, finalize it, convert it to PDF, and optionally retain it in history.
- **Application Package:** review all documents and gaps, open the job posting, and confirm manual submission.
- **Application History:** search and filter applications while preserving status history.
- **Profile:** inspect the master profile and submit natural-language updates through Phase 7 with an explicit confirmation step.
- **Pending Actions:** see approval, document, readiness, and follow-up actions.
- **Search:** search applications and projects.
- **Settings:** view safety and phase boundaries.

## Typical workflow

1. Open **New Application**.
2. Paste the JD and optionally provide its actual URL and company name.
3. Select **Analyze job**. Phase 8 performs JD intelligence and evidence matching.
4. Review the supported, partial, and unsupported requirements, selected projects, and experience decisions.
5. Select **Create tracked application**.
6. Open **Resume Workspace** and explicitly approve the Resume Plan.
7. Generate and review the working resume. Finalization revalidates the DOCX, required sections, contact information, hyperlinks, provenance, placeholders, and one-page requirement before creating a final version.
8. Convert and validate the final PDF without replacing the DOCX.
9. Generate, review, finalize, and convert the cover letter through the same lifecycle.
10. Review the **Application Package**.
11. Personally submit the application on the employer’s website.
12. Select **Mark as applied** only after confirming that you personally submitted it.

## Document lifecycle

Both resume and cover letter follow:

```text
WORKING → REVIEW → FINALIZE → VALIDATE → CONVERT TO PDF → OPTIONAL SAVE TO HISTORY
```

Working changes do not automatically create history entries. Application records are stored in `data/applications.json`, JD snapshots in `job_descriptions/`, working/final documents in `output/`, and optional document history in `data/document_history.json`.

## Profile updates

The Profile page calls the Phase 7 planner. It displays a proposed plan first. Persistent profile modification requires explicit confirmation and remains subject to Phase 7 provenance and conflict rules.

## Safety boundary

Phase 10 does **not** implement automatic job application submission. It does not log in to LinkedIn or company portals, fill application forms, bypass CAPTCHAs, send application emails, or click final submission buttons. Application submission is manual only.

The original `resumes/RESUME.docx`, ATS template, profile JSON files, and Phase 6–9A business-logic modules remain protected from routine UI actions.
