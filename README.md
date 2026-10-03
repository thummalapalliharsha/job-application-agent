# AI Career OS

AI Career OS is a human-in-the-loop job application workspace for matching job descriptions to candidate evidence, preparing resumes and cover letters, and tracking application progress. Job applications are submitted manually; the service does not automate employer portals.

## Production

- **Frontend:** [job-application-agent-zeta.vercel.app](https://job-application-agent-zeta.vercel.app)
- **Backend:** [job-application-agent-valc.onrender.com](https://job-application-agent-valc.onrender.com)

The browser uses same-origin `/api/*` requests. It does not call the Render service directly.

```text
Browser
  -> Vercel React/Vite frontend
  -> Vercel /api/* rewrite and serverless proxy
  -> Render Python backend
  -> Career OS services and canonical JSON storage
```

The Vercel rewrite sends `/api/:path*` to `frontend/api/[...path].ts`. That proxy forwards the request to `CAREER_OS_RENDER_URL` and adds the server-side bearer token. The browser-facing API origin is the Vercel URL; `CAREER_OS_RENDER_URL` is the backend origin without an `/api` suffix.

## Features

- Analyze job descriptions and map required, preferred, and uncertain requirements to profile evidence.
- Review and explicitly approve a resume plan before generating a Working Resume.
- Generate and validate one-page, ATS-oriented DOCX/PDF resumes.
- Edit Working Resume content through a source-backed document model; validate changes before saving.
- Generate, edit, and finalize tailored cover letters with DOCX/PDF artifacts.
- Edit the canonical profile through a plan-and-confirm workflow that preserves evidence and provenance.
- Track application status, notes, search, history, and readiness checklists.
- Keep final artifacts and application submission under explicit user control.

## Architecture

- **React + TypeScript + Vite** (`frontend/src/`): production browser application.
- **Vercel proxy** (`frontend/api/[...path].ts`, `frontend/vercel.json`): same-origin `/api/*` forwarding to the backend.
- **Python HTTP API** (`career_os_api.py`): standard-library `ThreadingHTTPServer` with request validation, authentication, application workflows, and document operations.
- **Career services:** `jd_resume_planner.py`, `application_assistant.py`, `profile_update_agent.py`, and the resume document model/renderer/validation modules.
- **Canonical storage:** JSON records under `data/`; job-description snapshots under `job_descriptions/`; generated documents and reports under `output/`.

The repository also contains `app.py`, an additional Streamlit interface. The deployed production frontend is the React/Vite application described above.

## Project Structure

```text
.
|-- frontend/
|   |-- api/[...path].ts       # Vercel API proxy
|   |-- src/                   # React application and styles
|   |-- package.json
|   |-- vercel.json            # /api/* rewrite
|   `-- vite.config.ts         # Local /api proxy to port 8504
|-- data/                      # Canonical profile and application JSON
|-- job_descriptions/          # Saved job-description snapshots
|-- output/                    # Historical/generated documents and reports
|-- templates/                 # Resume DOCX template
|-- resumes/                   # Source resume reference
|-- tests/                     # JD regression fixtures and runners
|-- docs/
|   |-- handoffs/              # Historical project handoff notes
|   `-- reports/               # Historical engineering reports
|-- career_os_api.py
|-- application_assistant.py
|-- jd_resume_planner.py
|-- profile_update_agent.py
|-- resume_document_*.py
|-- resume_generator.py
|-- app.py                     # Additional Streamlit interface
|-- Dockerfile                 # Python backend container
`-- requirements.txt
```

The documents under `docs/reports/` and `docs/handoffs/` are historical records, not current deployment instructions or requirements.

## Local Development

### Backend

Python 3.12 is used by the backend image. Create and activate a virtual environment, then install the Python dependencies:

```bash
python -m venv .venv
# Activate .venv for your shell, then:
python -m pip install -r requirements.txt
python career_os_api.py
```

In development, the API listens on `127.0.0.1:8504` by default. The document workflow uses `python-docx`; PDF rendering requires LibreOffice and Poppler utilities (`soffice`, `pdfinfo`, and `pdftotext`).

### Frontend

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Vite serves the app at `http://127.0.0.1:5173` and proxies `/api/*` to `http://127.0.0.1:8504`, as configured in `vite.config.ts`. The current client uses relative `/api` URLs; `VITE_API_BASE_URL` is not read by `frontend/src/apiUrl.ts`.

Build and preview the production frontend locally:

```bash
cd frontend
npm run build
npm run preview
```

## Deployment Configuration

### Vercel frontend and proxy

Configure the Vercel project root as `frontend/`. Its build command is `npm run build`; `frontend/vercel.json` rewrites `/api/:path*` to the catch-all serverless proxy.

Set these **server-side Vercel environment variables**:

| Variable | Purpose |
|---|---|
| `CAREER_OS_RENDER_URL` | Render backend origin, for example `https://job-application-agent-valc.onrender.com`; do not append `/api`. |
| `CAREER_OS_API_TOKEN` | Shared secret forwarded to Render as a bearer token. Keep it server-side; never expose it as a `VITE_*` variable. |

### Render Python backend

Deploy the repository’s root `Dockerfile`. It installs the Python requirements plus LibreOffice, Poppler, and Liberation fonts, then starts `career_os_api.py`. Render supplies `PORT`.

Configure these backend variables:

| Variable | Purpose |
|---|---|
| `CAREER_OS_ENV` | Set to `production` to enable production checks. |
| `CAREER_OS_API_TOKEN` | Same secret as the Vercel proxy; production requires at least 32 characters. |
| `CAREER_OS_ALLOWED_HOSTS` | Include the Render service hostname so the backend host check accepts proxy traffic. |
| `CAREER_OS_STORAGE_ROOT` | Root of storage containing `data/`, `job_descriptions/`, and `output/`. In production, point it at a persistent mount so canonical data and generated artifacts survive service restarts. |

The backend also supports `CAREER_OS_HOST`, `CAREER_OS_PORT`, `CAREER_OS_ALLOWED_ORIGINS`, and `CAREER_OS_ALLOWED_HOSTS` for host, port, origin, and host allow-list configuration. `PORT` takes precedence over `CAREER_OS_PORT`.

## Environment Variables

The Vercel proxy and Render backend must use the same `CAREER_OS_API_TOKEN`. The frontend sends relative `/api` requests, so its production API routing is provided by the Vercel rewrite/proxy rather than a browser-visible backend URL. Never put the API token in frontend code or a `VITE_*` variable.

For local development, no API token is required unless `CAREER_OS_API_TOKEN` is configured. Optional `CAREER_OS_STORAGE_ROOT` can point to a separate local data root with the same `data/`, `job_descriptions/`, and `output/` layout.

## API Overview

The browser-facing API is rooted at the Vercel origin under `/api`; the proxy forwards those paths to the Render backend.

| Method | Routes | Purpose |
|---|---|---|
| `GET` | `/api/health`, `/api/bootstrap`, `/api/profile`, `/api/applications`, `/api/search` | Health, initial app data, profile, application list, and search. |
| `GET` | `/api/applications/{id}/resume-editor`, `/api/applications/{id}/resume-document`, `/api/artifact?ref=...` | Resume editor/document data and validated stored artifacts. |
| `POST` | `/api/analyze`, `/api/applications` | Analyze a JD or create an application record. |
| `POST` | `/api/profile/edit/plan`, `/api/profile/edit/apply` | Preview and explicitly confirm canonical profile updates. |
| `POST` | `/api/applications/{id}/approve-resume`, `/confirm-skill-gap`, `/generate-resume`, `/finalize-resume` | Resume-plan approval, skill-gap confirmation, and resume lifecycle actions. |
| `POST` | `/api/applications/{id}/resume-document/validate`, `/resume-document/save`, `/resume-edit` | Validate and save source-backed Working Resume edits. |
| `POST` | `/api/applications/{id}/cover-letter`, `/cover-letter-edit`, `/status`, `/note` | Cover-letter and application-tracking actions. |
| `DELETE` | `/api/applications/{id}` | Remove an application and its safely scoped artifacts. |

The backend protects API routes with the configured bearer token, validates request hosts and origins, and restricts artifact access to supported output locations.

## Evidence and Provenance

- `data/*.json` is the canonical structured profile and application store; generated resumes are not the source of truth.
- Skills, projects, experience, education, and certifications retain their source/evidence and verification metadata.
- JD planning selects supported profile evidence; unsupported claims are not added to resumes or cover letters.
- Profile edits are planned, reviewed, and explicitly confirmed. Changed verified records are marked candidate-provided; prior evidence is retained.
- Existing application plans and final documents are not automatically rewritten or regenerated by profile edits.
- Resume edits are checked against the source-backed document model and validation rules before Working artifacts are saved.
- Application submission remains manual; the application record changes to `applied` only after explicit confirmation.

## Tests

From the repository root, run the Python unittest suite:

```bash
python -m unittest discover -s . -p "test_*.py"
```

The profile-update agent also has a standalone regression runner:

```bash
python test_profile_update_agent.py
```

Build the frontend from `frontend/`:

```bash
npm ci
npm run build
```
