# Phase 3C.4 — Controlled Full-Resume Editing

**Status: Complete.** The existing Tiptap Resume Editor now supports controlled editing across the source-backed resume content while retaining the approved plan, canonical evidence, additive renderer, one-page gate, atomic Working activation, and Final protection.

## Files changed

1. `career_os_api.py` — adds a read-only canonical skill catalog to the existing ResumeDocument load response and a temporary compatibility view for legacy frozen-generator checks. The final Working files are still rendered from the unchanged user candidate.
2. `resume_document_model.py` — enables source-backed factual editing for project/experience titles and bullets, education, certifications, and skill items; validates canonical skill selections and source references; allows only supported new bullets under selected project/experience parents; validates section identity, record grouping/order, and bounded presentation settings. Canonical skill categories remain fixed and each must retain at least one item.
3. `resume_document_validation.py` — applies the existing source-bound lexical policy to the expanded editable content and candidate skill selections; unsupported factual vocabulary/numbers remain rejected.
4. `resume_document_renderer.py` — additive DOCX/PDF rendering now applies validated section, block, and run formatting/spacing, including project and bullet gaps. The frozen generator remains the template/validation helper; it was not modified.
5. `frontend/src/components/ResumeDocumentEditor.tsx` — extends the existing Tiptap nodes, editing controls, source-backed skill picker, section headings, bullet actions, education/certification reordering, spacing controls, and edit ledger. New bullet IDs use the model’s required stable-ID format; catalog-only grouping metadata is not persisted into skill items.
6. `frontend/src/styles.css` — adds scoped styles for in-document skill and heading controls.
7. `test_resume_document_editor.py` — covers supported source-backed edits, skill addition/reordering, education/certification reordering, section labels/spacing, supported new bullets, and rejection of unsupported claims/spacing.
8. `test_resume_document_save.py` — adds an isolated real-data save/render test asserting edits appear in DOCX and PDF, all required checks pass, output is one page, and prior/Final artifacts are preserved.
9. `frontend/.phase3c4_e2e.cjs` — adds a Playwright test harness which routes API calls to a temporary cloned store rather than the live application data.

## Capabilities added

- **Summary:** edit existing source-backed text and use text formatting controls.
- **Skills:** edit, add, remove, and reorder evidence-backed skill items. New items must come from the canonical profile/selected-project catalog and carry its exact source references. Existing category identities/order remain fixed, and a category cannot be emptied.
- **Education:** edit source-backed displayed text, apply formatting, and reorder complete education records while keeping each record’s lines together.
- **Experience:** existing selected experience entries and bullets are editable/source-bound; bullets can be added, removed, or reordered only under the selected canonical experience. Employers, dates, stable record identities, and provenance remain protected.
- **Projects:** edit display titles and bullets; add/remove/reorder source-backed bullets only under selected projects. Canonical project IDs/order and technology stacks remain protected/read-only.
- **Certifications:** edit source-backed displayed text, format it, and reorder complete existing entries; certification identity/provenance remains fixed.
- **Headings/layout:** edit visible section labels without changing section identity. Bounded spacing controls cover sections, project starts, title-to-bullet gaps, and bullet gaps. No tables, columns, text boxes, images, or floating objects were introduced.
- **Editor controls:** bold, italic, underline, font size/line-spacing presets, alignment, bullets/numbering, undo/redo, block actions, and the existing Cancel/Save Working flow remain available.

Server validation still examines the exact candidate for model structure, stable identities, source references, and unsupported claims. To preserve the frozen generator’s legacy exact-heading/project-name/language checks without changing `resume_generator.py`, the save transaction renders a **temporary validation-only view** with canonical labels for those legacy checks. The actual candidate is separately rendered to the staged Working DOCX/PDF and checked for one page, extractable/matching text, structure, and provenance before activation.

## Validation results

- `python -X utf8 -m unittest -v test_resume_document_model test_resume_document_renderer test_resume_document_save test_resume_document_editor` — **PASS, 21 tests**.
- `python -X utf8 test_resume_project_edit.py` — **PASS**.
- `python -X utf8 test_document_history.py` — **PASS**.
- `npm run build` — **PASS** (`tsc -b` and Vite production build).
- Playwright browser E2E against the isolated clone — **PASS**:
  - Resume Workspace opened for Rex.zone, and EDIT loaded ResumeDocument as **HTTP 200 `application/json`** (`decision: ready`, schema v1).
  - Exercised summary, skills (including canonical MySQL add/remove/reorder), education text and record reordering, certification text and reordering, project title/bullet editing, section headings, spacing, and formatting.
  - Exercised adding and removing a supported bullet, then confirmed **CANCEL / DISCARD** reloaded the unmodified baseline.
  - Saved the candidate in the clone; the renderer produced DOCX and PDF, the extracted edits were present in both, and one-page, ATS, and provenance checks passed.
  - A fabricated `10000 enterprise clients` claim was rejected (`validation_failed`); the cloned application store, active Working references, and artifact file list remained unchanged after rejection.
  - Browser page errors: **none**.

## Data and artifact integrity

- `resume_generator.py`: **not modified**; its hash matched the pre-E2E snapshot.
- Live application count: **2**, unchanged. `data/applications.json` remained byte-for-byte identical through the browser test.
- Approved Resume Plan, canonical profile/data, active Working DOCX/PDF and revision/validation files, template, and Final DOCX/PDF hashes were checked against the pre-E2E snapshot and remained unchanged.
- Live Rex.zone (`app_14a66f897623`) still uses active Working revision `rev_ab7adc5325d50511427d7a20`; it remains non-stale. The browser Save was performed only in a temporary clone.
- Final Resume artifacts and Final metadata were not changed.

## Test limitation / remaining issue

The approved Rex.zone Resume Plan does not select an experience section. To honor the instruction not to modify that plan or fabricate experience, the real Rex.zone browser run could not exercise experience editing. The model, renderer, editor actions, and server policy support experience records/bullets when they are present in an approved selection; an experience fixture was not inserted into Rex.zone.
