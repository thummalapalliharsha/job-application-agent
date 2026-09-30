Create Phase 4: agent_instructions.md for the Job Application Agent.

IMPORTANT:
- Do NOT generate a resume yet.
- Do NOT modify RESUME.docx.
- Do NOT modify ats_resume_template.docx.
- Do NOT modify the existing JSON data unless absolutely required to reference the workflow.
- This phase is ONLY to create the central agent rulebook.

The agent_instructions.md must define the following workflows.

## 1. SOURCE OF TRUTH

The JSON files in data/ are the canonical structured profile.

Use:
- master_profile.json
- skills.json
- projects.json
- experience.json
- certifications.json
- education.json
- achievements.json

RESUME.docx is source/reference material, not the canonical database.

GitHub is an evidence/provenance source for projects, not the only source of truth.

Never invent information.

---

## 2. PROJECT LIFECYCLE

Respect the existing project lifecycle system.

Possible statuses:
- idea
- planned
- in_progress
- completed
- unknown

GitHub availability is independent:
- github_verified
- github_not_uploaded
- github_pending
- github_unverified

Rules:
- idea/planned projects cannot appear on a final resume.
- in_progress projects are excluded by default.
- completed projects may be selected if sufficiently supported.
- unknown projects cannot be treated as completed.
- GitHub presence does not prove completion.
- A project uploaded to GitHub later must update its existing record rather than create a duplicate.
- Never permanently rank projects.

---

## 3. NEW INFORMATION / PROFILE UPDATE WORKFLOW

The agent must support future updates without rebuilding the system.

Examples:
- Add a new skill.
- Add a new project.
- Update an existing project.
- Mark a project completed.
- Add GitHub information later.
- Add a certification.
- Add an achievement.
- Correct an existing factual record.

When new information is provided:
1. Identify the appropriate JSON record.
2. Check whether the information already exists.
3. Avoid duplicates.
4. Preserve provenance.
5. Record the source/evidence.
6. Preserve conflicting claims instead of silently overwriting them.
7. Apply appropriate verification/status fields.
8. Do not automatically modify an existing resume.
9. Require user approval before destructive or ambiguous changes.

A skill can exist without project usage, but the agent must never claim project experience that does not exist.

---

## 4. JOB DESCRIPTION ANALYSIS

When the user provides a JD:
1. Extract required skills.
2. Extract preferred skills.
3. Extract responsibilities.
4. Identify role type.
5. Identify relevant keywords.
6. Identify education/eligibility requirements.
7. Identify technologies/tools.
8. Identify domain-specific requirements.
9. Distinguish explicit requirements from inferred preferences.

Do not invent requirements that are not present.

---

## 5. DYNAMIC CANDIDATE SELECTION

Select resume content dynamically for each JD.

Selection should consider:
- JD relevance
- verified skills
- completed project status
- evidence strength
- relevant experience
- available space
- truthful representation

Do NOT use a permanent high/medium/low project ranking.

The same project may be selected for one JD and not selected for another.

Never select a project simply because it is the newest or has a GitHub repository.

---

## 6. RESUME CONTENT RULES

The candidate is a fresher.

The final resume must:
- be exactly ONE PAGE.
- be ATS-friendly.
- be truthful.
- use only information supported by the master profile.
- prioritize JD-relevant information.
- preserve factual meaning.
- avoid fabricated metrics.
- avoid fabricated technologies.
- avoid fabricated responsibilities.
- avoid fabricated employment.
- avoid fabricated achievements.

Rewriting and condensing existing truthful information is allowed.

Do not turn projects into employment.

IMDb Movie Analysis must always remain a project.

Ediglobe and EduSkills must remain separate records.

---

## 7. PROVENANCE AND VERIFICATION

Every substantive resume claim must be traceable to available source evidence.

Distinguish:
- verified
- partially_verified
- candidate_provided
- needs_review
- unverified

If a claim is marked unverified, do not present it as independently verified.

Do not strengthen an unverified claim merely to improve the resume.

---

## 8. ONE-PAGE VALIDATION

Before presenting a final resume:
- Verify the document is one page.
- Check that no section is accidentally pushed to a second page.
- Check readability.
- Check ATS-friendly structure.
- Check headings and formatting.
- Check contact information.
- Check dates.
- Check project names.
- Check technologies.
- Check metrics.
- Check experience classifications.
- Check for duplicated content.

If it exceeds one page, revise by condensing/reordering content rather than violating the one-page requirement.

---

## 9. HUMAN APPROVAL CHECKPOINTS

The agent must not silently make major profile or resume decisions.

For resume generation:
1. Analyze JD.
2. Present a concise selection/reasoning summary.
3. Show which projects, skills, and experience it intends to use.
4. Wait for user approval.
5. Generate the draft only after approval.
6. Validate the draft.
7. Present the final result.
8. Never automatically submit a job application unless explicitly instructed and an appropriate workflow exists.

For ambiguous profile updates, ask for clarification or approval before making the change.

---

## 10. OUTPUT ORGANIZATION

Generated files must use the existing folders:

output/
├── cover_letters/
├── reports/
└── resumes/

Do not create a new project structure.

---

## 11. SAFETY AGAINST HALLUCINATION

The highest-priority rule is factual accuracy.

The agent must never:
- invent skills
- invent projects
- invent experience
- invent certifications
- invent achievements
- invent metrics
- invent responsibilities
- invent technologies
- invent employment
- claim a project was completed when status is unknown
- claim GitHub verification when it has not been established

When information is missing, say it is missing.

---

## 12. FUTURE EXTENSIBILITY

The design must support:
- new skills
- new projects
- new certifications
- new experience
- future GitHub repositories
- updated project statuses
- additional source documents

without requiring a redesign of the agent.

Do not hard-code the current 11 completed projects as the permanent project set.

The master profile must remain dynamic.

After creating agent_instructions.md:
1. Validate that the file is internally consistent with the existing JSON schema.
2. Confirm that the existing folder structure was preserved.
3. Confirm that no resume/template was modified.
4. Provide a concise summary of the rules implemented.

Then STOP and wait for my next instruction.


---

# Phase 7 — Profile Update Agent

The Profile Update Agent maintains the JSON files under `data/` as the long-term canonical profile source. GitHub is evidence/provenance, not a competing database, and profile updates never automatically regenerate a resume.

## Natural-language routing and planning

The agent routes requests to `skills.json`, `projects.json`, `certifications.json`, `experience.json`, `education.json`, `achievements.json`, or an appropriate `master_profile.json` field. Before a meaningful persistent change, it produces an update plan that identifies the action, record, fields, old/new values where relevant, provenance, and any warnings. Ambiguous requests such as “Add FastAPI” require clarification rather than guessing.

## Skill versus project evidence

A learned skill is not project experience. A statement such as “I learned Docker” may update `skills.json` only. Project technologies are updated only when the user explicitly states that the technology was used in that project. The agent never converts a skill into a project claim.

## Project lifecycle and GitHub

Project lifecycle is independent of GitHub availability. Valid `project_status` values are `idea`, `planned`, `in_progress`, `completed`, and `unknown`. Valid `github_availability` values are `github_verified`, `github_not_uploaded`, `github_pending`, and `github_unverified`. GitHub presence does not prove completion, and a completed project can remain usable when it is not uploaded. Existing projects are updated when a repository is later supplied; duplicates are not created.

## Duplicate, conflict, and deletion handling

The agent checks normalized names, aliases, URLs, and available identity details before creating projects or certifications. Conflicting factual values are not silently overwritten; the existing value, proposed value, and affected field are shown for confirmation. Destructive project removal is confirmation-gated and must identify the record and related references before any deletion or archival action.

## Provenance and synchronization

User-provided facts are stored as user-provided evidence and are never represented as inferred or independently verified. Missing dates, URLs, IDs, metrics, responsibilities, and results remain empty or require clarification. After an approved category update, `master_profile.json` indexes are synchronized with the category files without creating a second database. Existing Ediglobe and EduSkills records remain separate, and IMDb Movie Analysis remains a project.

## Approval and resume isolation

The default Profile Update Agent behavior is a read-only plan. Persistent writes require explicit confirmation through the approval workflow. Profile updates do not modify `resumes/RESUME.docx`, `templates/ats_resume_template.docx`, existing tailored resumes, or resume plans. Resume generation remains a separate Phase 6 workflow requiring its own approved Resume Plan.

## Validation and history

After an approved update, JSON validity, lifecycle values, duplicate IDs, provenance, required fields, master-profile indexes, and unrelated-record integrity must be checked. A report is written under `output/reports/`. The agent may record update metadata in that report, including timestamp, request, affected category/record, changed fields, provenance, and confirmation status, without storing unnecessary sensitive information.

The implementation is provided by `profile_update_agent.py`; regression coverage is provided by `test_profile_update_agent.py`.


---

# Phase 8 — JD Intelligence and Semantic Matching

Phase 8 improves JD analysis and candidate matching while preserving the Phase 6 resume generator and Phase 7 profile-update workflow. The planner reads the latest `data/*.json` files at runtime and does not modify profile data, resumes, templates, or resume plans automatically.

## Deterministic semantic normalization

The planner recognizes transparent technical relationships such as vector database → ChromaDB, retrieval pipeline → embeddings/semantic retrieval/RAG, LLM application → Ollama or documented API integration, natural-language database querying → Text-to-SQL, data preprocessing → preprocessing pipelines, and EDA → Pandas analysis/visualization. These mappings identify relevance only; they never create unsupported technologies, responsibilities, dates, metrics, or project claims.

The current implementation is deterministic and uses no external LLM or embedding service. This provides a reproducible local fallback with no external-profile transmission and no paid dependency. If a future semantic model is introduced, its output must be validated against the JSON profile before use.

## Requirement classification and evidence

JD requirements are classified as required, preferred, or uncertain only when explicit JD wording supports that classification. Each requirement receives traceable profile evidence and one of `SUPPORTED`, `PARTIAL`, `UNSUPPORTED`, or `UNKNOWN`. Direct matches are distinguished from semantic/related matches. Partial evidence is never upgraded to supported evidence, and unsupported JD technologies are never added to the profile.

## Project and experience matching

Project relevance is scored dynamically for the current JD only using direct and semantic requirement evidence, while generic overlap such as Python, Git, GitHub, or broad machine-learning terms cannot independently select a project. Only `completed` projects are eligible by default. `idea`, `planned`, `in_progress`, and `unknown` projects remain excluded unless a future explicit rule changes that behavior. GitHub availability remains independent of lifecycle status, so a completed project without GitHub can remain eligible.

Experience is evaluated using actual responsibilities and technologies. Broad terms such as AI or Python do not automatically make an internship relevant. If experience is not meaningfully relevant, the planner excludes it honestly and may use the third relevant completed project fallback. The normal selection target is two relevant completed projects; the third project is used only when relevant experience is insufficient.

## Gap analysis and explainability

Reports identify strong evidence, partial or related evidence, unsupported requirements, unknown requirements, potential risks, selected projects, excluded lifecycle records, experience decisions, skill evidence, certifications where supported, and concise reasons for each important decision. Numerical relevance aids are internal organizational tools only and are not candidate-quality, hiring-probability, or permanent project-ranking scores.

## Human approval and Phase 6 integration

Every generated Resume Plan remains approval-gated with `resume_generation_allowed: false`. The workflow is: JD analysis → semantic normalization → evidence matching → dynamic selection → Resume Plan → explicit human approval → existing Phase 6 generator. Phase 8 never regenerates resumes automatically and does not alter the frozen Phase 6 generator, ATS template, original resume, or existing profile records.


---

# Phase 9A — Human-in-the-Loop Application Assistant

Phase 9A manages manual job-application preparation and tracking. It does not log in to portals, automate browser actions, solve CAPTCHAs, submit applications, send application email, or impersonate the user. The final application submission is always performed manually by the candidate.

## Application records and job storage

Applications are stored in `data/applications.json`. A record may include the application ID, company, role, actual user-provided job URL, source/platform, location, employment type, JD reference, dates, controlled status, resume and cover-letter references, selected profile evidence, requirements summary, gaps, notes, follow-up date, status history, and provenance. Supplied JD snapshots are stored under `job_descriptions/`; missing job details remain empty rather than inferred.

Before creating an application, the assistant checks normalized job URL, company, title, requisition information when available, and JD similarity. A likely duplicate is reported with its existing status and URL; the assistant asks whether to update the existing record or create a separate application.

## Phase 8 and Phase 6 integration

Phase 9A calls the existing Phase 8 planner for JD intelligence and stores its evidence classifications, selected projects, skills, experience decisions, supported requirements, partial requirements, unsupported requirements, and candidate gaps. It does not duplicate matching logic. Resume generation remains a separate Phase 6 operation: human approval must set the application’s resume-generation permission before the frozen generator may be used. Generated resume paths are associated with the correct application and must never overwrite another application’s resume or `resumes/RESUME.docx`.

## Cover letters and checklists

Cover letters are generated as concise Markdown files under `output/cover_letters/` using only the supplied JD and source-supported profile evidence. Unsupported technologies, experience, metrics, and employment claims are not added. Application checklists distinguish required, preferred, partial, unsupported, document, and manual-submission items. Manual actions remain pending until the user confirms them.

## Status lifecycle and manual submission

Controlled statuses include `saved`, `analyzing`, `awaiting_resume_approval`, `resume_ready`, `ready_to_apply`, `applied`, `assessment`, `interview`, `offer`, `rejected`, `withdrawn`, and `closed`. The assistant never moves an application to `applied` automatically. The candidate must explicitly confirm that they manually submitted it; only then are `current_status=applied` and `date_applied` recorded. Every status change preserves old status, new status, timestamp, and source in status history. Ambiguous status updates require application identification or clarification.

## Notes, follow-up, search, and reporting

User-provided notes and follow-up dates are stored against the identified application. Follow-up dates do not create reminders automatically. Applications can be searched by company, title, or status, and a summary report is written under `output/reports/`. No external service is required for Phase 9A.


---

# Phase 10 — Graphical Application Dashboard

Phase 10 is a Streamlit integration layer only. It does not rewrite Phases 6–9A and does not implement Phase 9B. The entry point is `app.py`, launched with `streamlit run app.py`.

The dashboard reads `data/applications.json` and the existing profile data. It provides Dashboard, New Application/JD Analysis, Resume Workspace, Cover Letter Workspace, Application Package, Application History, Profile, Pending Actions, Search, and Settings pages. It must not create a second application or profile database.

## UI approval gates

The UI displays the Phase 8 Resume Plan before resume generation. Resume generation remains disabled until the user explicitly approves the plan. Profile updates call Phase 7 planning and require explicit confirmation before persistent writes. Applied status requires the user to confirm that they personally submitted the application. The UI must not silently generate, finalize, save history, update profile, mark applied, or submit an application.

## Document lifecycle

Resume and cover letter each follow `WORKING → REVIEW → FINALIZE → VALIDATE → CONVERT TO PDF → OPTIONAL SAVE TO HISTORY`. Working versions are application-specific. Final DOCX files remain available, final PDFs are validated for existence, page count, and readable text, and history is written only after an explicit save-to-history action. The original resume and ATS template are never overwritten.

## Phase integration

Phase 8 remains authoritative for JD intelligence and evidence matching. Phase 6 remains authoritative for resume generation and validation. Phase 7 remains authoritative for profile updates. Phase 9A remains authoritative for application records, duplicate detection, notes, follow-up, cover letters, checklists, and manual submission confirmation. The UI uses adapters and does not duplicate those business rules.

## Safety and privacy

Phase 10 has no browser automation, portal login, CAPTCHA handling, automatic form filling, automatic submission, or automatic email submission. It displays the manual-submission boundary clearly. It does not expose secrets or send unnecessary personal data to external services. Phase 9B remains future scope only.
