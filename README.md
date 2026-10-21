# Career OS / Job Application Agent

Career OS is a human-in-the-loop job-application workspace. It uses a job description and a canonical candidate profile to create an evidence-backed application plan, then supports resume and cover-letter preparation while keeping review and submission under the user's control.

Applications are submitted manually. Career OS does not log into employer portals or submit applications automatically.

## Production

- Frontend: [job-application-agent-zeta.vercel.app](https://job-application-agent-zeta.vercel.app)
- Backend: [job-application-agent-valc.onrender.com](https://job-application-agent-valc.onrender.com)
- Frontend hosting: Vercel
- Backend hosting: Render, using the root `Dockerfile`

The browser sends relative `/api/*` requests to the Vercel frontend. The Vercel proxy forwards requests to the Render API and supplies the backend API token.

```text
Browser
  ↓
Vercel React/Vite frontend
  ↓
Vercel /api proxy
  ↓
Render Python API (career_os_api.py)
  ↓
Career OS application, profile, and document services
```

## Features

### Applications and JD Intelligence

- Create and track applications from a supplied job description.
- Analyze role requirements and classify candidate evidence as supported, partial, unsupported, or unknown.
- Review the Evidence Map and identify required skill gaps.
- Confirm supported candidate-provided skill information through the profile workflow.
- Search application records, view history, add notes, and remove an application with scoped cleanup.

### Project Strategy

- Automatic, job-specific project recommendations are the default.
- In JD Intelligence, click **EDIT PROJECTS** to choose canonical projects that are completed and verified.
- The limit is three projects, and selection order is preserved.
- **CONFIRM PROJECTS** persists the selection through the existing resume-edit workflow and refreshes the reviewed plan.
- The Evidence Map and reviewed-plan approval use the confirmed selection. Backend approval checks the plan against canonical evidence.
- If projects are not edited, automatic recommendations remain in effect.

### Resume Workflow

- Review and explicitly approve a deterministic Resume Plan before generation.
- Generate and validate a Working Resume before it is activated.
- Review or edit source-backed resume content in Resume Workspace.
- Finalize a validated Working Resume separately; existing Final artifacts are preserved through the lifecycle.
- Generate DOCX/PDF artifacts where the installed document tools support them.

### Cover Letters and Profile

- Generate and edit application-specific cover letters using profile evidence, with Working and Final artifact states.
- View the canonical profile; edit existing information or add Skills, Projects, Experience, Education, Certifications, and Achievements.
- Review profile changes before saving. Existing profile validation and evidence/provenance handling remain in force.

## Profile Security

Every persistent profile mutation requires a six-digit PIN at save time. The React and Streamlit interfaces prompt when a user confirms a profile change. The backend independently verifies the PIN at the shared canonical profile writer, so a direct API request cannot bypass verification. Missing configuration, missing or malformed PINs, and incorrect PINs fail closed before profile data is written. Read-only profile access does not require a PIN.

The backend reads `CAREER_OS_PROFILE_PIN_HASH` from its process environment. It must contain a salted scrypt hash, not the PIN. The hash is not stored in profile/application JSON or a local security file, and the API exposes only whether a valid hash is configured. Configure it privately in Render's environment settings; never put a PIN or hash in Git, frontend variables, browser storage, or this README.

To generate a hash locally, run this on a trusted machine and enter the PIN only at the hidden prompts:

```bash
python -m profile_security
```

The command prints the scrypt hash. Set that value as `CAREER_OS_PROFILE_PIN_HASH` in Render. Do not send the PIN or hash to the application, GitHub, or Copilot. For local development, set the hash in the backend process environment before starting the API.

## Architecture

The production web UI is React, TypeScript, and Vite under `frontend/`. `frontend/api/[...path].ts` implements the Vercel serverless proxy; `frontend/vercel.json` rewrites `/api/*` to it. The Python API uses the standard-library `ThreadingHTTPServer` in `career_os_api.py` and delegates to root-level Career OS services.

| Module | Responsibility |
| --- | --- |
| `career_os_api.py` | HTTP routing, request checks, profile/application APIs, artifacts |
| `career_os_config.py` | Environment-backed storage and deployment paths |
| `application_assistant.py` | Application lifecycle and deterministic reviewed-plan approval |
| `jd_resume_planner.py` | JD analysis, requirement matching, and resume planning |
| `profile_update_agent.py` | Profile edit plans, validation, and canonical profile writes |
| `profile_security.py` | Scrypt PIN hash generation and server-side verification |
| `resume_generator.py` | Resume generation and validation |
| `resume_document_model.py` | Structured, source-backed resume document model |
| `resume_document_renderer.py` | DOCX/PDF rendering support |
| `resume_document_validation.py` | Resume edit and document validation |
| `app.py` | Separate Streamlit interface using the shared services |

Canonical profile and application data are JSON files under `data/`. Job-description snapshots are under `job_descriptions/`; reports and generated artifacts are under `output/`. `CAREER_OS_STORAGE_ROOT` can select a different root. Render's filesystem is ephemeral unless backed by a persistent disk. The current Render plan does not provide a persistent disk, so file-backed data and artifacts may not survive a restart or redeploy.

When `CAREER_OS_STORAGE_BACKEND=postgres` is selected, profile, application, and document-history records use PostgreSQL. The application does not create its PostgreSQL schema at startup: an operator must first apply the additive `postgres_schema_sql()` schema to the intended database. The explicit `run_staging_backfill()` path also applies that schema, but it additionally imports and reconciles profile, application, job-description, report, and history data in one transaction; it is not a schema-only command.

For schema-only preparation, use the dedicated local-target command `postgres_schema_migrate.py`. It is deliberately restricted to `127.0.0.1:55432/career_test` as user `career_test`; it rejects connection URLs and remote/shared targets, requires explicit disposable confirmation and expected identity arguments, verifies the connected database/user/PostgreSQL 16 version before DDL, rejects conflicting relation kinds, and validates required columns/types before committing. All DDL runs in one transaction. It never imports application data and does not invoke `run_staging_backfill()`.

Non-production operator procedure:

1. Provision a dedicated disposable local PostgreSQL 16 database and independently verify the container, loopback-only port mapping, dedicated volume, database, and role. Take a restorable snapshot before schema changes. Do not target production or shared/remote staging.
2. Set the connection environment in PowerShell. Load the password from an ACL-protected secret file without echoing it:

   ```powershell
   $secretPath = '<ACL-protected secret file path>'
   $env:POSTGRES_PASSWORD = [System.IO.File]::ReadAllText($secretPath).TrimEnd([char[]]@(10,13))
   $env:CAREER_OS_STORAGE_BACKEND = 'postgres'
   $env:POSTGRES_HOST = '127.0.0.1'
   $env:POSTGRES_PORT = '55432'
   $env:POSTGRES_DB = 'career_test'
   $env:POSTGRES_USER = 'career_test'
   $env:POSTGRES_SSLMODE = 'disable'
   ```

   Never put the password in command arguments, scripts, source, or logs.
3. From the repository root, run:

   ```powershell
   python postgres_schema_migrate.py `
     --confirm-disposable `
     --expected-host 127.0.0.1 `
     --expected-port 55432 `
     --expected-database career_test `
     --expected-user career_test
   ```

   The command refuses other targets. Inspect the success result; on any exception the DDL transaction rolls back.
4. Verify on the same connection using read-only queries:

   ```sql
   SELECT current_database(), current_user, current_setting('server_version_num');
   SELECT table_name, column_name, data_type, is_identity
   FROM information_schema.columns
   WHERE table_schema = 'public'
     AND table_name IN ('document_history_records', 'document_history_migrations')
   ORDER BY table_name, ordinal_position;
   ```

   Confirm the expected database/user and PostgreSQL major version 16, plus `document_id`, `application_id`, `payload_json`, identity `history_position`, timestamps, and migration marker columns. Re-run the schema-only command to confirm repeatability.
5. Keep schema-only preparation separate from `run_staging_backfill()`. The latter is an explicit full data-import/reconciliation operation, guarded for non-production staging but not limited to a disposable local database.

The application does not apply schema automatically at startup. Rollback of uncommitted DDL is automatic on failure. After a successful commit, do not drop tables or manually delete schema objects as an ad hoc rollback; schema is additive and may contain live records. Restore the pre-change disposable snapshot or use a separately reviewed forward migration. Schema application itself does not import history; the runtime importer records its own legacy source marker on first access.

On first history access, if `data/document_history.json` exists, a valid legacy snapshot is imported transactionally into `document_history_records`; the source file is retained and its SHA-256 and imported count are recorded in `document_history_migrations`. A missing source file leaves PostgreSQL history unchanged. An existing empty `{"documents":[]}` file is recorded as an empty migration, so later source changes are detected. Legacy entries without IDs receive generated stable database IDs; source order and duplicate entries are preserved. The runtime importer and staging backfill share the same advisory lock, source hash, marker, and conflict checks. Repeated imports of the same source are no-ops. Malformed/unreadable JSON, a changed source hash, or existing PostgreSQL history without the marker stops the operation visibly; it does not clear, merge, or overwrite history.

For recovery, stop further imports when a history error is reported. Preserve both the source file and a database snapshot; do not delete a marker or history rows to force a retry. A failed import/backfill transaction rolls back its inserted history and marker. After a committed migration, changing the source file or switching back to file mode does not reverse database writes. Recovery from committed data requires an explicit, reviewed reconciliation or restoration from the pre-migration snapshot, with the migration marker reconciled consistently. In file mode, history remains in `data/document_history.json` with stable IDs and atomic snapshot writes.

## Repository Structure

Production Python modules remain at the repository root; they are not in a `backend/` directory.

```text
.
├── app.py
├── application_assistant.py
├── career_os_api.py
├── career_os_config.py
├── jd_resume_planner.py
├── profile_security.py
├── profile_update_agent.py
├── resume_generator.py
├── resume_document_model.py
├── resume_document_renderer.py
├── resume_document_validation.py
├── data/
├── docs/
├── frontend/
│   ├── api/
│   ├── public/
│   └── src/
├── job_descriptions/
├── output/
├── resumes/
├── templates/
└── tests/
    ├── application/
    ├── profile/
    ├── resume/
    ├── jd/
    ├── planning/
    ├── cover_letter/
    ├── ui/
    ├── jd_regression_suite/
    └── jd_regression_suite_summary_fix/
```

`docs/` contains handoffs and reports. The root `resumes/` and `output/` directories are separate from the production Python source modules.

## Local Development

The backend Docker image uses Python 3.12. From the repository root, create and activate a virtual environment, install dependencies, configure a local PIN hash if profile writes are needed, and start the API:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m profile_security
$env:CAREER_OS_PROFILE_PIN_HASH = "<locally-generated-scrypt-hash>"
python career_os_api.py
```

The API defaults to `http://127.0.0.1:8504`. The hash placeholder is not a real credential; keep the generated value out of source control. The separate Streamlit interface can be run with `streamlit run app.py`.

In a second terminal, install frontend dependencies and start Vite:

```powershell
cd frontend
npm ci
npm run dev
```

Vite serves the frontend at `http://127.0.0.1:5173` and proxies `/api` to the local Python API. Build and preview the production frontend with:

```powershell
npm run build
npm run preview
```

## Environment Variables

Configure secrets in the hosting provider's private environment settings. Do not use `VITE_*` variables for backend secrets.

| Variable | Used by | Purpose |
| --- | --- | --- |
| `CAREER_OS_RENDER_URL` | Vercel API proxy | Render backend origin, without an `/api` suffix |
| `CAREER_OS_API_TOKEN` | Vercel proxy and Render API | Shared bearer token; production backend requires at least 32 characters |
| `CAREER_OS_PROFILE_PIN_HASH` | Render API | Required scrypt hash for profile-write verification |
| `CAREER_OS_ENV` | Render API | Runtime mode; `production`/`prod` activates production token checks |
| `CAREER_OS_ALLOWED_HOSTS` | Render API | Additional accepted `Host` values |
| `CAREER_OS_ALLOWED_ORIGINS` | Render API | Additional accepted browser origins |
| `CAREER_OS_HOST` | Render API | Bind address; production defaults to `0.0.0.0` |
| `PORT` | Render API | Render-provided listening port; otherwise `CAREER_OS_PORT` or `8504` is used |
| `CAREER_OS_PORT` | Render API | Optional listening port when `PORT` is absent |
| `CAREER_OS_STORAGE_ROOT` | Backend services | Optional root for data, job descriptions, and output files |
| `CAREER_OS_POSTGRES_STAGING_HOST` | Explicit staging backfill only | Required exact Neon staging hostname allow-list; must match the configured target |
| `CAREER_OS_FRONTEND_DIR` | Backend API | Optional location of the built frontend served by the Python API |
| `CAREER_OS_POSTGRES_DIAGNOSTIC_ENABLED` | Render API | Temporary PostgreSQL diagnostic; disabled unless exactly `1` |

The checked-in `frontend/.env.example` has a frontend API-base example; the current React client uses relative `/api/*` paths and does not read that variable.

The explicit staging backfill additionally requires `CAREER_OS_ENV=staging` and `CAREER_OS_POSTGRES_STAGING_HOST` set to the exact staging hostname. The connection target must match that allow-list and be a Neon hostname whose labels identify staging; production-looking, arbitrary, incomplete, or ambiguous targets are rejected before health checks or database connections.

## Deployment

- **Frontend:** Vercel project rooted at `frontend/`; `npm run build` is the production build command. `frontend/vercel.json` routes `/api/*` through `frontend/api/[...path].ts`.
- **Backend:** Render Docker service built from the repository-root `Dockerfile`; the container starts `python career_os_api.py`.
- **Secrets:** Set `CAREER_OS_RENDER_URL` and `CAREER_OS_API_TOKEN` in Vercel; set `CAREER_OS_API_TOKEN` and `CAREER_OS_PROFILE_PIN_HASH` in Render. The browser never receives either secret.
- **Temporary PostgreSQL diagnostic:** To enable, set `CAREER_OS_POSTGRES_DIAGNOSTIC_ENABLED=1` on Render. Send `GET /api/diagnostics/postgres-application-store` with the existing `Authorization: Bearer <CAREER_OS_API_TOKEN>` header. Remove the flag after diagnosis; the endpoint is hidden when disabled.
- No Render service manifest or CI/CD workflow is present in the repository; provider-side deployment settings control the services.
- Render's current plan has no persistent disk. Plan for possible loss of local JSON data and generated files on restart/redeploy before relying on this storage for durable records.

## Testing

Run the unittest-discoverable suite from the repository root:

```powershell
python -m unittest discover -s tests
```

Run focused suites by their categorized module paths:

```powershell
python -m unittest tests.profile.test_profile_edit_api
python -m unittest tests.profile.test_skill_gap_confirmation
python -m unittest tests.planning.test_reviewed_plan_lifecycle
python -m unittest tests.resume.test_resume_document_model
```

Some regression checks are standalone scripts rather than `unittest` cases. Run them directly:

```powershell
python tests/profile/test_profile_update_agent.py
python tests/planning/test_manual_project_selection.py
python tests/application/test_application_assistant.py
python tests/application/test_document_history.py
python tests/ui/test_phase10_ui.py
```

At the time of this README update, `python -m unittest discover -s tests` runs 72 tests but has two known resume-document failures: the expanded editor test raises `IndexError` for an empty certifications section, and the expanded save test rejects a skill as a duplicate. The standalone manual-project-selection script currently cannot find its temporary `plan.json`; the Phase 10 UI script references `/home/ubuntu/phase10_before_hashes.txt`, which is unavailable in this Windows workspace. These are test limitations, not documented as working behavior.

Validate the frontend and whitespace separately:

```powershell
cd frontend
npm run build
cd ..
git diff --check
```

## Security Notes

- Keep `CAREER_OS_API_TOKEN` and `CAREER_OS_PROFILE_PIN_HASH` out of Git and frontend code.
- Do not commit `.env.local` or other local secret files.
- The six-digit PIN is verified server-side before profile persistence; failed verification leaves profile data unchanged.
- Profile security status is read-only and does not expose the PIN or its hash.
- Keep employer credentials out of Career OS; application submission remains manual.

## Project Status

Career OS is a deployed production application with JD Intelligence, automatic and inline manual Project Strategy, Evidence Map, reviewed-plan approval, resume and cover-letter workflows, application history, profile editing, and server-side PIN protection for profile writes. Known test failures and Render file-storage durability limitations are listed above; no future capabilities are presented as implemented.