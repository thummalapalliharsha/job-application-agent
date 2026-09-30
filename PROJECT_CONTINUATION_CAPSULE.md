# AI Career Agent — Project Continuation Capsule

## 1. Purpose and architecture

AI Career Agent is a local-first, approval-gated Streamlit workspace for turning job descriptions into application-ready materials. The main UI is `app.py`; supporting modules handle application records, JD/resume planning, profile updates, resume generation, and document history. Workflows are navigated through Streamlit sidebar pages and Dashboard action callbacks. Application data is stored locally under `data/`; generated artifacts and validation reports are stored under `output/`.

## 2. Current project structure

```text
app.py                         Main Streamlit UI and page routing
resume_generator.py            Frozen deterministic resume generator
application_assistant.py       Application-record/application-assistant logic
jd_resume_planner.py           JD analysis and resume planning
profile_update_agent.py        Approval-gated profile updates
data/                          Profile, achievements, projects, applications, and local records
output/                        Generated resumes/letters and validation reports
templates/                     Protected ATS resume template
resumes/                       Original/protected resume source artifacts
test_*.py                      Existing regression tests
```

## 3. Current Dashboard/UI state

The Dashboard opens as one unified hero composition. The left side contains:

```text
AI CAREER AGENT
Your AI-powered job application workspace.
Analyze jobs, build tailored resumes, and create application-ready materials.
```

The three compact primary actions remain beside the copy: `Analyze JD`, `Build Resume`, and `Create Cover Letter`. The right side contains the actual Spline Viewer component inside the same hero card, occupying approximately half of the hero width. The existing sidebar/navigation and workflow callbacks remain unchanged. The internal label `PHASE 9B IS NOT IMPLEMENTED` was removed from the sidebar.

## 4. Exact Spline integration

Current scene URL:

```text
https://prod.spline.design/q7IZR3vyGue1MLyp/scene.splinecode
```

Current integration: the existing `components.html` embed uses Spline Viewer `2.0.55` with:

```html
<spline-viewer
  class="spline-orb"
  url="https://prod.spline.design/q7IZR3vyGue1MLyp/scene.splinecode"
  loading="eager">
</spline-viewer>
```

The failed Public URL iframe experiment was reverted. Do not substitute the Public URL or modify the Spline scene.

## 5. Completed and verified

The Dashboard hero was corrected so the actual orb is physically inside the opening hero on the right, beside the concise text/actions. A fresh real-browser check at 100% zoom visibly showed the orb, its Spline watermark, and the text/action column in one hero. Browser measurements showed approximately `408px` text width and `408px × 430px` Spline iframe/canvas. Pointer movement across the visible orb was performed and its visible interaction state changed. `app.py` compiled successfully. Protected resume/application/template hashes were checked and remained unchanged except that the expected original-resume path was unavailable in the final hash check and must not be recreated or altered without evidence.

## 6. Known issues / pending small changes

The only known regression issue is an obsolete assertion in `test_manual_project_selection.py` that expects the removed text `PHASE 9B IS NOT IMPLEMENTED`. The test otherwise passes. Do not restore that internal label merely to satisfy the obsolete assertion. No Spline debugging or integration changes are pending.

## 7. Frozen/protected components — do not modify

Do not modify `resume_generator.py`, `app.py` production/business logic, backend/application logic, workflow callbacks, the Spline scene, templates, `data/applications.json`, the original `RESUME.docx`, or protected resume/application/profile/JD source data. The frozen `resume_generator.py` SHA-256 is:

```text
85d8e0c9989995b1f6cdba80e9a96a7ddc99ec629a92fe445cedc6c58f5cf48b
```

For future UI work, edits must remain presentation-only and must not alter resume generation, application persistence, workflow semantics, or protected artifacts.

## 8. Key tests and known obsolete failure

Passing existing tests:

```text
test_document_history.py
test_resume_project_edit.py
test_application_assistant.py
test_phase8_jd_intelligence.py
test_profile_update_agent.py
```

`test_manual_project_selection.py` has one known obsolete failure: `Phase 9B remains unimplemented`. Its substantive selection, synchronization, generator, approval-gate, and integration checks pass. Do not weaken tests or change production behavior to force this obsolete expectation.

## 9. Rules to preserve

Keep the app local-first and approval-gated. Application submission remains manual. Preserve the existing sidebar/navigation, three Dashboard workflow buttons, exact Spline scene URL, real Spline Viewer, and unified text-left/orb-right hero. Do not add a fake/CSS/SVG orb, replace the Spline scene, use the failed Public URL iframe, redesign the whole application, or perform speculative Spline/WebGL debugging. Do not modify frozen resume-generation or application logic.

## 10. Recommended next step

Continue with the next explicitly requested **UI-only** task. Before changing code, preserve the current hero structure and run `python3 -B -m py_compile app.py`; after UI edits, run the existing regression suite and perform a fresh 100%-zoom browser check. Treat the single Phase 9B test failure as obsolete unless the user explicitly authorizes updating that test expectation.
