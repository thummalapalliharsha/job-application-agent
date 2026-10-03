AI Career OS
AI Career OS is a human-in-the-loop job application workspace for analyzing job descriptions, matching requirements with candidate evidence, preparing tailored resumes and cover letters, managing applications, and maintaining a canonical career profile.
> **Note:** Job applications are submitted manually. AI Career OS does not automatically submit applications to employer portals.
Production
Component	Details
Frontend	https://job-application-agent-zeta.vercel.app
Backend	https://job-application-agent-valc.onrender.com
Frontend Hosting	Vercel
Backend Hosting	Render
Frontend Framework	React + TypeScript + Vite
Backend	Python
Production API	`/api/*` through the Vercel frontend
Production Architecture
```text
User Browser
     |
     v
React + Vite Frontend
     |
     | /api/*
     v
Vercel API Proxy
     |
     | CAREER_OS_API_TOKEN
     v
Render Python Backend
     |
     v
Career OS Services
     |
     +--> Canonical Profile / Application Data
     +--> Job Description Data
     +--> Resume Artifacts
     +--> Cover Letter Artifacts
     +--> Reports
```
The browser communicates with the backend through the Vercel `/api/*` proxy and does not directly call the Render backend.
The Vercel proxy is implemented in `frontend/api/[...path].ts`, with routing configured in `frontend/vercel.json`. It forwards requests to `CAREER_OS_RENDER_URL` and authenticates backend requests using `CAREER_OS_API_TOKEN`.
Project Overview
AI Career OS is designed around a canonical candidate evidence model:
```text
Candidate Profile / Evidence
          |
          v
   Job Description
          |
          v
   Requirement Analysis
          |
          v
    Evidence Matching
          |
          v
Resume / Cover Letter / Application
```
The system supports:
Job description analysis
Requirement extraction
Required/preferred skill identification
Candidate evidence matching
Skill-gap identification
Resume planning and generation
Resume validation and editing
Cover letter generation and editing
Canonical profile editing
Evidence and provenance tracking
Application creation and tracking
Application notes and search
Application history and readiness workflows
Safe application removal
Manual application submission
Key Features
Job Description Intelligence
Analyze job descriptions.
Extract role, required skills, preferred skills, and uncertain requirements.
Match requirements against candidate evidence.
Identify supported skill gaps.
Allow explicit confirmation before supported profile updates.
Avoid adding unsupported candidate claims.
Resume Workflow
```text
Job Description
      |
      v
JD Analysis
      |
      v
Resume Plan
      |
      v
Explicit Approval
      |
      v
Working Resume
      |
      v
Validation / Editing
      |
      v
Final Resume
```
Features include:
Job-specific resume planning
Explicit resume-plan approval
Working Resume generation
DOCX/PDF generation where supported
Resume validation
One-page ATS-oriented workflow
Source-backed resume editing
Validation before saving
Explicit resume finalization
Cover Letter Workflow
Generate job-specific cover letters.
Ground content in candidate evidence.
Support cover-letter editing.
Generate DOCX/PDF artifacts where supported.
Finalize cover letters explicitly.
Profile / Evidence Management
Supported profile areas include:
Name
Headline
Location
Skills
Projects
Experience
Education
Certifications
Profile editing follows:
```text
User Edit
    |
    v
Update Plan
    |
    v
Review
    |
    v
Explicit Confirmation
    |
    v
Canonical Profile Update
```
Profile changes do not automatically regenerate resumes or cover letters and do not silently rewrite existing application plans.
Application Management
Create applications.
Track application status.
Add application notes.
Search applications.
View application history.
Track readiness.
Remove applications with scoped artifact cleanup.
Keep final submission under explicit user control.
Architecture
Frontend
The production frontend uses React, TypeScript, Vite, CSS, and Vercel.
```text
frontend/
frontend/src/
frontend/api/[...path].ts
frontend/vercel.json
```
The frontend uses relative `/api/*` requests.
Backend
The backend is implemented in Python.
Main API entry point:
```text
career_os_api.py
```
The API uses Python's standard-library `ThreadingHTTPServer`.
The backend handles:
API routing
Authentication
Request validation
Host/origin validation
Application workflows
Profile operations
Resume operations
Cover-letter operations
Artifact access
Storage operations
Career OS Services
Important modules include:
```text
application_assistant.py
jd_resume_planner.py
profile_update_agent.py
resume_generator.py
resume_document_model.py
resume_document_renderer.py
resume_document_validation.py
```
Module	Responsibility
`career_os_api.py`	HTTP API and request handling
`application_assistant.py`	Application lifecycle and workflows
`jd_resume_planner.py`	JD analysis and resume planning
`profile_update_agent.py`	Canonical profile update workflow
`resume_generator.py`	Resume generation
`resume_document_model.py`	Source-backed resume document model
`resume_document_renderer.py`	Resume document rendering
`resume_document_validation.py`	Resume validation
Storage
Canonical structured information is stored under:
```text
data/
```
Job-description snapshots are stored under:
```text
job_descriptions/
```
Generated documents and reports are stored under:
```text
output/
```
The canonical profile/evidence data is the source of truth rather than generated resume documents.
Project Structure
```text
job-application-agent/
|
|-- frontend/
|   |-- api/
|   |   `-- [...path].ts
|   |-- public/
|   |-- src/
|   |-- package.json
|   |-- package-lock.json
|   |-- vercel.json
|   |-- vite.config.ts
|   `-- tsconfig*.json
|
|-- data/
|-- job_descriptions/
|-- output/
|-- templates/
|-- resumes/
|-- tests/
|
|-- docs/
|   |-- handoffs/
|   `-- reports/
|
|-- career_os_api.py
|-- application_assistant.py
|-- jd_resume_planner.py
|-- profile_update_agent.py
|-- resume_generator.py
|-- resume_document_model.py
|-- resume_document_renderer.py
|-- resume_document_validation.py
|-- app.py
|-- Dockerfile
|-- requirements.txt
|-- agent_instructions.md
`-- README.md
```
The `docs/` directory contains historical engineering and project handoff documentation.
Technology Stack
Frontend
React
TypeScript
Vite
CSS
Vercel
Vercel serverless API proxy
Backend
Python
`ThreadingHTTPServer`
JSON-based storage
`python-docx`
Document processing
LibreOffice
Poppler utilities
Application Intelligence
Job description analysis
Requirement extraction
Evidence matching
Resume planning
Source-backed document generation
Profile update workflow
Evidence/provenance preservation
Testing
Python `unittest`
Project-specific regression tests
Frontend production build validation
Git whitespace validation
Local Development
Prerequisites
Recommended environment:
Python 3.12+
Node.js
npm
LibreOffice
Poppler utilities
Backend Setup
From the repository root:
```bash
python -m venv .venv
```
Windows PowerShell activation:
```powershell
.\.venv\Scripts\Activate.ps1
```
Install dependencies:
```bash
python -m pip install -r requirements.txt
```
Start the backend:
```bash
python career_os_api.py
```
The development backend listens on:
```text
http://127.0.0.1:8504
```
Frontend Setup
Open a second terminal:
```bash
cd frontend
npm ci
npm run dev
```
The Vite development server runs at:
```text
http://127.0.0.1:5173
```
During local development, `/api/*` requests are proxied to:
```text
http://127.0.0.1:8504
```
Frontend Production Build
```bash
cd frontend
npm run build
```
Preview locally:
```bash
npm run preview
```
Environment Variables
Frontend
The production frontend uses relative `/api/*` requests, so the browser does not need a separate production backend URL.
Example:
```text
frontend/.env.example
```
Do not expose backend authentication secrets through frontend variables. In particular, never expose `CAREER_OS_API_TOKEN` through a `VITE_*` variable.
Vercel
Variable	Purpose
`CAREER_OS_RENDER_URL`	Render backend origin
`CAREER_OS_API_TOKEN`	Shared secret used by the Vercel API proxy
Example backend origin:
```text
https://job-application-agent-valc.onrender.com
```
`CAREER_OS_RENDER_URL` should not include `/api`.
Render
Variable	Purpose
`CAREER_OS_ENV`	Production environment configuration
`CAREER_OS_API_TOKEN`	Shared authentication token
`CAREER_OS_ALLOWED_HOSTS`	Allowed backend hostnames
`CAREER_OS_STORAGE_ROOT`	Persistent storage root
Additional supported configuration includes:
```text
CAREER_OS_HOST
CAREER_OS_PORT
CAREER_OS_ALLOWED_ORIGINS
CAREER_OS_ALLOWED_HOSTS
```
Render provides the production `PORT`.
Secrets
Never commit API tokens, passwords, private credentials, or production secrets.
Use `.env.example` for placeholders and configure real production secrets through Vercel and Render.
Deployment
Frontend
The production frontend is deployed on Vercel.
Project root:
```text
frontend/
```
Build command:
```bash
npm run build
```
Vercel routing:
```text
frontend/vercel.json
```
API proxy:
```text
frontend/api/[...path].ts
```
Backend
The backend is deployed on Render using the repository's:
```text
Dockerfile
```
The container starts:
```text
career_os_api.py
```
Production backend:
```text
https://job-application-agent-valc.onrender.com
```
Production Request Flow
```text
Browser
   |
   | GET / POST / DELETE /api/*
   v
Vercel React/Vite Frontend
   |
   v
Vercel API Proxy
   |
   | CAREER_OS_API_TOKEN
   v
Render Python Backend
   |
   v
Career OS Services
   |
   +--> data/
   +--> job_descriptions/
   +--> output/
```
API Overview
The production browser-facing API is available under `/api` on the Vercel frontend origin.
Health, Bootstrap, Profile and Search
Method	Endpoint	Purpose
`GET`	`/api/health`	Backend health check
`GET`	`/api/bootstrap`	Initial application/profile data
`GET`	`/api/profile`	Canonical profile summary
`GET`	`/api/applications`	Application list
`GET`	`/api/search`	Application/data search
Job Analysis
Method	Endpoint	Purpose
`POST`	`/api/analyze`	Analyze a job description
`POST`	`/api/applications`	Create an application
Profile Editing
Method	Endpoint	Purpose
`POST`	`/api/profile/edit/plan`	Create a profile edit plan
`POST`	`/api/profile/edit/apply`	Explicitly confirm and apply a profile edit
Resume Workflow
Method	Endpoint	Purpose
`POST`	`/api/applications/{id}/approve-resume`	Approve resume plan
`POST`	`/api/applications/{id}/confirm-skill-gap`	Confirm supported skill-gap update
`POST`	`/api/applications/{id}/generate-resume`	Generate Working Resume
`POST`	`/api/applications/{id}/finalize-resume`	Finalize resume
`POST`	`/api/applications/{id}/resume-document/validate`	Validate resume document changes
`POST`	`/api/applications/{id}/resume-document/save`	Save validated resume changes
`POST`	`/api/applications/{id}/resume-edit`	Apply supported resume edits
Resume and Artifact Retrieval
Method	Endpoint	Purpose
`GET`	`/api/applications/{id}/resume-editor`	Retrieve resume editor data
`GET`	`/api/applications/{id}/resume-document`	Retrieve resume document data
`GET`	`/api/artifact?ref=...`	Retrieve supported stored artifacts
Cover Letter
Method	Endpoint	Purpose
`POST`	`/api/applications/{id}/cover-letter`	Generate/update cover letter
`POST`	`/api/applications/{id}/cover-letter-edit`	Edit cover letter
Application Tracking
Method	Endpoint	Purpose
`POST`	`/api/applications/{id}/status`	Update application status
`POST`	`/api/applications/{id}/note`	Add application note
`DELETE`	`/api/applications/{id}`	Remove an application and safely scoped related artifacts
Evidence and Provenance
AI Career OS uses a canonical evidence model:
```text
Canonical Candidate Profile
          |
          v
     Job Description
          |
          v
    Requirement Matching
          |
          v
 Resume / Cover Letter
```
Generated application documents are outputs of the evidence model and are not intended to replace the canonical candidate profile.
Candidate evidence can include:
Skills
Projects
Experience
Education
Certifications
Achievements
Other supported profile evidence
Where supported, evidence records retain provenance and verification information.
Application Workflow
```text
Job Description
       |
       v
JD Analysis
       |
       v
Requirement Extraction
       |
       v
Candidate Evidence Matching
       |
       v
Application Record
       |
       v
Resume Plan
       |
       v
Explicit Resume Approval
       |
       v
Working Resume
       |
       v
Resume Validation / Editing
       |
       v
Final Resume
       |
       +--------------------+
       |                    |
       v                    v
Cover Letter          Application Package
       |                    |
       +----------+---------+
                  |
                  v
        Manual Employer Submission
                  |
                  v
        Explicit Submission Confirmation
                  |
                  v
               Applied
```
Application Safety
The system does not:
Automatically submit applications.
Automatically log into employer portals.
Automatically fill employer application forms.
Solve CAPTCHAs.
Store employer portal passwords.
Automatically send applications to employers.
Final employer submission is manual and remains under user control.
Application Removal
When an application is removed:
The target application is removed.
Matching application history is cleaned.
Related artifacts are cleaned only within approved/scoped locations.
Shared profile/project/skill information is preserved.
Unrelated applications and artifacts are preserved.
Testing
Python Test Suite
```bash
python -m unittest discover -s . -p "test_*.py"
```
Profile Update Regression
```bash
python test_profile_update_agent.py
```
Frontend Build
```bash
cd frontend
npm ci
npm run build
```
Git Validation
```bash
git diff --check
```
Development Notes
The repository also contains an additional Streamlit interface:
```text
app.py
```
The deployed production UI is the React/Vite application under:
```text
frontend/
```
Production architecture:
```text
React/Vite Frontend
        |
        v
Vercel API Proxy
        |
        v
Python Backend
```
Documentation
Historical engineering and handoff documentation is organized under:
```text
docs/
|
|-- handoffs/
|
`-- reports/
```
These documents preserve development history, engineering decisions, project handoff information, and historical implementation reports.
The root `README.md` is the primary current project documentation.
Security
Never commit API tokens.
Never commit passwords.
Never commit private credentials.
Keep `CAREER_OS_API_TOKEN` server-side.
Never expose backend authentication tokens through `VITE_*` variables.
Use `.env.example` for placeholder configuration.
Configure production secrets through Vercel and Render.
Do not store employer portal credentials.
Keep final application submission under explicit user control.
Production Configuration Summary
Area	Configuration
Frontend	React + TypeScript + Vite
Frontend Hosting	Vercel
Backend	Python
Backend Hosting	Render
API Proxy	Vercel `/api/*`
Backend API	`career_os_api.py`
Frontend Production URL	https://job-application-agent-zeta.vercel.app
Backend Production URL	https://job-application-agent-valc.onrender.com
Browser API	`/api/*` on frontend origin
Canonical Storage	`data/`
Job Description Storage	`job_descriptions/`
Generated Artifacts	`output/`
Profile Updates	Plan / Review / Explicit Confirmation
Application Submission	Manual
Frontend Build	`npm run build`
Backend Start	`python career_os_api.py`
Project Status
AI Career OS is deployed with:
React/Vite production frontend
Vercel API proxy
Python backend
Render deployment
Canonical JSON-backed profile/application storage
Job description analysis
Evidence matching
Resume generation
Resume validation/editing
Cover letter generation/editing
Profile editing
Application tracking
Application history
Safe application removal
Manual application submission
Live Application
https://job-application-agent-zeta.vercel.app
Backend Service
https://job-application-agent-valc.onrender.com
Production Request Flow
```text
Browser
  |
  v
Vercel React/Vite Frontend
  |
  v
/ api/*
  |
  v
Vercel Serverless Proxy
  |
  v
Render Python Backend
  |
  v
Career OS Services
  |
  +--> Canonical Profile
  +--> Applications
  +--> Job Descriptions
  +--> Resumes
  +--> Cover Letters
  +--> Reports
```
---
AI Career OS provides an evidence-backed workflow for preparing job applications while keeping candidate data centralized and important actions under explicit user control.