import { StrictMode, Suspense, lazy, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'

import { createRoot } from 'react-dom/client'

import './styles.css'

import { apiUrl } from './apiUrl'

import { LoadingStatus } from './components/LoadingStatus'

const ResumeDocumentEditor = lazy(() => import('./components/ResumeDocumentEditor').then((module) => ({ default: module.ResumeDocumentEditor })))



type AppRecord = Record<string, any>

type Boot = { profile: AppRecord; applications: AppRecord[]; counts: Record<string, number> }

type Route = 'home' | 'new' | 'analysis' | 'resume' | 'letter' | 'package' | 'history' | 'profile' | 'search' | 'settings'



function ApplicationInfo({ app, go }: { app?: AppRecord; go: (r: Route) => void }) {

  if (!app) return <Workspace title="APPLICATION INFORMATION" eyebrow="APPLICATION DETAILS" intro="Review the currently selected application." ><div className="notice-panel">No application is currently selected.</div><button className="button quiet" onClick={() => go('package')}>← PACKAGE ASSEMBLY</button></Workspace>

  const details: [string, string][] = [

    ['Company', app.company_name || '—'],

    ['Application ID', app.application_id || '—'],

    ['Role', app.job_title || 'Not provided'],

    ['Status', app.current_status || '—'],

    ['Location', app.location || '—'],

    ['Source', app.source_platform || '—'],

    ['Date added', app.date_added || '—'],

    ['Job URL', app.job_url || '—'],

  ]

  return <Workspace title="APPLICATION INFORMATION" eyebrow="APPLICATION DETAILS" intro="Read-only details for the application selected in this workspace."><div className="analysis-grid">{details.map(([label, value]) => <div className="analysis-card" key={label}><span className="card-label">{label.toUpperCase()}</span><p>{value}</p></div>)}</div>{app.job_description_text && <div className="analysis-card full"><span className="card-label">JOB DESCRIPTION</span><p style={{ whiteSpace: 'pre-wrap' }}>{app.job_description_text}</p></div>}<button className="button quiet" onClick={() => go('package')}>← PACKAGE ASSEMBLY</button></Workspace>

}



const nav: { key: Route; label: string; index: string }[] = [

  { key: 'home', label: 'Command center', index: '00' },

  { key: 'new', label: 'New application', index: '01' },

  { key: 'analysis', label: 'JD intelligence', index: '02' },

  { key: 'resume', label: 'Resume workspace', index: '03' },

  { key: 'letter', label: 'Cover letter', index: '04' },

  { key: 'package', label: 'Package assembly', index: '05' },

  { key: 'history', label: 'Application history', index: '06' },

  { key: 'profile', label: 'Profile / evidence', index: '07' },

  { key: 'search', label: 'Search records', index: '08' },

  { key: 'settings', label: 'Settings', index: '09' },

]



async function api<T>(path: string, options?: RequestInit): Promise<T> {

  const headers = new Headers(options?.headers)

  if (options?.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')

  const response = await fetch(apiUrl(path), { ...options, headers })

  const data = await response.json().catch(() => null)

  if (!response.ok) throw new Error(data?.error || data?.message || `Request failed (${response.status})`)

  if (data === null) throw new Error('The API returned an invalid JSON response.')

  return data

}



function useTransientConfirmation() {

  const [message, setMessage] = useState('')

  const timer = useRef<number | null>(null)

  useEffect(() => () => { if (timer.current !== null) window.clearTimeout(timer.current) }, [])

  const show = (next: string) => {

    if (timer.current !== null) window.clearTimeout(timer.current)

    setMessage(next)

    timer.current = window.setTimeout(() => { setMessage(''); timer.current = null }, 3200)

  }

  return { message, show }

}



function InlineConfirmation({ message }: { message: string }) {

  if (!message) return null

  return <div className="inline-confirmation" role="status" aria-live="polite">✓ {message}</div>

}



function App() {

  const [boot, setBoot] = useState<Boot | null>(null)

  const [route, setRoute] = useState<Route>((location.hash.replace('#/', '') as Route) || 'home')

  const [selected, setSelected] = useState<string | null>(null)

  const [applicationInfoMode, setApplicationInfoMode] = useState(false)

  const [notice, setNotice] = useState('')

  const [guide, setGuide] = useState(false)



  const refresh = () => api<Boot>('/api/bootstrap').then(setBoot).catch((e) => setNotice(e.message))

  useLayoutEffect(() => { refresh(); const onHash = () => setRoute((location.hash.replace('#/', '') as Route) || 'home'); addEventListener('hashchange', onHash); return () => removeEventListener('hashchange', onHash) }, [])

  useEffect(() => { if (route !== 'new') setApplicationInfoMode(false) }, [route])

  const go = (next: Route) => { setApplicationInfoMode(false); location.hash = `/${next}`; setRoute(next) }

  const openApplication = (id: string, next: Route = 'analysis') => { setSelected(id); go(next) }

  const openApplicationInfo = () => { setApplicationInfoMode(true); location.hash = '/new'; setRoute('new') }



  if (!boot) return <div className="boot-screen"><div className="boot-mark">CAREER<span>OS</span></div><div className="boot-line"><LoadingStatus label="LOADING LOCAL EVIDENCE GRAPH…" /></div></div>

  const selectedApp = boot.applications.find((a) => a.application_id === selected) || boot.applications[boot.applications.length - 1]



  return <div className="app-shell">

    <AmbientField />

    <aside className="rail">

      <button className="brand" onClick={() => go('home')}><span className="brand-glyph">+</span><span><b>CAREER OS</b><small>local intelligence</small></span></button>

      <div className="rail-rule" />

      <div className="rail-label">OPERATING SYSTEM</div>

      <nav>{nav.map((item) => <button key={item.key} className={route === item.key ? 'nav-item active' : 'nav-item'} onClick={() => go(item.key)}><span>{item.index}</span>{item.label}</button>)}</nav>

      <div className="rail-status"><i /> SYSTEM ONLINE<br /><small>approval gates active<br />manual submission boundary</small></div>

    </aside>

    <main className="main-stage">

      <header className="topbar"><span className="topbar-kicker">CAREER OPERATING SYSTEM / 2026</span><div className="topbar-tools"><button className="guide-trigger" onClick={() => setGuide(true)}>HOW TO USE</button><span className="topbar-state"><i /> LOCAL-FIRST · EVIDENCE LOCKED</span></div></header>

      {notice && <div className="notice" onClick={() => setNotice('')}>{notice}</div>}

      {guide && <Guide close={() => setGuide(false)} />}

      {route === 'home' && <Home boot={boot} go={go} openApplication={openApplication} />}

      {route === 'new' && (applicationInfoMode ? <ApplicationInfo app={selectedApp} go={go} /> : <NewApplication onCreated={(id) => { refresh(); openApplication(id, 'analysis') }} setNotice={setNotice} go={go} />)}

      {route === 'analysis' && <Analysis app={selectedApp} setNotice={setNotice} refresh={refresh} go={go} />}

      {route === 'resume' && <Resume app={selectedApp} go={go} setNotice={setNotice} refresh={refresh} />}

      {route === 'letter' && <Letter app={selectedApp} setNotice={setNotice} refresh={refresh} go={go} />}

      {route === 'package' && <Package app={selectedApp} go={(next) => next === 'new' ? openApplicationInfo() : go(next)} />}

      {route === 'history' && <History apps={boot.applications} openApplication={openApplication} go={go} />}

      {route === 'profile' && <Profile profile={boot.profile} />}

      {route === 'search' && <Search openApplication={openApplication} />}

      {route === 'settings' && <Settings />}

      <footer className="footer"><span>CAREER OS / LOCAL WORKSPACE</span><span>NO AUTOMATIC SUBMISSION · HUMAN APPROVAL REQUIRED</span></footer>

    </main>

  </div>

}



function AmbientField() { return <div className="ambient" aria-hidden="true"><div className="ambient-grid" /><span className="trace t1" /><span className="trace t2" /><span className="trace t3" /><div className="pulse pulse-a" /><div className="pulse pulse-b" /><div className="pulse pulse-c" /></div> }



function Home({ boot, go, openApplication }: { boot: Boot; go: (r: Route) => void; openApplication: (id: string, r?: Route) => void }) {

  const recent = [...boot.applications].reverse().slice(0, 4)

  const latest = recent[0]

  const count = boot.applications.length

  return <>

    <section className="hero-scene">

      <div className="hero-copy"><div className="eyebrow">00 / COMMAND CENTER</div><h1>INPUT<br /><em>SIGNAL</em><br />STORY<br /><strong>MOVE</strong></h1><p className="hero-lede">Your AI career operating system for turning opportunities into application-ready materials.</p><div className="hero-actions"><button className="button primary" onClick={() => go('new')}>Start with a role <span>↗</span></button><button className="button quiet" onClick={() => go('history')}>Open pipeline <span>→</span></button></div></div>

      <div className="hero-visual"><div className="visual-label">LIVE EVIDENCE FIELD <span>01—04</span></div><div className="orbitless-field"><div className="field-core"><span>REAL<br />SIGNAL</span></div><div className="field-ring r1" /><div className="field-ring r2" /><div className="field-ring r3" /><span className="field-node n1">JD<br /><b>INPUT</b></span><span className="field-node n2">PROFILE<br /><b>LOCKED</b></span><span className="field-node n3">OUTPUT<br /><b>READY</b></span></div><div className="visual-caption">A calm surface for complex work.<br /><b>Every claim traces back to evidence.</b></div></div>

    </section>

    <section className="ticker"><span>THE WORKFLOW</span><div><b>01</b> ANALYZE <i>→</i> <b>02</b> BUILD <i>→</i> <b>03</b> CREATE <i>→</i> <b>04</b> APPLY <i>→</i> <b>05</b> TRACK</div></section>

    <Reveal className="story-scene analyze"><div className="story-index">01 / ANALYZE</div><div className="story-content"><div><h2>FIND THE<br /><em>SIGNAL.</em></h2><p>Give Career OS the role. It extracts requirements, relevant skills, and evidence from the canonical profile without inventing a claim.</p></div><div className="analysis-thread"><div className="thread-label">JOB DESCRIPTION</div><div className="thread-line" /><div className="thread-node"><b>{latest?.job_title || 'REQUIREMENTS'}</b><small>{latest ? `${latest.supported_requirements?.length || 0} supported · ${latest.partial_requirements?.length || 0} partial` : 'waiting for first role'}</small></div><div className="thread-line" /><div className="thread-label accent">EVIDENCE MAP</div></div></div></Reveal>

    <Reveal className="story-scene build"><div className="story-index">02 / BUILD</div><div className="story-content"><div><h2>TURN EVIDENCE<br /><em>INTO YOUR STORY.</em></h2><p>The resume workspace turns selected projects, skills, and experience into a document with a visible approval lifecycle.</p></div><div className="document-stage" role="button" tabIndex={0} aria-label="Open Projects in Profile and Evidence" onClick={() => go('profile')} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); go('profile') } }}><div className="document-sheet"><span>PROJECTS</span><b>CANONICAL PROJECTS</b><small>{boot.profile.projects?.length || 0} projects available · evidence-backed</small></div><div className="document-shadow" /></div></div></Reveal>

    <Reveal className="story-scene create"><div className="story-index">03 / CREATE</div><div className="story-content"><div><h2>MAKE THE<br /><em>APPLICATION COMPLETE.</em></h2><p>Cover letters and supporting materials are composed from the same selected evidence, keeping the story consistent from first read to final review.</p></div><div className="letter-stack" role="button" tabIndex={0} aria-label="Open Application History" onClick={() => go('history')} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); go('history') } }}><div className="letter-page back" /><div className="letter-page"><span>APPLICATIONS</span><b>{latest?.company_name || 'APPLICATION PIPELINE'}</b><small>{recent.length ? `${recent.length} recent applications in history` : 'No applications yet'}</small></div></div></div></Reveal>

    <Reveal className="story-scene apply"><div className="story-index">04 / APPLY</div><div className="story-content"><div><h2>READY<br /><em>WHEN YOU ARE.</em></h2><p>Resume, cover letter, JD analysis, and application information converge into one reviewable package. Submission remains manual by design.</p></div><div className="assembly-line"><div>RESUME</div><i>+</i><div>LETTER</div><i>+</i><div>ANALYSIS</div><span>→ APPLICATION READY</span></div></div></Reveal>

    <Reveal className="story-scene track"><div className="story-index">05 / TRACK</div><div className="story-content"><div><h2>KEEP THE<br /><em>TRACE.</em></h2><p>Every real application keeps its place in the timeline. Statuses and milestones come from the local application store, not a decorative demo.</p></div><div className="track-line">{recent.length ? recent.map((a, i) => <button key={a.application_id} onClick={() => openApplication(a.application_id, 'analysis')}><span>{String(i + 1).padStart(2, '0')}</span><b>{a.company_name || 'Unknown company'}</b><small>{a.current_status || 'unknown'}</small></button>) : <div className="track-empty">DISCOVERED → ANALYZED → RESUME → PACKAGE → SUBMITTED</div>}</div></div></Reveal>

    <section className="manifesto"><div className="eyebrow">THE PROMISE</div><p>Less noise.<br /><span>More signal.</span></p><button className="button primary" onClick={() => go('new')}>Enter the workspace <span>↗</span></button></section>

  </>

}

function Stat({ label, value }: { label: string; value: string }) { return <div className="stat"><span>{label}</span><b>{value}</b></div> }



function Reveal({ className, children }: { className: string; children: ReactNode }) { const ref = useRef<HTMLElement | null>(null); const [visible, setVisible] = useState(false); useEffect(() => { const node = ref.current; if (!node) return; const observer = new IntersectionObserver(([entry]) => { if (entry.isIntersecting) { setVisible(true); observer.disconnect() } }, { threshold: 0.16 }); observer.observe(node); return () => observer.disconnect() }, []); return <section ref={ref} className={`${className} reveal${visible ? ' visible' : ''}`}>{children}</section> }



function NewApplication({ app, onCreated, setNotice, go }: { app?: AppRecord; onCreated: (id: string) => void; setNotice: (s: string) => void; go: (r: Route) => void }) {

  const [form, setForm] = useState({ company: '', title: '', url: '', source: '', location: '', employment_type: '', job_description: '' }); const [busy, setBusy] = useState(false)

  const update = (key: string, value: string) => setForm({ ...form, [key]: value })

  const submit = async () => { setBusy(true); try { const result: any = await api('/api/applications', { method: 'POST', body: JSON.stringify(form) }); if (result.application?.application_id) onCreated(result.application.application_id); else setNotice(result.message || 'Application created') } catch (e: any) { setNotice(e.message) } finally { setBusy(false) } }

  return <Workspace title="START WITH THE ROLE" eyebrow="01 / INTAKE" intro="Give the system the raw material. It will extract the signal without inventing the evidence." workflow="new" go={go}><div className="form-layout"><div><label>JOB DESCRIPTION<textarea value={form.job_description} onChange={(e) => update('job_description', e.target.value)} placeholder="Paste the complete job description here…" /></label></div><div className="form-stack"><label>COMPANY<input value={form.company} onChange={(e) => update('company', e.target.value)} placeholder="Company name" /></label><label>ROLE<input value={form.title} onChange={(e) => update('title', e.target.value)} placeholder="Job title" /></label><label>JOB URL<input value={form.url} onChange={(e) => update('url', e.target.value)} placeholder="https://…" /></label><div className="form-row"><label>LOCATION<input value={form.location} onChange={(e) => update('location', e.target.value)} placeholder="Remote / city" /></label><label>SOURCE<input value={form.source} onChange={(e) => update('source', e.target.value)} placeholder="LinkedIn / referral" /></label></div><button className="button primary wide" onClick={submit} disabled={busy}>{busy ? <LoadingStatus label="ANALYZING…" /> : 'CREATE + ANALYZE ROLE ↗'}</button></div></div></Workspace>

}



function Analysis({ app, setNotice, refresh, go }: { app?: AppRecord; setNotice: (s: string) => void; refresh: () => void; go: (r: Route) => void }) {

  const [plan, setPlan] = useState<AppRecord | null>(null)

  const [busy, setBusy] = useState(false)

  const [skillCategories, setSkillCategories] = useState<Record<string, string>>({})

  const confirmation = useTransientConfirmation()

  const load = async () => {

    if (!app?.phase8_plan_reference) return

    setBusy(true)

    try {

      const result: any = await api('/api/analyze', { method: 'POST', body: JSON.stringify({ job_description: app.job_description_text }) })

      setPlan(result)

      confirmation.show('ANALYSIS COMPLETE')

    } catch (e: any) { setNotice(e.message) } finally { setBusy(false) }

  }

  const approve = async () => {

    if (!app || !plan) return

    try {

      const result: any = await api(`/api/applications/${app.application_id}/approve-resume`, { method: 'POST', body: JSON.stringify({ plan }) })

      if (result.decision !== 'approved') throw new Error(result.message || 'The reviewed plan could not be approved.')

      setPlan(null)

      setNotice('Reviewed Resume Plan approved and saved for this application.')

      refresh()

    }

    catch (e: any) { setNotice(e.message) }

  }

  const confirmSkill = async (skill: string) => {

    if (!app) return

    const category = skillCategories[skill]

    if (!category) return

    setBusy(true)

    try {

      const result: any = await api(`/api/applications/${app.application_id}/confirm-skill-gap`, { method: 'POST', body: JSON.stringify({ skill, category, confirmed: true }) })

      setNotice(result.message || 'Skill recorded as candidate-provided. Verify it before using it in a resume.')

      setPlan(null)

      refresh()

    } catch (e: any) { setNotice(e.message) } finally { setBusy(false) }

  }

  const requiredGaps = (plan?.candidate_matching || []).filter((item: any) => item.classification === 'required' && ['UNSUPPORTED', 'UNKNOWN'].includes(item.evidence_status) && !(item.evidence || []).some((evidence: any) => evidence.type === 'skill' && ['verified', 'candidate_provided'].includes(evidence.status)))

  return <Workspace title="SEE THE SIGNAL" eyebrow="02 / JD INTELLIGENCE" intro="Requirements, evidence, gaps, and a defensible resume plan in one readable surface." workflow="analysis" go={go}>

    <div className="analysis-top"><div className="analysis-card"><span className="card-label">SELECTED APPLICATION</span><h3>{app?.company_name || 'No application selected'}</h3><p>{app?.job_title || 'Create an application first.'}</p><span className="pill">{app?.current_status || 'WAITING'}</span></div><button className="button outline" onClick={load} disabled={!app || busy}>{busy ? <LoadingStatus label="ANALYZING…" /> : 'RUN EVIDENCE MAP ↗'}</button></div>

    <InlineConfirmation message={confirmation.message} />

    {app && plan && <div className="analysis-grid">

      <div className="analysis-card large"><span className="card-label">ROLE IDENTITY</span><h3>{plan.jd_analysis?.target_role || app.job_title || 'Role'}</h3><div className="chip-list">{(plan.jd_analysis?.required_technical_skills || app.supported_requirements || []).map((item: any) => <span className="chip positive" key={item}>{item}</span>)}</div></div>

      <div className="analysis-card large"><span className="card-label">ALIGNMENT READOUT</span><div className="alignment-meter"><span style={{ width: `${Math.min(92, 35 + (plan.evidence_summary?.supported_requirements?.length || 0) * 12)}%` }} /></div><p>{`${plan.evidence_summary?.supported_requirements?.length || 0} supported · ${plan.evidence_summary?.partial_requirements?.length || 0} partial · ${plan.evidence_summary?.unsupported_requirements?.length || 0} gaps`}</p></div>

      <div className="analysis-card full"><span className="card-label">PROJECT STRATEGY</span><div className="project-row">{(plan.resume_plan?.projects_to_include || []).map((item: any) => <span className="project-chip" key={item.record_id}>{item.name}</span>)}</div></div>

      {requiredGaps.map((gap: any) => <div className="analysis-card full" key={gap.requirement}>

        <span className="card-label">REQUIRED SKILL GAP</span>

        <p>This JD strongly requires <b>{gap.requirement}</b>, but it is not currently in your profile. Do you want to add it?</p>

        <label className="field-label">PROFILE CATEGORY<select value={skillCategories[gap.requirement] || ''} onChange={(event) => setSkillCategories({ ...skillCategories, [gap.requirement]: event.target.value })}><option value="">Choose a category</option>{(plan.candidate_skill_categories || []).map((category: string) => <option key={category} value={category}>{category.split('_').join(' ')}</option>)}</select></label>

        <button className="button outline" onClick={() => confirmSkill(gap.requirement)} disabled={busy || !skillCategories[gap.requirement]}>CONFIRM ADD AS CANDIDATE-PROVIDED</button>

      </div>)}

    </div>}

    {app && <div className="action-bar"><span>Approval gate: resume generation stays locked until you review this plan.</span>{plan && <button className="button primary" onClick={approve}>APPROVE REVIEWED PLAN ↗</button>}</div>}

  </Workspace>

}



function Resume({ app, go, setNotice, refresh }: { app?: AppRecord; go: (r: Route) => void; setNotice: (s: string) => void; refresh: () => void }) {

  const [busy, setBusy] = useState(false)

  const [busyLabel, setBusyLabel] = useState('')

  const confirmation = useTransientConfirmation()

  const [editor, setEditor] = useState<any | null>(null)

  const [textEditorOpen, setTextEditorOpen] = useState(false)

  const approved = !!app?.resume_generation_allowed

  const working = !!app?.working_resume_generation_id

  const finalized = !!app?.resume_generation_id

  const workingTime = Date.parse(app?.working_resume_generated_at || '')

  const finalizedTime = Date.parse(app?.resume_finalized_at || '')

  const workingNewerThanFinal = !!(working && finalized && !app?.resume_working_artifact_stale && Number.isFinite(workingTime) && Number.isFinite(finalizedTime) && workingTime > finalizedTime)

  const finalStale = !!(finalized && (app?.resume_final_stale || workingNewerThanFinal))

  const canFinalize = !!(working && !app?.resume_working_artifact_stale && (!finalized || finalStale))

  const action = async (endpoint: string, success: string) => { if (!app) return; setBusyLabel(endpoint === 'finalize-resume' ? 'FINALIZING…' : 'BUILDING RESUME…'); setBusy(true); try { const result: any = await api(`/api/applications/${app.application_id}/${endpoint}`, { method: 'POST', body: JSON.stringify({}) }); if (result.decision && !['created', 'finalized'].includes(result.decision)) throw new Error(result.message || 'Resume action could not be completed.'); if (endpoint === 'generate-resume') confirmation.show('RESUME READY'); else setNotice(success); refresh() } catch (e: any) { setNotice(e.message) } finally { setBusy(false); setBusyLabel('') } }

  const openEditor = async () => { if (!app) return; setBusyLabel('LOADING PROJECTS…'); setBusy(true); try { setEditor(await api(`/api/applications/${app.application_id}/resume-editor`)) } catch (e: any) { setNotice(e.message) } finally { setBusy(false); setBusyLabel('') } }

  const openTextEditor = () => { if (!app) return; setEditor(null); setTextEditorOpen(true) }

  const saveEditor = async () => { if (!app || !editor) return; setBusyLabel('SAVING WORKING RESUME…'); setBusy(true); try { const result: any = await api(`/api/applications/${app.application_id}/resume-edit`, { method: 'POST', body: JSON.stringify({ mode: editor.mode, record_ids: editor.selected_record_ids }) }); setEditor(null); setNotice(result.message || 'Supported project selection saved.'); refresh() } catch (e: any) { setNotice(e.message) } finally { setBusy(false); setBusyLabel('') } }

  const toggleProject = (id: string) => setEditor({ ...editor, selected_record_ids: editor.selected_record_ids.includes(id) ? editor.selected_record_ids.filter((x: string) => x !== id) : [...editor.selected_record_ids, id] })

  if (textEditorOpen && app) return <Workspace title="EDIT THE WORKING RESUME" eyebrow="03 / RESUME WORKSPACE" intro="Edit only source-backed resume text. Save validates and activates a new Working DOCX/PDF revision; Cancel discards the session." workflow="resume" go={go}><Suspense fallback={<div className="resume-editor-loading"><LoadingStatus label="LOADING EDITOR MODULE…" /></div>}><ResumeDocumentEditor applicationId={app.application_id} companyName={app.company_name || 'Selected application'} onCancel={() => setTextEditorOpen(false)} onSaved={() => { setTextEditorOpen(false); confirmation.show('WORKING VERSION SAVED'); refresh() }} /></Suspense></Workspace>

  return <Workspace title="BUILD THE PROOF" eyebrow="03 / RESUME WORKSPACE" intro="A working document, a final document, and a clear lifecycle between them." workflow="resume" go={go}>

    <div className="resume-context"><div><span className="card-label">SELECTED APPLICATION</span><h3>{app?.company_name || 'No application selected'}</h3><p>{app?.job_title || 'Create an application first.'}</p></div><span className="pill">{finalStale ? 'WORKING UPDATED · FINAL SUPERSEDED' : finalized ? 'FINALIZED' : working ? 'RESUME READY' : approved ? 'PLAN APPROVED' : 'PLAN REVIEW REQUIRED'}</span></div><InlineConfirmation message={confirmation.message} />

    {!app && <div className="notice-panel">Create an application before opening the Resume Workspace.</div>}

    {app && !approved && <div className="resume-gate"><div><b>Approve the Resume Plan before generating.</b><span>Review the evidence map and project strategy in JD Intelligence first.</span></div><button className="button outline" onClick={() => go('analysis')}>← JD INTELLIGENCE</button></div>}

    {app && approved && !working && <div className="resume-next"><div><b>Resume plan approved</b><span>Ready to generate your tailored resume using the canonical profile and approved evidence.</span></div><div className="resume-actions"><button className="button primary" onClick={() => action('generate-resume', 'Working resume generated and validated.')} disabled={busy}>{busy && busyLabel === 'BUILDING RESUME…' ? <LoadingStatus label={busyLabel} /> : 'GENERATE RESUME ↗'}</button><button className="button quiet" onClick={openEditor} disabled={busy}>{busy && busyLabel === 'LOADING PROJECTS…' ? <LoadingStatus label={busyLabel} /> : 'EDIT PROJECTS'}</button></div></div>}

    {app && approved && working && <div className="resume-next"><div><b>{finalStale ? 'Working Resume is newer than the superseded Final' : finalized ? 'Working Resume and Final Resume available' : 'Working Resume ready'}</b><span>Last generated: {app.working_resume_generated_at || 'date not recorded'}</span></div><div className="resume-actions"><button className="button quiet" onClick={openEditor} disabled={busy}>{busy && busyLabel === 'LOADING PROJECTS…' ? <LoadingStatus label={busyLabel} /> : 'EDIT PROJECTS'}</button><button className="button quiet" onClick={() => action('generate-resume', 'Working resume regenerated and validated.')} disabled={busy}>{busy && busyLabel === 'BUILDING RESUME…' ? <LoadingStatus label={busyLabel} /> : 'REGENERATE'}</button>{canFinalize && <button className="button primary" onClick={() => action('finalize-resume', 'Current Working Resume finalized; prior Final artifact retained.')} disabled={busy}>{busy && busyLabel === 'FINALIZING…' ? <LoadingStatus label={busyLabel} /> : finalized ? 'FINALIZE UPDATED WORKING ↗' : 'FINALIZE RESUME ↗'}</button>}</div></div>}

    {editor && <div className="resume-editor"><div className="editor-heading"><div><span className="card-label">SUPPORTED REVIEW / EDIT</span><h3>Project Selection</h3><p>Only canonical completed projects can be changed here. Final artifacts remain protected.</p></div><span className="pill">MAX {editor.max_projects}</span></div><div className="editor-modes"><button className={editor.mode === 'automatic' ? 'button primary' : 'button quiet'} onClick={() => setEditor({ ...editor, mode: 'automatic', selected_record_ids: editor.automatic_record_ids })}>AUTOMATIC RECOMMENDATION</button><button className={editor.mode === 'manual' ? 'button primary' : 'button quiet'} onClick={() => setEditor({ ...editor, mode: 'manual' })}>CHOOSE PROJECTS MANUALLY</button></div>{editor.mode === 'automatic' ? <div className="editor-readout">{editor.projects.filter((p: any) => editor.selected_record_ids.includes(p.record_id)).map((p: any) => <span key={p.record_id}>{p.name}</span>)}<small>Automatic recommendation will be restored. Saving invalidates the current Working Resume until the updated plan is approved and regenerated.</small></div> : <div className="editor-projects">{editor.projects.map((p: any) => <label key={p.record_id}><input type="checkbox" checked={editor.selected_record_ids.includes(p.record_id)} onChange={() => toggleProject(p.record_id)} /><span><b>{p.name}</b><small>{p.technologies.join(' · ') || 'Canonical completed project'}</small></span></label>)}</div>}<div className="editor-footer"><span>Unsupported fields cannot be invented or edited in this workflow.</span><div><button className="button quiet" onClick={() => setEditor(null)} disabled={busy}>CANCEL</button><button className="button primary" onClick={saveEditor} disabled={busy || editor.mode === 'manual' && !editor.selected_record_ids.length}>{busy && busyLabel === 'SAVING WORKING RESUME…' ? <LoadingStatus label={busyLabel} /> : 'SAVE WORKING VERSION ↗'}</button></div></div></div>}

    <div className="artifact-grid"><Artifact label="WORKING VERSION" title="Editable candidate" state={working ? 'READY' : 'WAITING'} reference={app?.working_resume_docx_path} pdfReference={app?.working_resume_pdf_path} docxAvailable={app?.working_resume_docx_available} pdfAvailable={app?.working_resume_pdf_available} generatedAt={app?.working_resume_generated_at} viewLabel="VIEW RESUME" /><Artifact label="FINAL VERSION" title={finalStale ? 'Superseded Final · retained in history' : 'Active finalized resume'} state={finalStale ? 'SUPERSEDED' : finalized ? 'FINAL' : 'NOT CREATED'} reference={app?.resume_reference} pdfReference={app?.resume_pdf_reference} docxAvailable={app?.final_resume_docx_available} pdfAvailable={app?.final_resume_pdf_available} generatedAt={app?.resume_finalized_at} viewLabel="VIEW FINAL RESUME" /></div>

    <div className="process-strip"><span className={approved ? 'live' : ''}>PLAN APPROVED</span><i>→</i><span className={working ? 'live' : ''}>WORKING GENERATED</span><i>→</i><span className={working ? 'live' : ''}>REVIEW / EDIT</span><i>→</i><span className={finalized ? 'live' : ''}>FINALIZED</span></div>

  </Workspace>

}

function Artifact({ label, title, state, reference, pdfReference, docxAvailable, pdfAvailable, generatedAt, viewLabel }: { label: string; title: string; state: string; reference?: string; pdfReference?: string; docxAvailable?: boolean; pdfAvailable?: boolean; generatedAt?: string; viewLabel: string }) { return <div className="artifact"><span className="card-label">{label}</span><h3>{title}</h3><span className={state === 'FINAL' || state === 'READY' ? 'pill live' : 'pill'}>{state}</span>{generatedAt && <small className="artifact-date">{generatedAt}</small>}<div className="artifact-sheet"><span>DOCUMENT SURFACE</span><span>evidence-aligned structure</span><span>one-page validation</span></div>{(docxAvailable || pdfAvailable) && <div className="artifact-links">{pdfAvailable && pdfReference && <a className="artifact-view" href={apiUrl(`/api/artifact?ref=${encodeURIComponent(pdfReference)}&view=inline`)} target="_blank" rel="noreferrer">{viewLabel}</a>}{docxAvailable && reference && <a href={apiUrl(`/api/artifact?ref=${encodeURIComponent(reference)}`)} download>DOWNLOAD DOCX</a>}{pdfAvailable && pdfReference && <a href={apiUrl(`/api/artifact?ref=${encodeURIComponent(pdfReference)}`)} download>DOWNLOAD PDF</a>}</div>}</div> }

function Letter({ app, setNotice, refresh, go }: { app?: AppRecord; setNotice: (s: string) => void; refresh: () => void; go: (r: Route) => void }) {

  const [content, setContent] = useState('')

  const [draft, setDraft] = useState('')

  const [editing, setEditing] = useState(false)

  const [busy, setBusy] = useState(false)

  const [busyLabel, setBusyLabel] = useState('')

  const [workingPdfRef, setWorkingPdfRef] = useState(app?.cover_letter_working_pdf_reference || '')

  const confirmation = useTransientConfirmation()



  const loadMd = async (reference: string) => {

    const response = await fetch(apiUrl(`/api/artifact?ref=${encodeURIComponent(reference)}`))

    if (!response.ok) throw new Error('Generated cover letter could not be loaded.')

    return response.text()

  }



  // Load text preview from the working Markdown source (cover_letter_working_reference preferred, fall back to cover_letter_reference)

  const mdRef = app?.cover_letter_working_reference || app?.cover_letter_reference

  useEffect(() => { setWorkingPdfRef(app?.cover_letter_working_pdf_reference || '') }, [app?.application_id, app?.cover_letter_working_pdf_reference])

  useEffect(() => {

    let active = true

    if (!mdRef) { if (active) { setContent(''); setDraft(''); setEditing(false) }; return () => { active = false } }

    loadMd(mdRef).then((text) => { if (active) { setContent(text); setDraft(text) } }).catch((e: any) => { if (active) setNotice(e.message) })

    return () => { active = false }

  }, [app?.application_id, mdRef])



  const create = async () => {

    if (!app) return

    setBusyLabel('GENERATING LETTER…'); setBusy(true)

    try {

      const result: any = await api(`/api/applications/${app.application_id}/cover-letter`, { method: 'POST' })

      const next = result.content || (mdRef ? await loadMd(mdRef) : content)

      if (next) { setContent(next); setDraft(next) }

      if (result.cover_letter_working_pdf_reference) setWorkingPdfRef(result.cover_letter_working_pdf_reference)

      setEditing(false); confirmation.show('COVER LETTER READY'); refresh()

    } catch (e: any) { setNotice(e.message) } finally { setBusy(false); setBusyLabel('') }

  }



  const save = async () => {

    if (!app) return

    setBusyLabel('SAVING LETTER…'); setBusy(true)

    try {

      const result: any = await api(`/api/applications/${app.application_id}/cover-letter-edit`, { method: 'POST', body: JSON.stringify({ content: draft }) })

      setContent(result.content || draft); setDraft(result.content || draft)

      if (result.cover_letter_working_pdf_reference) setWorkingPdfRef(result.cover_letter_working_pdf_reference)

      setEditing(false); setNotice('Working cover letter saved.'); refresh()

    } catch (e: any) { setNotice(e.message) } finally { setBusy(false); setBusyLabel('') }

  }



  // Resolve the best download references

  const finalPdfRef = app?.cover_letter_pdf_reference



  return (

    <Workspace title="WRITE WITH INTENT" eyebrow="04 / COVER LETTER" intro="An editorial writing surface grounded in the role, the profile, and the projects already selected." workflow="letter" go={go}>

      <div className="writing-surface">

        <div className="writing-meta">

          <span>{app?.company_name || 'SELECT AN APPLICATION'}</span>

          <span>{app?.job_title || 'ROLE NOT SPECIFIED'}</span>

        </div>



        {content

          ? editing

            ? <textarea value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Working cover letter" rows={18} />

            : <p style={{ whiteSpace: 'pre-wrap' }}>{content}</p>

          : <p>Generate a working letter from the approved application evidence.</p>}



        <div className="letter-actions">

          {content && !editing && (

            <>

              <button className="button outline" onClick={() => { setDraft(content); setEditing(true) }} disabled={busy}>EDIT</button>

              {workingPdfRef && (

                <a className="button quiet" href={apiUrl(`/api/artifact?ref=${encodeURIComponent(workingPdfRef)}&view=inline`)} target="_blank" rel="noreferrer">

                  VIEW PDF

                </a>

              )}

              {workingPdfRef && (

                <a className="button quiet" href={apiUrl(`/api/artifact?ref=${encodeURIComponent(workingPdfRef)}`)} download>

                  DOWNLOAD WORKING PDF

                </a>

              )}

              {finalPdfRef && (

                <a className="button quiet" href={apiUrl(`/api/artifact?ref=${encodeURIComponent(finalPdfRef)}`)} download>

                  DOWNLOAD FINAL PDF

                </a>

              )}

            </>

          )}

          {editing && (

            <>

              <button className="button quiet" onClick={() => setEditing(false)} disabled={busy}>CANCEL</button>

              <button className="button primary" onClick={save} disabled={busy || !draft.trim()}>

                {busy && busyLabel === 'SAVING LETTER…' ? <LoadingStatus label={busyLabel} /> : 'SAVE WORKING LETTER ↗'}

              </button>

            </>

          )}

          <button className="button primary" onClick={create} disabled={!app || busy}>

            {busy && busyLabel === 'GENERATING LETTER…' ? <LoadingStatus label={busyLabel} /> : content ? 'REGENERATE WORKING LETTER ↗' : 'GENERATE WORKING LETTER ↗'}

          </button>

        </div>



        <InlineConfirmation message={confirmation.message} />

        {content && <small className="artifact-date">WORKING / GENERATED ARTIFACT</small>}

      </div>

    </Workspace>

  )

}

function Package({ app, go }: { app?: AppRecord; go: (r: Route) => void }) { const cards: [string, Route][] = [['RESUME', 'resume'], ['COVER LETTER', 'letter'], ['JD ANALYSIS', 'analysis'], ['APPLICATION INFO', 'new']]; const checks: [string, boolean, Route][] = [['JD analyzed', !!app?.phase8_plan_reference, 'analysis'], ['Resume plan approved', !!app?.resume_generation_allowed, 'resume'], ['Working resume', !!app?.working_resume_docx_path, 'resume'], ['Final resume', !!app?.resume_reference, 'resume'], ['Cover letter', !!app?.cover_letter_reference, 'letter']]; return <Workspace title="ASSEMBLE THE MOMENT" eyebrow="05 / PACKAGE ASSEMBLY" intro="Documents and application information converge into a package you can submit manually with confidence." workflow="package" go={go}><div className="assembly"><div className="assembly-stack">{cards.map(([label, route], i) => <button key={label} className="assembly-card" style={{ '--i': i } as CSSProperties} onClick={() => go(route)} aria-label={`Open ${label}`}>{label}<span>+</span></button>)}</div><div className="assembly-result">APPLICATION<br /><em>PACKAGE</em><small>MANUAL SUBMISSION ONLY</small></div></div><div className="check-list">{checks.map(([label, ok, route]) => <button className="check-row" key={label} onClick={() => go(route)}><i className={ok ? 'check on' : 'check'} />{label}<span>{ok ? 'READY' : 'PENDING'}</span></button>)}</div></Workspace> }

function History({ apps, openApplication, go }: { apps: AppRecord[]; openApplication: (id: string, r?: Route) => void; go: (r: Route) => void }) { return <Workspace title="FOLLOW THE TRACE" eyebrow="06 / HISTORY" intro="A spatial record of every application state, decision, and artifact milestone." workflow="history" go={go}><div className="timeline">{[...apps].reverse().map((a, i) => <button className="timeline-row" key={a.application_id} onClick={() => openApplication(a.application_id, 'analysis')}><span className="timeline-dot" /><span className="timeline-date">{a.date_added || '—'}</span><span><b>{a.company_name || 'Unknown company'}</b><small>{a.job_title || 'Untitled role'}</small></span><span className="stream-status">{a.current_status}</span><span>↗</span></button>)}</div></Workspace> }

function Profile({ profile }: { profile: AppRecord }) { return <Workspace title="KNOW YOUR EVIDENCE" eyebrow="07 / PROFILE" intro="The canonical profile stays authoritative. This surface makes its clusters, projects, and proof readable."><div className="profile-grid"><div className="profile-intro"><div className="eyebrow">CANDIDATE</div><h3>{profile.name || 'Profile'}</h3><p>{profile.headline || 'Evidence-backed career profile'}</p><span>{profile.location || 'Local profile store'}</span></div><div className="profile-block"><span className="card-label">SKILL CLUSTERS</span><div className="tag-cloud">{(profile.skills || []).slice(0, 18).map((s: any) => <span key={s.name}>{s.name}</span>)}</div></div><div className="profile-block"><span className="card-label">PROJECTS</span>{(profile.projects || []).map((p: any) => <div className="proof-row" key={p.record_id}><b>{p.name}</b><small>{p.project_status || 'unknown'} · {p.github_availability || 'source recorded'}</small></div>)}</div></div></Workspace> }

function Search({ openApplication }: { openApplication: (id: string, r?: Route) => void }) { const [q, setQ] = useState(''); const [results, setResults] = useState<AppRecord[]>([]); useEffect(() => { if (q.length < 2) { setResults([]); return } const timer = setTimeout(() => api<{ applications: AppRecord[] }>(`/api/search?q=${encodeURIComponent(q)}`).then((x) => setResults(x.applications)), 250); return () => clearTimeout(timer) }, [q]); return <Workspace title="FIND THE SIGNAL" eyebrow="08 / SEARCH" intro="Search the local application store without losing the spatial context of the work."><input className="search-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search company, role, note…" /><div className="search-results">{results.map((a) => <button className="stream-row" key={a.application_id} onClick={() => openApplication(a.application_id)}><span className="stream-main"><b>{a.company_name}</b><small>{a.job_title}</small></span><span className="stream-status">{a.current_status}</span>↗</button>)}</div></Workspace> }

function Settings() { return <Workspace title="KEEP THE BOUNDARY" eyebrow="09 / SETTINGS" intro="Career OS is local-first, approval-gated, and intentionally manual at the point of submission."><div className="settings-grid"><div><span className="card-label">SAFETY</span><h3>Manual submission only.</h3><p>No browser automation, portal login, CAPTCHA handling, email submission, or fabricated evidence.</p></div><div><span className="card-label">MOTION</span><h3>Purposeful by default.</h3><p>Use the browser’s reduced-motion preference to calm transitions and preserve readability.</p></div></div></Workspace> }

const workflowSteps: { key: Route; label: string }[] = [{ key: 'new', label: 'NEW APPLICATION' }, { key: 'analysis', label: 'JD INTELLIGENCE' }, { key: 'resume', label: 'RESUME WORKSPACE' }, { key: 'letter', label: 'COVER LETTER' }, { key: 'package', label: 'PACKAGE ASSEMBLY' }, { key: 'history', label: 'APPLICATION HISTORY' }]



function WorkflowNav({ current, go }: { current: Route; go: (r: Route) => void }) { const index = workflowSteps.findIndex((step) => step.key === current); const previous = workflowSteps[index - 1]; const next = workflowSteps[index + 1]; return <div className="workflow-nav">{previous ? <button className="button quiet" onClick={() => go(previous.key)}>← {previous.label}</button> : <span />}{next ? <button className="button outline" onClick={() => go(next.key)}>{next.label} →</button> : <span />}</div> }



function Guide({ close }: { close: () => void }) { return <div className="guide-backdrop" role="dialog" aria-modal="true" aria-label="How to use Career OS"><div className="guide-panel"><div className="guide-heading"><div><span className="card-label">CAREER OS / QUICK GUIDE</span><h2>HOW TO USE</h2></div><button className="guide-close" onClick={close} aria-label="Close guide">×</button></div><div className="guide-steps"><p><b>01 — NEW APPLICATION</b><span>Create an application and provide the job description.</span></p><p><b>02 — JD INTELLIGENCE</b><span>Run the evidence map and review/approve the resume plan.</span></p><p><b>03 — RESUME WORKSPACE</b><span>Generate the Working Resume, view it, review/edit supported information, and finalize it.</span></p><p><b>04 — COVER LETTER</b><span>Create and finalize the cover letter.</span></p><p><b>05 — PACKAGE ASSEMBLY</b><span>Check that all finalized application materials are ready.</span></p><p><b>06 — APPLICATION HISTORY</b><span>Track applications and status.</span></p></div><div className="guide-definitions"><span><b>WORKING</b> editable draft</span><span><b>FINAL</b> finalized artifact</span><span><b>VIEW</b> opens the actual generated document</span><span><b>DOWNLOAD</b> retrieves the actual DOCX/PDF</span><span><b>MANUAL SUBMISSION</b> user submits the application manually</span></div></div></div> }



function Workspace({ title, eyebrow, intro, children, workflow, go }: { title: string; eyebrow: string; intro: string; children: ReactNode; workflow?: Route; go?: (r: Route) => void }) { return <section className="workspace"><div className="workspace-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{intro}</p></div><span className="workspace-mark">⌁</span></div>{children}{workflow && go && <WorkflowNav current={workflow} go={go} />}</section> }



createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)