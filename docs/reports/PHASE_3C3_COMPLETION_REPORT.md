# Phase 3C.3 — Resume Save, DOCX/PDF Render, and Working Activation

**Status: Complete.** The implementation follows the additive-renderer approach; `resume_generator.py` remains frozen.

## A. Files created for the Phase 3C implementation

- `resume_document_model.py` — versioned ResumeDocument schema, application adapter, revision identity, and source-reference checks (3C.1).
- `resume_document_validation.py` — conservative source-bound lexical, numeric, and protected-structure edit policy.
- `resume_document_renderer.py` — additive DOCX/PDF renderer for validated ResumeDocument models.
- `frontend/src/components/ResumeDocumentEditor.tsx` — constrained Tiptap editor with source-backed block identity, formatting presets, and canonical link checks (3C.2).
- `test_resume_document_model.py`, `test_resume_document_editor.py`, `test_resume_document_renderer.py`, and `test_resume_document_save.py` — model, editor, render, save/rollback, and finalization coverage.
- `frontend/.phase3c3_e2e.cjs` — real Rex.zone browser acceptance harness.

## B. Files modified

- `career_os_api.py` — document save/load/validate endpoints; temporary staging and atomic Working activation; stale-state and server-side finalization checks.
- `frontend/src/main.tsx` and `frontend/src/styles.css` — editor/Workspace integration and its constrained presentation.
- `frontend/package.json` and `frontend/package-lock.json` — Tiptap editor dependencies.
- `test_resume_document_model.py` — parity assertions now distinguish the immutable base resume from a deliberately edited, active Working revision and verify the saved sidecar remains unchanged.
- `test_resume_document_editor.py` — the provenance rewrite case now uses a source-supported lexical-equivalent hyphen/space change rather than expecting unsupported added wording to pass.
- `frontend/.phase3c3_e2e.cjs` — handles an already-active saved revision without creating a duplicate, observes the popup PDF response at browser-context scope, and normalizes SHA-256 hex case.
- `data/applications.json` — only the intended Working-revision metadata for existing Rex.zone application `app_14a66f897623` was updated. No application was added or removed.

The production build refreshed `frontend/dist` outputs.

## C. Renderer architecture

The new renderer opens the existing ATS template and reuses the frozen generator’s safe formatting, heading, hyperlink, and LibreOffice/Poppler conversion helpers. It renders only approved ResumeDocument block types and supported marks. A DOCX package inspection rejects tables, text boxes, drawings/images, floating objects, and embedded objects. The renderer writes only to caller-provided staging paths; it does not target the frozen generator’s Working or Final output paths.

## D. Save pipeline

`POST /api/applications/{application_id}/resume-document/save` receives the structured document and base revision. The API checks application identity, current approved plan/generation, revision freshness, schema, provenance, protected content, allowed formatting, and source-bound edit policy. It stages DOCX/PDF, runs the frozen generator’s existing structural/content validator plus new structure/text checks, then writes unique revision artifacts, validation JSON, and a sidecar. Working references and hashes are updated only after all checks pass.

## E. Validation pipeline

A successful save requires **exactly one PDF page**, existing validation status `PASS`, standard headings, one-column structure, no prohibited Word objects, required contact information and links, project links/order/selection/stacks, skills, summary, languages, education, certifications, no placeholders, extractable text, and parity between model text and extracted PDF text. The current Rex.zone validation report records all checks as passing. Semantic truth is not claimed as machine-proven; human review remains required.

## F. Rollback behavior

The save uses temporary staging first. If rendering or any validation fails, it returns a failure without switching the active Working pointers. Activation writes unique artifact/report/sidecar files, then atomically replaces the application-store JSON only if the original store bytes are still current. Staged outputs are removed on ordinary failures. Unit tests simulate renderer and activation failures and verify the previous Working and Final artifacts remain unchanged. The browser test also verifies that an unsupported claim leaves the store bytes, active references/hashes/revision, and artifact file set unchanged.

## G. Finalization guard

The API-side guard checks approval/currentness, stale status, safe artifact paths and existence, DOCX/PDF hashes, saved revision/application/generation identity, plan digest, validation reference and persisted PASS report, and current source-evidence policy. It blocks stale, mismatched, missing, modified, or unvalidated Working revisions before creating a Final artifact. Tests verify stale and hash-modified cases are rejected and existing Final hashes remain unchanged.

## H. Rex.zone browser results

The real application remained **Rex.zone / `app_14a66f897623`**, and the applications list count remained **2**. The successful save had already completed earlier in this task, so the final E2E rerun reopened and verified that active revision rather than making a duplicate save. It verified the supported “natural-language” → “natural language” edit, the persisted editor content, all validation checks, Workspace return/navigation persistence, and the new-tab inline PDF response. An attempted unsupported addition (“with 10000 enterprise clients”) was rejected with `validation_failed`; the editor remained open with a validation message and the prior Working artifacts were preserved.

## I. DOCX/PDF artifact results

- **Revision:** `rev_ab7adc5325d50511427d7a20`
- **Working DOCX:** `output/resumes/rex_zone_role_app_14a66f897623_Working_rev_ab7adc5325d50511427d7a20_548480e3a6.docx`
- **Working PDF:** `output/resumes/rex_zone_role_app_14a66f897623_Working_rev_ab7adc5325d50511427d7a20_548480e3a6.pdf`
- **Page count:** 1
- The supported edit is present in both extracted DOCX and PDF text. View opened a new PDF tab with `application/pdf`; DOCX and PDF downloads matched the active artifact hashes.
- **Validation report:** `output/reports/app_14a66f897623_resume_document_validation_rev_ab7adc5325d50511427d7a20_548480e3a6.json`
- **Revision sidecar:** `output/resume_edits/app_14a66f897623/rev_ab7adc5325d50511427d7a20_548480e3a6.json`

## J. Tests and build

| Check | Result |
|---|---|
| `python -X utf8 test_resume_document_model.py` | PASS |
| `python -X utf8 -m unittest -v test_resume_document_renderer test_resume_document_save test_resume_document_editor` | PASS — 19 tests |
| `python -X utf8 test_resume_project_edit.py` | PASS |
| `python -X utf8 test_document_history.py` | PASS |
| `npm run build` (TypeScript + Vite production build) | PASS |
| `node frontend/.phase3c3_e2e.cjs` | PASS — real Rex.zone browser flow and rejection/integrity checks |

The renderer/save tests exercise the existing frozen generator validator. No separate `test_resume_generator.py` module is present; the generator’s frozen hash was also asserted by the model regression.

## K. Hash and protection verification

- Frozen `resume_generator.py` SHA-256: `85d8e0c9989995b1f6cdba80e9a96a7ddc99ec629a92fe445cedc6c58f5cf48b` (unchanged).
- Active Working DOCX SHA-256: `c3c8dc40cc0146ddc911c665d075d429e2d80767cec9867054a75e918811dc88`.
- Active Working PDF SHA-256: `79ae5c8566ab49913ccb01921e1faa19479f274a7d54ef9962adf42e966f5201`.
- Existing Final DOCX SHA-256: `ed3e17c4fbefdb349493954e337e7de6e3df67c8d1f722ea3fe6bdc629048c6e`.
- Existing Final PDF SHA-256: `6054419f5e2e74ed6b5442c2fc00ece9610c428236fa34c0458c03f72164c0ee`.
- Browser baseline comparisons passed for Final metadata/files, cover letter, template, canonical profile data, and all other non-application baseline files. The application store changed only in the permitted Rex.zone Working revision metadata.

## L. Remaining limitations

No functional blocker remains for Phase 3C.3. The editor deliberately uses a conservative source-bound lexical policy and does not claim semantic truth verification. The browser emits a nonfatal React `contentEditable`/children warning from the editor integration; the HTTP 409 console entry in the negative test is expected for the rejected unsupported claim. These did not affect build, save, rendering, validation, or artifact integrity.
