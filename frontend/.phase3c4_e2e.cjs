const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require(path.join(os.tmpdir(), 'career-os-playwright-3c3', 'node_modules', 'playwright-core'));

const root = 'C:\\project\\job-application-agent';
const appId = 'app_14a66f897623';
const normalize = (value) => String(value || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
const sha256 = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const rootPath = (reference) => path.resolve(root, String(reference).replace(/[\\/]/g, path.sep));
const finalKeys = ['resume_reference','resume_pdf_reference','resume_docx_path','resume_pdf_path','resume_docx_sha256','resume_pdf_sha256','resume_generation_id','resume_finalized_at','resume_status'];

function walkFiles(directory) {
  if (!fs.existsSync(directory)) return [];
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    return entry.isDirectory() ? walkFiles(target) : [target];
  });
}
function swapCase(value) {
  return String(value).replace(/[a-zA-Z]/g, (character) => character === character.toUpperCase() ? character.toLowerCase() : character.toUpperCase());
}
async function replaceEditableBlock(page, locator, replacement) {
  await locator.scrollIntoViewIfNeeded();
  await locator.click({ position: { x: 8, y: 8 } });
  await locator.evaluate((element) => {
    const content = element.querySelector('.resume-editor-editable-content');
    if (!content) throw new Error('Editable Tiptap content container was not found');
    const range = document.createRange();
    range.selectNodeContents(content);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  });
  await page.keyboard.type(replacement);
  await page.waitForTimeout(120);
  assert.equal(normalize(await locator.innerText()), normalize(replacement), 'Text edit did not update the targeted Tiptap block');
}
async function snapshot(page) {
  return page.evaluate(async () => {
    const response = await fetch('/api/bootstrap');
    if (!response.ok) throw new Error(`bootstrap returned ${response.status}`);
    return response.json();
  });
}

(async () => {
  const liveStorePath = path.join(root, 'data', 'applications.json');
  const liveStoreBytes = fs.readFileSync(liveStorePath);
  const liveStore = JSON.parse(liveStoreBytes.toString('utf8'));
  const liveApp = liveStore.applications.find((item) => item.application_id === appId);
  assert(liveApp, `Live Rex.zone application not found: ${appId}`);
  assert.equal(liveApp.company_name, 'Rex.zone');
  const liveApplicationIds = liveStore.applications.map((item) => item.application_id).sort();
  const protectedReferences = [
    'resume_generator.py', 'templates/ats_resume_template.docx',
    'data/master_profile.json', 'data/skills.json', 'data/projects.json', 'data/experience.json',
    'data/education.json', 'data/certifications.json', 'data/achievements.json',
    liveApp.phase8_plan_reference, liveApp.working_resume_revision_reference, liveApp.working_resume_validation_reference,
    liveApp.working_resume_docx_path, liveApp.working_resume_pdf_path,
    liveApp.resume_docx_path, liveApp.resume_pdf_path,
  ].filter(Boolean);
  const liveProtectedHashes = new Map(protectedReferences.map((reference) => [rootPath(reference), sha256(rootPath(reference))]));
  const finalMetadataBefore = Object.fromEntries(finalKeys.map((key) => [key, liveApp[key] ?? null]));

  const isolatedRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'career-os-phase3c4-isolated-'));
  const serverScript = path.join(os.tmpdir(), `career-os-phase3c4-api-${process.pid}.py`);
  const pythonCode = String.raw`import json, shutil, sys
from pathlib import Path
from http.server import ThreadingHTTPServer
source = Path(sys.argv[1]); target = Path(sys.argv[2]); target.mkdir(parents=True, exist_ok=True)
shutil.copytree(source / 'data', target / 'data', dirs_exist_ok=True)
store = json.loads((target / 'data' / 'applications.json').read_text(encoding='utf-8'))
keys = ('phase8_plan_reference','working_resume_docx_path','working_resume_pdf_path','working_resume_reference','working_resume_pdf_reference','working_resume_revision_reference','working_resume_validation_reference','resume_reference','resume_pdf_reference','resume_docx_path','resume_pdf_path','cover_letter_reference')
for app in store.get('applications', []):
    for key in keys:
        reference = app.get(key)
        if not isinstance(reference, str) or not reference.strip(): continue
        src = (source / reference).resolve()
        try: src.relative_to(source.resolve())
        except ValueError: continue
        if not src.is_file(): continue
        dst = target / reference
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
sys.path.insert(0, str(source))
import application_assistant as aa
import career_os_api as api
aa.DATA = target / 'data'
api.ROOT = target
server = ThreadingHTTPServer(('127.0.0.1', 0), api.Handler)
print(json.dumps({'ready': True, 'port': server.server_address[1], 'application_count': len(store.get('applications', []))}), flush=True)
server.serve_forever()`;
  fs.writeFileSync(serverScript, pythonCode, 'utf8');
  const apiServer = spawn('python', ['-X', 'utf8', '-B', serverScript, root, isolatedRoot], { cwd: root, windowsHide: true });
  let serverStdout = '';
  let serverStderr = '';
  apiServer.stdout.on('data', (chunk) => { serverStdout += chunk.toString('utf8'); });
  apiServer.stderr.on('data', (chunk) => { serverStderr += chunk.toString('utf8'); });
  const serverReady = await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(`Isolated API startup timed out. stdout=${serverStdout} stderr=${serverStderr}`)), 30000);
    const inspect = () => {
      for (const line of serverStdout.split(/\r?\n/)) {
        try { const value = JSON.parse(line); if (value.ready) { clearTimeout(timeout); resolve(value); return; } } catch {}
      }
    };
    apiServer.stdout.on('data', inspect);
    inspect();
    apiServer.once('exit', (code) => { clearTimeout(timeout); reject(new Error(`Isolated API exited (${code}). stdout=${serverStdout} stderr=${serverStderr}`)); });
  });
  assert.equal(serverReady.application_count, liveApplicationIds.length);

  const browser = await chromium.launch({ headless: true, executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } });
  const page = await context.newPage();
  const apiResponses = [];
  const pageErrors = [];
  let loadedResumePayload = null;
  let lastSavePayload = null;
  page.on('pageerror', (error) => pageErrors.push(error.message));
  context.on('response', (response) => {
    if (response.url().includes('/api/')) apiResponses.push({ url: response.url(), status: response.status(), contentType: response.headers()['content-type'] || '' });
  });
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const upstream = new URL(request.url());
    upstream.hostname = '127.0.0.1';
    upstream.port = String(serverReady.port);
    if (upstream.pathname.endsWith('/resume-document/save') && request.method() === 'POST') {
      lastSavePayload = request.postDataJSON();
    }
    const response = await route.fetch({ url: upstream.href, timeout: 120000 });
    const body = await response.body();
    if (upstream.pathname.endsWith('/resume-document') && request.method() === 'GET') {
      loadedResumePayload = JSON.parse(body.toString('utf8'));
    }
    const headers = { ...response.headers() };
    delete headers['content-length']; delete headers['transfer-encoding']; delete headers.connection;
    await route.fulfill({ status: response.status(), headers, body });
  });

  try {
    await page.goto('http://127.0.0.1:5173/#/resume', { waitUntil: 'domcontentloaded' });
    await page.locator('.rail').waitFor({ timeout: 30000 });
    const initial = await snapshot(page);
    assert.deepEqual(initial.applications.map((item) => item.application_id).sort(), liveApplicationIds);
    const initialApp = initial.applications.find((item) => item.application_id === appId);
    assert.equal(initialApp.company_name, 'Rex.zone');

    await page.getByRole('button', { name: /Application history/i }).click();
    const rexRow = page.locator('.timeline-row').filter({ hasText: 'Rex.zone' });
    await rexRow.waitFor({ timeout: 10000 });
    await rexRow.click();
    await page.locator('.rail nav button').filter({ hasText: 'Resume workspace' }).click();
    await page.locator('.resume-context h3').waitFor({ timeout: 10000 });
    assert.equal(normalize(await page.locator('.resume-context h3').innerText()), 'Rex.zone');

    const openEditor = page.getByTestId('open-resume-document-editor');
    await openEditor.click();
    try { await page.getByTestId('resume-document-editor').waitFor({ timeout: 10000 }); }
    catch (error) {
      console.error('EDITOR_OPEN_DIAGNOSTICS', JSON.stringify({ body: (await page.locator('body').innerText()).slice(-5000), load: loadedResumePayload, apiResponses: apiResponses.slice(-10), pageErrors }));
      throw error;
    }
    assert.equal(loadedResumePayload?.decision, 'ready');
    assert.equal(loadedResumePayload?.application_id, appId);
    assert(loadedResumePayload?.document?.content?.sections?.length >= 5);
    assert((loadedResumePayload?.skill_catalog || []).some((item) => item.text === 'MySQL' && item.group === 'Databases'));
    const resumeLoadHttp = apiResponses.find((item) => item.url.includes(`/applications/${appId}/resume-document`));
    assert(resumeLoadHttp && resumeLoadHttp.status === 200 && resumeLoadHttp.contentType.includes('application/json'), JSON.stringify(resumeLoadHttp));

    // CANCEL / DISCARD: an unsaved text change and temporary add/remove block leave no persisted revision.
    const firstSummary = page.locator('[data-block-type="summary_paragraph"]').first();
    const summaryBeforeCancel = await firstSummary.innerText();
    await replaceEditableBlock(page, firstSummary, swapCase(summaryBeforeCancel));
    const bulletCountBeforeCancel = await page.locator('[data-block-type="project_bullet"]').count();
    await page.locator('[data-block-type="project_bullet"]').first().click();
    await page.getByRole('button', { name: 'ADD SUPPORTED BULLET' }).click();
    await page.keyboard.type('Text-to-SQL Project');
    assert.equal(await page.locator('[data-block-type="project_bullet"]').count(), bulletCountBeforeCancel + 1);
    await page.getByRole('button', { name: 'REMOVE BULLET FROM THIS SESSION' }).click();
    assert.equal(await page.locator('[data-block-type="project_bullet"]').count(), bulletCountBeforeCancel);
    await page.getByRole('button', { name: 'CANCEL / DISCARD' }).click();
    await openEditor.waitFor({ timeout: 20000 });
    await openEditor.click();
    await page.getByTestId('resume-document-editor').waitFor({ timeout: 20000 });
    assert.equal(normalize(await page.locator('[data-block-type="summary_paragraph"]').first().innerText()), normalize(summaryBeforeCancel));
    assert.equal(await page.locator('[data-block-type="project_bullet"]').count(), bulletCountBeforeCancel);

    // Edit the actual supported text areas, preserving each node's canonical ID and source references.
    const summary = page.locator('[data-block-type="summary_paragraph"]').first();
    await replaceEditableBlock(page, summary, swapCase(await summary.innerText()));
    await summary.click();
    await summary.evaluate((element) => {
      const content = element.querySelector('.resume-editor-editable-content');
      const walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT);
      const textNode = walker.nextNode();
      const range = document.createRange();
      range.setStart(textNode, 0); range.setEnd(textNode, Math.min(8, textNode.textContent.length));
      const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
    });
    await page.getByRole('button', { name: 'Bold' }).click();
    await page.getByRole('button', { name: 'Italic' }).click();
    await page.getByRole('button', { name: 'Underline' }).click();
    assert(await summary.locator('strong').count() > 0, 'Bold formatting did not apply to the selected summary text');
    await page.getByLabel('Font size preset').selectOption('12');
    await page.getByLabel('Line spacing preset').selectOption('1.1');

    await page.getByLabel('Section heading professional_summary').fill('SUMMARY AND PROFILE');
    await page.getByLabel('Section spacing before').selectOption('2');
    await page.getByLabel('Section spacing after').selectOption('2');

    const database = page.locator('[data-block-type="skill_group"]').filter({ hasText: 'Databases:' });
    await page.getByLabel('Edit skill SQLite').fill('sqlite');
    const catalog = loadedResumePayload.skill_catalog;
    const mysql = catalog.find((item) => item.group === 'Databases' && item.text === 'MySQL');
    const chroma = catalog.find((item) => item.group === 'Databases' && item.text === 'ChromaDB');
    assert(mysql && chroma, 'Canonical skill catalog does not contain expected Rex.zone-supported database entries');
    const skillPicker = page.getByLabel('Supported skill to add');
    await skillPicker.selectOption(mysql.id);
    await page.getByRole('button', { name: 'ADD SKILL' }).click();
    await page.getByLabel('Edit skill MySQL').waitFor();
    await page.getByRole('button', { name: 'Move skill MySQL up' }).click();
    await page.getByRole('button', { name: 'Remove skill ChromaDB' }).click();
    await skillPicker.selectOption(chroma.id);
    await page.getByRole('button', { name: 'ADD SKILL' }).click();
    await page.getByLabel('Edit skill MySQL').waitFor();
    assert(await database.getByLabel('Edit skill MySQL').isVisible());

    const projectSectionHeading = page.getByLabel('Section heading projects');
    await projectSectionHeading.fill('PROJECTS · PORTFOLIO');
    const projectEntries = page.locator('[data-block-type="project_entry"]');
    const projectTitle = projectEntries.first();
    await replaceEditableBlock(page, projectTitle, swapCase(await projectTitle.innerText()));
    await projectTitle.click();
    await page.getByLabel('Block spacing before').selectOption('2');
    await page.getByLabel('Block spacing after').selectOption('3');
    await projectEntries.nth(1).click();
    await page.getByLabel('Block spacing before').selectOption('0.5');
    const projectBullets = page.locator('[data-block-type="project_bullet"]');
    const textSqlBullet = projectBullets.filter({ hasText: /natural[- ]language/i }).first();
    const oldBullet = await textSqlBullet.innerText();
    const newBullet = oldBullet.replace(/natural[- ]language/i, (match) => match === 'NATURAL-LANGUAGE' ? 'natural-language' : 'NATURAL-LANGUAGE');
    assert.notEqual(newBullet, oldBullet);
    await replaceEditableBlock(page, textSqlBullet, newBullet);
    await textSqlBullet.click();
    await page.getByLabel('Block spacing after').selectOption('1.5');
    await projectBullets.nth(1).click();
    await page.getByRole('button', { name: 'MOVE UP' }).click();

    const education = page.locator('[data-block-type="education_line"]');
    const educationBefore = await education.first().innerText();
    await replaceEditableBlock(page, education.first(), swapCase(educationBefore));
    await education.first().click();
    await page.getByRole('button', { name: 'MOVE ENTRY DOWN' }).click();

    await page.getByLabel('Section heading education').fill('EDUCATION AND TRAINING');
    const certifications = page.locator('[data-block-type="certification_entry"]');
    await replaceEditableBlock(page, certifications.first(), swapCase(await certifications.first().innerText()));
    await certifications.first().click();
    await page.getByRole('button', { name: 'MOVE ENTRY DOWN' }).click();
    await page.getByLabel('Section heading certifications').fill('CERTIFICATIONS AND COURSES');

    // Add a source-backed bullet using only words in its canonical project title.
    await projectBullets.first().click();
    await page.getByRole('button', { name: 'ADD SUPPORTED BULLET' }).click();
    await page.keyboard.type('Text-to-SQL Project');
    assert(await page.locator('[data-block-type="project_bullet"]').count() === bulletCountBeforeCancel + 1);

    const saveResponsePromise = page.waitForResponse((response) => response.url().includes(`/applications/${appId}/resume-document/save`), { timeout: 120000 });
    await page.getByTestId('save-resume-document').click();
    const saveResponse = await saveResponsePromise;
    const saveResult = await saveResponse.json();
    assert.equal(saveResponse.status(), 200, JSON.stringify(saveResult));
    assert.equal(saveResult.decision, 'saved', JSON.stringify(saveResult));
    assert.equal(saveResult.validation.final_status, 'PASS');
    assert.equal(saveResult.validation.page_count, 1);
    assert(Object.values(saveResult.validation.checks).every(Boolean), JSON.stringify(saveResult.validation.checks));

    const savedBootstrap = await snapshot(page);
    const savedApp = savedBootstrap.applications.find((item) => item.application_id === appId);
    assert.deepEqual(savedBootstrap.applications.map((item) => item.application_id).sort(), liveApplicationIds);
    assert.equal(savedApp.company_name, 'Rex.zone');
    assert.equal(savedApp.resume_working_artifact_stale, false);
    for (const key of finalKeys) assert.deepEqual(savedApp[key] ?? null, finalMetadataBefore[key], `Final metadata changed: ${key}`);
    assert(lastSavePayload && lastSavePayload.document, 'Expected a real editor Save Working API payload');
    assert(lastSavePayload.document.content.sections.find((section) => section.type === 'professional_summary').title === 'SUMMARY AND PROFILE');
    assert(lastSavePayload.document.content.sections.some((section) => section.blocks.some((block) => block.type === 'skill_group' && block.items?.some((item) => item.text === 'MySQL'))));

    const isolatedPath = (reference) => path.resolve(isolatedRoot, String(reference).replace(/[\\/]/g, path.sep));
    const savedDocx = isolatedPath(savedApp.working_resume_docx_path);
    const savedPdf = isolatedPath(savedApp.working_resume_pdf_path);
    assert(fs.existsSync(savedDocx) && fs.existsSync(savedPdf));
    assert.equal(sha256(savedDocx), savedApp.working_resume_docx_sha256);
    assert.equal(sha256(savedPdf), savedApp.working_resume_pdf_sha256);
    const docxInspection = JSON.parse(require('node:child_process').execFileSync('python', ['-X','utf8','-B','-c', "import sys,json;from docx import Document;p=Document(sys.argv[1]);t='\\n'.join(x.text for x in p.paragraphs);print(json.dumps({'tables':len(p.tables),'text':t},ensure_ascii=False))", savedDocx], { encoding: 'utf8' }));
    assert.equal(docxInspection.tables, 0);
    const pdfInfo = require('node:child_process').execFileSync('pdfinfo', [savedPdf], { encoding: 'utf8' });
    assert.match(pdfInfo, /Pages:\s+1/);
    const pdfText = require('node:child_process').execFileSync('pdftotext', [savedPdf, '-'], { encoding: 'utf8' });
    for (const text of ['MySQL', 'SUMMARY AND PROFILE', 'PROJECTS · PORTFOLIO', 'NATURAL-LANGUAGE', 'EDUCATION AND TRAINING', 'CERTIFICATIONS AND COURSES']) {
      assert(docxInspection.text.toLowerCase().includes(text.toLowerCase()), `DOCX omitted ${text}`);
      assert(pdfText.toLowerCase().includes(text.toLowerCase()), `PDF omitted ${text}`);
    }
    const report = JSON.parse(fs.readFileSync(isolatedPath(savedApp.working_resume_validation_reference), 'utf8'));
    assert.equal(report.final_status, 'PASS');
    assert.equal(report.page_count, 1);
    assert.equal(report.checks.truth_provenance, true);
    assert.equal(report.validation_view.includes('temporary canonical labels'), true);

    // Reject a fabricated metric in the isolated copy and prove rollback/non-mutation.
    await page.getByTestId('open-resume-document-editor').click();
    await page.getByTestId('resume-document-editor').waitFor({ timeout: 20000 });
    const invalidBullet = page.locator('[data-block-type="project_bullet"]').filter({ hasText: /natural-language/i }).first();
    const invalidOriginal = await invalidBullet.innerText();
    await replaceEditableBlock(page, invalidBullet, `${invalidOriginal} with 10000 enterprise clients`);
    const isolatedStorePath = path.join(isolatedRoot, 'data', 'applications.json');
    const storeBytesBeforeInvalid = fs.readFileSync(isolatedStorePath);
    const activeBeforeInvalid = { docx: savedApp.working_resume_docx_path, pdf: savedApp.working_resume_pdf_path, revision: savedApp.working_resume_revision_id };
    const fileListBeforeInvalid = ['output/resumes','output/reports','output/resume_edits'].flatMap((folder) => walkFiles(path.join(isolatedRoot, folder)).map((file) => path.relative(isolatedRoot, file).replace(/\\/g, '/'))).sort();
    const invalidResponsePromise = page.waitForResponse((response) => response.url().includes(`/applications/${appId}/resume-document/save`), { timeout: 120000 });
    await page.getByTestId('save-resume-document').click();
    const invalidResponse = await invalidResponsePromise;
    const invalidResult = await invalidResponse.json();
    assert.equal(invalidResponse.status(), 409);
    assert.equal(invalidResult.decision, 'validation_failed');
    assert.equal(invalidResult.previous_working_preserved, true);
    assert.deepEqual(fs.readFileSync(isolatedStorePath), storeBytesBeforeInvalid);
    const afterInvalid = (await snapshot(page)).applications.find((item) => item.application_id === appId);
    assert.deepEqual({ docx: afterInvalid.working_resume_docx_path, pdf: afterInvalid.working_resume_pdf_path, revision: afterInvalid.working_resume_revision_id }, activeBeforeInvalid);
    const fileListAfterInvalid = ['output/resumes','output/reports','output/resume_edits'].flatMap((folder) => walkFiles(path.join(isolatedRoot, folder)).map((file) => path.relative(isolatedRoot, file).replace(/\\/g, '/'))).sort();
    assert.deepEqual(fileListAfterInvalid, fileListBeforeInvalid);
    await page.getByRole('button', { name: 'CANCEL / DISCARD' }).click();

    // The live application store, generator, template, canonical files, and artifacts are byte-identical.
    assert.deepEqual(fs.readFileSync(liveStorePath), liveStoreBytes, 'Live application records were modified');
    assert.deepEqual(JSON.parse(fs.readFileSync(liveStorePath, 'utf8')).applications.map((item) => item.application_id).sort(), liveApplicationIds);
    for (const [file, hash] of liveProtectedHashes) assert.equal(sha256(file), hash, `Live protected file changed: ${file}`);
    assert.deepEqual(Object.fromEntries(finalKeys.map((key) => [key, liveApp[key] ?? null])), finalMetadataBefore);
    assert.deepEqual(pageErrors, [], `Browser page errors: ${pageErrors.join('\n')}`);

    console.log(JSON.stringify({
      result: 'PASS',
      application: { id: appId, company: 'Rex.zone', application_count: liveApplicationIds.length, live_store_unchanged: true },
      load: { status: resumeLoadHttp.status, content_type: resumeLoadHttp.contentType, decision: loadedResumePayload.decision, schema_version: loadedResumePayload.document.schema_version, skill_catalog_count: loadedResumePayload.skill_catalog.length },
      editor: { summary: true, skill_text_add_remove_reorder: true, education_text_and_record_reorder: true, certification_text_and_reorder: true, project_title_and_bullet: true, section_headings: true, controlled_spacing: true, formatting: true, bullet_add_remove: true, cancel_discards: true },
      save: { revision_id: saveResult.working.revision_id, page_count: saveResult.working.page_count, final_status: saveResult.validation.final_status, checks: saveResult.validation.checks },
      outputs: { docx: savedApp.working_resume_docx_path, pdf: savedApp.working_resume_pdf_path, docx_hash_matches: true, pdf_hash_matches: true, one_page: true, edits_present_in_both: true },
      rejected_edit: { decision: invalidResult.decision, rollback_verified: true },
      protections: { resume_generator_unchanged: true, live_application_store_unchanged: true, application_count_unchanged: true, final_artifact_hashes_unchanged: true },
      api_requests: apiResponses.length,
      page_errors: pageErrors,
    }, null, 2));
  } finally {
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
    apiServer.kill();
    await new Promise((resolve) => { if (apiServer.exitCode !== null) resolve(); else apiServer.once('exit', resolve); });
    fs.rmSync(serverScript, { force: true });
    fs.rmSync(isolatedRoot, { recursive: true, force: true });
  }
})().catch((error) => { console.error(error?.stack || error); process.exitCode = 1; });
