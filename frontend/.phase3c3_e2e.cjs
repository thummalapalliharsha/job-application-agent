const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { chromium } = require(path.join(os.tmpdir(), 'career-os-playwright-3c3', 'node_modules', 'playwright-core'));

const root = 'C:\\project\\job-application-agent';
const appId = 'app_14a66f897623';
const baselinePath = path.join(os.tmpdir(), 'career-os-phase3c3-baseline-RmamIX.json');
const baseline = JSON.parse(fs.readFileSync(baselinePath, 'utf8'));
const normalize = (value) => String(value || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
const sha256 = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex').toUpperCase();
const projectPath = (ref) => path.resolve(root, String(ref).replace(/[\\/]/g, path.sep));
const finalKeys = ['resume_reference','resume_pdf_reference','resume_docx_path','resume_pdf_path','resume_docx_sha256','resume_pdf_sha256','resume_generation_id','resume_finalized_at','resume_status'];
const allowedWorkingKeys = new Set(['working_resume_reference','working_resume_pdf_reference','working_resume_docx_path','working_resume_pdf_path','working_resume_docx_sha256','working_resume_pdf_sha256','working_resume_generation_id','working_resume_generated_at','working_resume_revision_id','working_resume_revision_reference','working_resume_source_plan_sha256','working_resume_validated','working_resume_validated_at','working_resume_validation_reference','resume_validation_reference','resume_working_artifact_stale','last_updated']);

function targetApp(bootstrap) {
  const app = (bootstrap.applications || []).find((item) => item.application_id === appId);
  assert(app, `Selected application ${appId} was not returned by bootstrap`);
  assert.equal(app.company_name, 'Rex.zone');
  return app;
}
function changedKeys(before, after) {
  return [...new Set([...Object.keys(before), ...Object.keys(after)])].filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]));
}
function assertPreservedArtifacts() {
  const changed = [];
  for (const [reference, expected] of Object.entries(baseline.hashes)) {
    if (reference.toLowerCase() === 'data\\applications.json') continue;
    const actual = sha256(projectPath(reference));
    if (actual !== expected.toUpperCase()) changed.push({ reference, expected, actual });
  }
  assert.deepEqual(changed, [], `Protected file hashes changed: ${JSON.stringify(changed)}`);
}
async function snapshot(page) {
  return await page.evaluate(async () => {
    const response = await fetch('/api/bootstrap');
    if (!response.ok) throw new Error(`bootstrap failed: ${response.status}`);
    return await response.json();
  });
}
async function replaceBlockText(page, block, oldText, nextText) {
  await block.scrollIntoViewIfNeeded();
  await block.click({ position: { x: 8, y: 9 } });
  await page.keyboard.press('Home');
  await page.keyboard.press('Shift+End');
  await page.waitForTimeout(200);
  const selected = await page.evaluate(() => window.getSelection()?.toString() || '');
  const diagnostics = await block.evaluate((el) => ({ outer: el.outerHTML.slice(0, 2400), active: document.activeElement?.outerHTML?.slice(0, 500), selection: window.getSelection()?.toString(), contenteditable: el.getAttribute('contenteditable'), inner: el.querySelector('.resume-editor-editable-content')?.outerHTML?.slice(0, 1000) }));
  assert.equal(normalize(selected), normalize(oldText), `Browser selected unexpected text: ${JSON.stringify(selected)}; DOM=${JSON.stringify(diagnostics)}`);
  await page.keyboard.type(nextText);
  await page.waitForTimeout(300);
  const current = await block.innerText();
  assert.equal(normalize(current), normalize(nextText), `Block replacement did not apply: ${JSON.stringify(current)}`);
}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', args: ['--no-sandbox'] });
  const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1440, height: 1050 } });
  const page = await context.newPage();
  const apiResponses = [];
  const consoleErrors = [];
  context.on('response', (response) => { if (response.url().includes('/api/')) apiResponses.push({ url: response.url(), status: response.status(), contentType: response.headers()['content-type'] || '' }); });
  page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  await page.route('**/api/**', async (route) => {
    const upstream = new URL(route.request().url());
    upstream.port = '8505';
    if (upstream.pathname.endsWith('/resume-document/save')) {
      const body = route.request().postDataJSON();
      const bullets = (body.document.content.sections || []).flatMap((section) => (section.blocks || []).filter((block) => block.type === 'project_bullet').map((block) => ({ list_style: block.formatting?.list_style, text: (block.runs || []).map((run) => run.text).join('') })));
      fs.writeFileSync(path.join(os.tmpdir(), 'career-os-phase3c3-candidate.json'), JSON.stringify(body.document));
      console.log('INTERCEPTED_SAVE_BULLETS=' + JSON.stringify(bullets));
    }
    const response = await route.fetch({ url: upstream.href, timeout: 45000 });
    await route.fulfill({ response });
  });
  const errors = [];
  try {
    await page.goto('http://127.0.0.1:5173/#/resume', { waitUntil: 'domcontentloaded' });
    await page.locator('.rail').waitFor({ timeout: 20000 });
    const initial = await snapshot(page);
    const initialApp = targetApp(initial);
    const appIdsBefore = initial.applications.map((item) => item.application_id).sort();
    const finalMetadataBefore = Object.fromEntries(finalKeys.map((key) => [key, initialApp[key] ?? null]));
    const workingBefore = {
      docx: initialApp.working_resume_docx_path,
      pdf: initialApp.working_resume_pdf_path,
      docxHash: initialApp.working_resume_docx_sha256,
      pdfHash: initialApp.working_resume_pdf_sha256,
      revision: initialApp.working_resume_revision_id || null,
      stale: initialApp.resume_working_artifact_stale,
    };
    assert.equal(initialApp.resume_working_artifact_stale, false, 'Rex.zone Working Resume must begin current');
    assert(initialApp.working_resume_docx_available && initialApp.working_resume_pdf_available, 'Existing Working DOCX/PDF must be available');

    // Select the actual Rex.zone application via the visible history surface.
    await page.getByRole('button', { name: /Application history/i }).click();
    const rexHistoryRow = page.locator('.timeline-row').filter({ hasText: 'Rex.zone' });
    await rexHistoryRow.waitFor({ timeout: 10000 });
    await rexHistoryRow.click();
    await page.locator('.rail nav button').filter({ hasText: 'Resume workspace' }).click();
    await page.locator('.resume-context h3').waitFor({ timeout: 10000 });
    assert.equal(normalize(await page.locator('.resume-context h3').innerText()), 'Rex.zone');
    assert(await page.getByTestId('open-resume-document-editor').isVisible());
    await page.getByTestId('open-resume-document-editor').click();
    await page.getByTestId('resume-document-editor').waitFor({ timeout: 20000 });
    assert.equal(normalize(await page.locator('.resume-editor-context strong').innerText()), 'Rex.zone');
    assert((await page.locator('.resume-editor-context').innerText()).includes(appId));

    const editableBlocks = page.locator('[data-testid="resume-editable-block"]');
    const beforeBlocks = await editableBlocks.allTextContents();
    const alreadySaved = Boolean(initialApp.working_resume_revision_id && initialApp.working_resume_revision_reference && initialApp.working_resume_validation_reference);
    let saveResult;
    let savedDuringThisRun = false;
    let supportedEdit = null;
    if (alreadySaved) {
      assert(beforeBlocks.some((text) => text.includes('natural language')), 'The successfully saved, source-backed edit must reopen in the editor');
      const currentReport = JSON.parse(fs.readFileSync(projectPath(initialApp.working_resume_validation_reference), 'utf8'));
      saveResult = { decision: 'saved', persisted: true, working: { revision_id: initialApp.working_resume_revision_id, page_count: currentReport.page_count }, validation: currentReport };
      await page.getByRole('button', { name: 'CANCEL / DISCARD' }).click();
      await page.getByTestId('open-resume-document-editor').waitFor({ timeout: 20000 });
    } else {
      const firstEditIndex = beforeBlocks.findIndex((text) => text.includes('natural-language'));
      assert(firstEditIndex >= 0, `Expected source-backed Rex.zone project bullet not found. Blocks: ${JSON.stringify(beforeBlocks)}`);
      const editBlock = editableBlocks.nth(firstEditIndex);
      const oldText = await editBlock.innerText();
      const supportedText = oldText.replace('natural-language', 'natural language');
      assert.notEqual(supportedText, oldText);
      supportedEdit = { old: oldText, new: supportedText };
      await replaceBlockText(page, editBlock, oldText, supportedText);
      const afterBlocks = await editableBlocks.allTextContents();
      assert.equal(afterBlocks.length, beforeBlocks.length, 'The edit must not add/remove blocks');
      for (let i = 0; i < afterBlocks.length; i++) if (i !== firstEditIndex) assert.equal(normalize(afterBlocks[i]), normalize(beforeBlocks[i]), `Unexpected block change at ${i}`);

      const saveResponsePromise = page.waitForResponse((response) => response.url().includes(`/applications/${appId}/resume-document/save`), { timeout: 60000 });
      await page.getByTestId('save-resume-document').click();
      const saveResponse = await saveResponsePromise;
      saveResult = await saveResponse.json();
      assert.equal(saveResponse.status(), 200, JSON.stringify(saveResult));
      assert.equal(saveResult.decision, 'saved', JSON.stringify(saveResult));
      assert.equal(saveResult.persisted, true);
      assert.equal(saveResult.validation.final_status, 'PASS');
      assert.equal(saveResult.validation.page_count, 1);
      assert(saveResult.working.revision_id.startsWith('rev_'));
      savedDuringThisRun = true;
      await page.getByTestId('open-resume-document-editor').waitFor({ timeout: 30000 });
      assert((await page.locator('.notice').innerText()).includes('Working Resume saved and validated.'));
    }

    let savedBootstrap = await snapshot(page);
    let savedApp = targetApp(savedBootstrap);
    const appIdsAfterSave = savedBootstrap.applications.map((item) => item.application_id).sort();
    assert.deepEqual(appIdsAfterSave, appIdsBefore, 'No application may be created or removed');
    assert.equal(savedApp.application_id, appId);
    assert.equal(savedApp.company_name, 'Rex.zone');
    assert.deepEqual(savedApp.project_selection_record_ids, initialApp.project_selection_record_ids);
    assert.equal(savedApp.working_resume_revision_id, saveResult.working.revision_id);
    assert.equal(savedApp.resume_working_artifact_stale, false);
    if (savedDuringThisRun) {
      assert.notEqual(savedApp.working_resume_docx_path, workingBefore.docx);
      assert.notEqual(savedApp.working_resume_pdf_path, workingBefore.pdf);
    } else {
      assert.equal(savedApp.working_resume_docx_path, workingBefore.docx);
      assert.equal(savedApp.working_resume_pdf_path, workingBefore.pdf);
      assert.notEqual(savedApp.working_resume_docx_path, baseline.application_fields.working_resume_docx_path);
    }
    assert(savedApp.working_resume_docx_available && savedApp.working_resume_pdf_available);
    for (const key of finalKeys) assert.deepEqual(savedApp[key] ?? null, finalMetadataBefore[key], `Final metadata changed: ${key}`);
    const changed = changedKeys(initialApp, savedApp);
    assert(changed.every((key) => allowedWorkingKeys.has(key)), `Unexpected application fields changed: ${changed.filter((key) => !allowedWorkingKeys.has(key)).join(', ')}`);

    const newDocx = projectPath(savedApp.working_resume_docx_path);
    const newPdf = projectPath(savedApp.working_resume_pdf_path);
    assert(fs.existsSync(newDocx) && fs.existsSync(newPdf), 'New Working DOCX and PDF must exist');
    assert.equal(sha256(newDocx).toLowerCase(), String(savedApp.working_resume_docx_sha256).toLowerCase());
    assert.equal(sha256(newPdf).toLowerCase(), String(savedApp.working_resume_pdf_sha256).toLowerCase());
    const reportPath = projectPath(savedApp.working_resume_validation_reference);
    const validationReport = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
    assert.equal(validationReport.final_status, 'PASS');
    assert.equal(validationReport.page_count, 1);
    assert.equal(validationReport.contact_validation.passed, true);
    assert.equal(validationReport.ats_validation.standard_headings_present, true);
    assert.equal(validationReport.hyperlink_validation.passed, true);
    assert.equal(validationReport.project_link_validation.passed, true);
    assert.equal(validationReport.project_order_validation.passed, true);
    assert.equal(validationReport.placeholder_validation.passed, true);
    assert.equal(validationReport.ats_validation.text_extractable, true);
    assert.equal(validationReport.ats_validation.single_column, true);
    assert.equal(validationReport.ats_validation.problematic_tables_or_textboxes, false);
    const sidecar = JSON.parse(fs.readFileSync(projectPath(savedApp.working_resume_revision_reference), 'utf8'));
    assert.equal(sidecar.revision_id, saveResult.working.revision_id);
    assert.equal(sidecar.document.application_id, appId);
    assert.equal(sidecar.working_docx_sha256, savedApp.working_resume_docx_sha256);

    const docxInspection = JSON.parse(execFileSync('python', ['-X','utf8','-B','-c', "import sys,json;from docx import Document;p=Document(sys.argv[1]);t='\\n'.join(x.text for x in p.paragraphs);print(json.dumps({'tables':len(p.tables),'text':t},ensure_ascii=False))", newDocx], { encoding: 'utf8' }));
    assert.equal(docxInspection.tables, 0);
    assert(docxInspection.text.includes('natural language'), 'The supported edit must appear in the generated DOCX');
    const pdfInfo = execFileSync('pdfinfo', [newPdf], { encoding: 'utf8' });
    assert.match(pdfInfo, /Pages:\s+1/);
    const pdfText = execFileSync('pdftotext', [newPdf, '-'], { encoding: 'utf8' });
    assert(pdfText.includes('natural language'), 'The supported edit must appear in the generated PDF');

    // Existing view action must open a separate PDF tab and serve the new active PDF.
    const workingCard = page.locator('.artifact').filter({ hasText: 'WORKING VERSION' });
    const viewLink = workingCard.getByRole('link', { name: 'VIEW RESUME' });
    assert((await viewLink.getAttribute('href')).includes(encodeURIComponent(savedApp.working_resume_pdf_path)));
    const [pdfTab] = await Promise.all([page.waitForEvent('popup', { timeout: 30000 }), viewLink.click()]);
    await pdfTab.waitForTimeout(1000);
    assert(!pdfTab.isClosed(), 'VIEW RESUME must leave a new PDF tab open');
    const viewTabUrl = pdfTab.url();
    const inlineResponse = apiResponses.find((response) => response.url.includes('/api/artifact?') && response.url.includes('view=inline'));
    assert(inlineResponse, `Inline PDF response was not observed. Responses: ${JSON.stringify(apiResponses.slice(-8))}`);
    assert.equal(inlineResponse.status, 200);
    assert(inlineResponse.contentType.includes('application/pdf'));
    await pdfTab.close();

    // Existing downloads must serve the newly activated DOCX and PDF.
    const downloadsDir = path.join(os.tmpdir(), `career-os-phase3c3-downloads-${Date.now()}`);
    fs.mkdirSync(downloadsDir, { recursive: true });
    const [docxDownload] = await Promise.all([page.waitForEvent('download'), workingCard.getByRole('link', { name: 'DOWNLOAD DOCX' }).click()]);
    assert.equal(docxDownload.suggestedFilename(), path.basename(savedApp.working_resume_docx_path));
    const downloadedDocx = path.join(downloadsDir, docxDownload.suggestedFilename());
    await docxDownload.saveAs(downloadedDocx);
    assert.equal(sha256(downloadedDocx).toLowerCase(), String(savedApp.working_resume_docx_sha256).toLowerCase());
    const [pdfDownload] = await Promise.all([page.waitForEvent('download'), workingCard.getByRole('link', { name: 'DOWNLOAD PDF' }).click()]);
    assert.equal(pdfDownload.suggestedFilename(), path.basename(savedApp.working_resume_pdf_path));
    const downloadedPdf = path.join(downloadsDir, pdfDownload.suggestedFilename());
    await pdfDownload.saveAs(downloadedPdf);
    assert.equal(sha256(downloadedPdf).toLowerCase(), String(savedApp.working_resume_pdf_sha256).toLowerCase());

    // Navigate away and back: selected application and new Working links persist.
    await page.getByRole('button', { name: /Application history/i }).click();
    await page.locator('.timeline-row').filter({ hasText: 'Rex.zone' }).waitFor();
    await page.locator('.rail nav button').filter({ hasText: 'Resume workspace' }).click();
    await page.locator('.resume-context h3').waitFor();
    assert.equal(normalize(await page.locator('.resume-context h3').innerText()), 'Rex.zone');
    const persistentWorkingCard = page.locator('.artifact').filter({ hasText: 'WORKING VERSION' });
    assert(await persistentWorkingCard.getByRole('link', { name: 'VIEW RESUME' }).isVisible());
    assert(await persistentWorkingCard.getByRole('link', { name: 'DOWNLOAD DOCX' }).isVisible());
    assert(await persistentWorkingCard.getByRole('link', { name: 'DOWNLOAD PDF' }).isVisible());

    // Invalid/unsupported claim must be rejected in the editor and leave active artifacts/store untouched.
    await page.getByTestId('open-resume-document-editor').click();
    await page.getByTestId('resume-document-editor').waitFor({ timeout: 20000 });
    const invalidBlocks = page.locator('[data-testid="resume-editable-block"]');
    const invalidTexts = await invalidBlocks.allTextContents();
    const invalidIndex = invalidTexts.findIndex((text) => text.includes('natural language'));
    assert(invalidIndex >= 0, 'The saved supported edit must remain in the reopened editor');
    const invalidBlock = invalidBlocks.nth(invalidIndex);
    const invalidOriginal = await invalidBlock.innerText();
    const invalidText = `${invalidOriginal} with 10000 enterprise clients`;
    await replaceBlockText(page, invalidBlock, invalidOriginal, invalidText);
    const storePath = path.join(root, 'data', 'applications.json');
    const storeBytesBeforeInvalid = fs.readFileSync(storePath);
    const currentBeforeInvalid = targetApp(await snapshot(page));
    const activeBeforeInvalid = { docx: currentBeforeInvalid.working_resume_docx_path, pdf: currentBeforeInvalid.working_resume_pdf_path, docxHash: currentBeforeInvalid.working_resume_docx_sha256, pdfHash: currentBeforeInvalid.working_resume_pdf_sha256, revision: currentBeforeInvalid.working_resume_revision_id, report: currentBeforeInvalid.working_resume_validation_reference };
    const existingFilesBeforeInvalid = new Set(['output/resumes','output/reports','output/resume_edits'].flatMap((folder) => {
      const abs = path.join(root, folder);
      return fs.existsSync(abs) ? walkFiles(abs).map((f) => path.relative(root, f).replace(/\\/g, '/')) : [];
    }));
    const invalidResponsePromise = page.waitForResponse((response) => response.url().includes(`/applications/${appId}/resume-document/save`), { timeout: 60000 });
    await page.getByTestId('save-resume-document').click();
    const invalidResponse = await invalidResponsePromise;
    const invalidResult = await invalidResponse.json();
    assert.equal(invalidResponse.status(), 409, JSON.stringify(invalidResult));
    assert.equal(invalidResult.decision, 'validation_failed');
    assert.equal(invalidResult.previous_working_preserved, true);
    const alert = page.getByTestId('resume-validation-result');
    await alert.waitFor({ timeout: 10000 });
    assert((await alert.innerText()).toLowerCase().includes('unsupported'), await alert.innerText());
    assert(await page.getByTestId('resume-document-editor').isVisible(), 'Invalid content must leave the editor open');
    assert.deepEqual(fs.readFileSync(storePath), storeBytesBeforeInvalid, 'Rejected save must not change application data');
    const currentAfterInvalid = targetApp(await snapshot(page));
    assert.deepEqual({ docx: currentAfterInvalid.working_resume_docx_path, pdf: currentAfterInvalid.working_resume_pdf_path, docxHash: currentAfterInvalid.working_resume_docx_sha256, pdfHash: currentAfterInvalid.working_resume_pdf_sha256, revision: currentAfterInvalid.working_resume_revision_id, report: currentAfterInvalid.working_resume_validation_reference }, activeBeforeInvalid);
    assert.equal(sha256(projectPath(activeBeforeInvalid.docx)).toLowerCase(), String(activeBeforeInvalid.docxHash).toLowerCase());
    assert.equal(sha256(projectPath(activeBeforeInvalid.pdf)).toLowerCase(), String(activeBeforeInvalid.pdfHash).toLowerCase());
    const existingFilesAfterInvalid = new Set(['output/resumes','output/reports','output/resume_edits'].flatMap((folder) => {
      const abs = path.join(root, folder);
      return fs.existsSync(abs) ? walkFiles(abs).map((f) => path.relative(root, f).replace(/\\/g, '/')) : [];
    }));
    assert.deepEqual([...existingFilesAfterInvalid].sort(), [...existingFilesBeforeInvalid].sort(), 'Rejected save must not leave staged artifacts/reports/sidecars');

    assertPreservedArtifacts();
    const finalAfterInvalid = targetApp(await snapshot(page));
    for (const key of finalKeys) assert.deepEqual(finalAfterInvalid[key] ?? null, finalMetadataBefore[key], `Final metadata changed after invalid save: ${key}`);
    assert.deepEqual((await snapshot(page)).applications.map((item) => item.application_id).sort(), appIdsBefore, 'No new application was created');

    console.log(JSON.stringify({
      result: 'PASS', application: { id: appId, company: 'Rex.zone', count_preserved: appIdsBefore.length },
      supported_edit: supportedEdit || { already_persisted_in_active_revision: true },
      saved_revision: saveResult.working,
      validations: validationReport.checks,
      artifacts: { docx: savedApp.working_resume_docx_path, docx_sha256: savedApp.working_resume_docx_sha256, pdf: savedApp.working_resume_pdf_path, pdf_sha256: savedApp.working_resume_pdf_sha256, pages: saveResult.working.page_count, docx_contains_edit: true, pdf_contains_edit: true, view_opened_new_tab: true, view_tab_url: viewTabUrl, docx_downloaded_and_hash_matched: true, pdf_downloaded_and_hash_matched: true },
      navigation: { left_and_returned: true, selected_application_preserved: true, working_links_persisted: true },
      invalid_edit: { rejected: true, decision: invalidResult.decision, error: await alert.innerText(), previous_working_preserved: true, final_preserved: true },
      protected_files: { all_non_application_baseline_hashes_unchanged: true, final_metadata_unchanged: true, cover_letter_unchanged: true, generator_template_profiles_unchanged: true },
      api_response_count: apiResponses.length,
      console_errors: consoleErrors,
    }, null, 2));
  } finally {
    await context.close().catch(() => {});
    await browser.close().catch(() => {});
  }
})().catch((error) => { console.error(error?.stack || error); process.exitCode = 1; });

function walkFiles(directory) {
  const files = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...walkFiles(target)); else files.push(target);
  }
  return files;
}
