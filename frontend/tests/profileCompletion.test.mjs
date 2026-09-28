import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { chromium } from 'playwright'
import { createServer } from 'vite'

// The modal is retired. What replaced it is not another dialog but the absence
// of one: a gap is now answered on the page that states it. This pins that the
// dialog is gone AND that the two things it used to be reachable from still
// work -- a deleted component is only an improvement if nothing was relying on
// it to reach the fields.
test('nothing opens a profile dialog, and the deep-link fallback survives', async () => {
  const [app, page, analysis, dashboard, shift] = await Promise.all([
    readFile(new URL('../src/App.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/pages/ProfileCompletionPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/AnalysisPanel.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/pages/AuthenticatedDashboard.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../../GradusIQ_career/features/shift.py', import.meta.url), 'utf8'),
  ])

  // The batch host is NOT retired: /profile/complete is still where a deep
  // link lands, and it still renders the same form the fields compose.
  assert.match(app, /path="\/profile\/complete"/)
  assert.match(page, /<ProfileCompletionForm/)

  // No dialog anywhere in the authenticated dashboard, and no component left
  // behind that could grow one back.
  assert.doesNotMatch(dashboard, /ProfileCompletionModal/)
  assert.doesNotMatch(dashboard, /role="dialog"|aria-modal/)
  await assert.rejects(
    readFile(new URL('../src/components/profile/ProfileCompletionModal.tsx', import.meta.url), 'utf8'),
    'ProfileCompletionModal.tsx is still present -- it has no importers',
  )

  // AnalysisPanel asks for ONE field, by path, rather than opening a form over
  // every field the surface owns.
  assert.match(analysis, /useProfileFieldRequest/)
  assert.match(analysis, /requestProfileField\(\{ path: field\.path/)
  // Outside a provider there is nothing to scroll to, so the deep link stays.
  assert.match(analysis, /profileCompletionHref\(field\.path\)/)

  const requiredPaths = shift.match(/required_paths\s*=\s*\(([\s\S]*?)\)/)?.[1] ?? ''
  assert.doesNotMatch(requiredPaths, /ai_anxiety_level/)
})

test('analysis failures render one coherent recovery instruction', async () => {
  const [panel, api] = await Promise.all([
    readFile(new URL('../src/components/AnalysisPanel.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/api/analysisApi.mjs', import.meta.url), 'utf8'),
  ])

  assert.doesNotMatch(panel, /analysis-failed-retry/)
  assert.match(api, /The analysis service is busy right now\. Try again in a moment\./)
  assert.match(api, /Too many requests\. Wait a minute and try again\./)
  assert.match(api, /Analysis request failed \(\$\{response\.status\}\)\./)
})

/**
 * The checklist counts what the runners actually require.
 *
 * Same arrangement as the N/A sentinel test above: required_paths is Python
 * that never crosses the wire, so the client mirrors it and this fails if the
 * two drift. Derived from the three runners rather than hardcoded -- a test
 * that restated the four paths by hand would agree with a stale mirror.
 */
test('the checklist mirrors GAP/FIT/SHIFT required_paths, less the resume-owned ones', async () => {
  const [mirror, analysis, gap, fit, shift, base] = await Promise.all([
    readFile(new URL('../src/lib/profileChecklist.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/AnalysisPanel.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../../GradusIQ_career/features/gap.py', import.meta.url), 'utf8'),
    readFile(new URL('../../GradusIQ_career/features/fit.py', import.meta.url), 'utf8'),
    readFile(new URL('../../GradusIQ_career/features/shift.py', import.meta.url), 'utf8'),
    readFile(new URL('../../GradusIQ_career/features/base.py', import.meta.url), 'utf8'),
  ])

  const pathsOf = (source) =>
    [...(source.match(/required_paths\s*=\s*\(([\s\S]*?)\)/)?.[1] ?? '').matchAll(/"([^"]+)"/g)].map((m) => m[1])
  const required = new Set([...pathsOf(gap), ...pathsOf(fit), ...pathsOf(shift)])
  assert.ok(required.size > 0, 'no required_paths could be read from the runners')

  // Résumé-owned paths are excluded by the SAME set AnalysisPanel routes on,
  // read from its source, so the two cannot disagree about what /resume owns.
  const resumeOwned = [...(analysis.match(/RESUME_OWNED_PATHS = new Set\(\[([\s\S]*?)\]\)/)?.[1] ?? '').matchAll(/'([^']+)'/g)].map((m) => m[1])
  assert.deepEqual(resumeOwned.slice().sort(), ['career.skills_self_reported', 'career.work_experience'])
  for (const path of resumeOwned) required.delete(path)

  const mirrored = [...mirror.matchAll(/\{ path: '([^']+)', label: '([^']+)' \}/g)]
  assert.deepEqual(
    mirrored.map(([, path]) => path).slice().sort(),
    [...required].sort(),
    'CHECKLIST_FIELDS no longer matches the runners union',
  )

  // ai_anxiety_level is editable on the Career tab and gates nothing, so it
  // must never be counted. This is the assertion that catches someone
  // "helpfully" adding it because the field is right there.
  assert.equal(required.has('career.ai_anxiety_level'), false)
  // Comments stripped first: the module argues at length about why these two
  // are absent, and naming them in that argument is the opposite of the
  // mistake being guarded against.
  const mirrorCode = mirror.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
  assert.doesNotMatch(mirrorCode, /ai_anxiety_level|major_current/)

  // The words a student reads come from base.py, so a gap named by the
  // checklist and the same gap named by a skipped analysis read identically.
  const labels = Object.fromEntries(
    [...(base.match(/FIELD_LABELS: Mapping\[str, str\] = \{([\s\S]*?)\n\}/)?.[1] ?? '')
      .matchAll(/"([^"]+)":\s*"([^"]+)"/g)].map((m) => [m[1], m[2]]),
  )
  assert.ok(Object.keys(labels).length > 0, 'FIELD_LABELS could not be read from base.py')
  for (const [, path, label] of mirrored) {
    assert.equal(label, labels[path], `checklist label for ${path} disagrees with base.py`)
  }
})

// The N/A the form writes is FIT's sentinel, and nothing at runtime would
// notice if the two drifted: the value crosses the boundary as an opaque
// string in a PATCH body, so a stale client would just start telling FIT that
// every staying student is switching. This is the check that catches it.
test('the frontend N/A sentinel still matches fit.py', async () => {
  const [sentinel, fit] = await Promise.all([
    readFile(new URL('../src/lib/majorSentinel.ts', import.meta.url), 'utf8'),
    readFile(new URL('../../GradusIQ_career/features/fit.py', import.meta.url), 'utf8'),
  ])
  const python = fit.match(/^_NO_INTENDED_MAJOR\s*=\s*"([^"]*)"/m)?.[1]
  const typescript = sentinel.match(/export const NO_INTENDED_MAJOR = '([^']*)'/)?.[1]
  assert.ok(python, 'fit.py no longer defines _NO_INTENDED_MAJOR')
  assert.ok(typescript, 'majorSentinel.ts no longer exports NO_INTENDED_MAJOR')
  assert.equal(typescript, python)
  // fit.py compares case-insensitively; the mirrored read helper must too.
  assert.match(sentinel, /toUpperCase\(\) === NO_INTENDED_MAJOR/)
})

// Each claim below is the same claim it was before the fields were extracted;
// only the file holding the answer changed. The rules now live one level down
// in ./fields, which is the point -- the completion form and the Career tab's
// inline rows both render these, so a rule proven here is proven for both.
test('the completion form owns only its five fields and routes the rest to resume review', async () => {
  const [form, analysis, page, major, graduation, comfort] = await Promise.all([
    readFile(new URL('../src/components/profile/ProfileCompletionForm.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/AnalysisPanel.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/pages/ProfileCompletionPage.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/profile/fields/MajorField.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/profile/fields/GraduationField.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/profile/fields/AiComfortField.tsx', import.meta.url), 'utf8'),
  ])

  // Skills belong to /resume. The form must not offer a competing editor, and
  // must not claim a field it cannot write.
  assert.doesNotMatch(form, /skills_technical|skills_soft|Technical skills|Professional skills/)
  assert.match(form, /resume review/)
  // Both résumé-owned gaps bypass the modal entirely, or they reopen a dialog
  // with no field for the thing that is missing.
  // Matched against the LABELS map alone -- the prose around it names these
  // paths precisely to record that their absence is a decision.
  const labels = page.match(/const LABELS: Record<string, string> = \{([\s\S]*?)\};/)?.[1] ?? ''
  assert.ok(labels, 'ProfileCompletionPage no longer declares a LABELS map')
  for (const path of ['career.skills_self_reported', 'career.work_experience']) {
    assert.match(analysis, new RegExp(`RESUME_OWNED_PATHS = new Set\\(\\[[^\\]]*'${path}'`))
    assert.doesNotMatch(labels, new RegExp(path.replace('.', '\\.')))
  }

  // "Not answered" was a default-selected state dressed as a choice, so a
  // never-asked profile rendered as an answered one. Null is now unselected.
  // The Career tab uses that phrase as a READ-ONLY absence label, which is a
  // different thing; what must not exist is an option offering it as a choice.
  assert.doesNotMatch(comfort, /\['not_answered'|Not answered/)
  assert.match(comfort, /Skip this if you'd rather not say\./)
  assert.doesNotMatch(comfort, /checked=\{value === ''\}/)

  // Not switching is written, never typed: the checkbox gates the field and
  // the sentinel comes from the shared constant.
  assert.match(major, /I'm planning to switch majors/)
  assert.match(major, /disabled=\{!switching \|\| disabled\}/)
  assert.match(major, /value\.switching \? value\.majorIntended\.trim\(\) : NO_INTENDED_MAJOR/)

  // Both-or-neither still belongs to the graduation pair, not to whichever
  // container happens to render it.
  assert.match(graduation, /Choose both a graduation season and year, or leave both blank\./)

  // The literal may appear in prose (comments, helper copy); what must not
  // exist is a second hardcoded copy of it in the code itself -- in ANY of the
  // files that now render these fields.
  for (const source of [form, major, graduation, comfort]) {
    const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
    assert.doesNotMatch(code, /'N\/A'|"N\/A"/)
  }

  // Both hosts render the SAME components. A second copy of a field is the
  // failure this whole extraction exists to prevent.
  assert.match(form, /from '\.\/fields\/MajorField'/)
  assert.match(form, /from '\.\/fields\/GraduationField'/)
  assert.match(form, /from '\.\/fields\/AiComfortField'/)
  const career = await readFile(new URL('../src/components/career/CareerProfile.tsx', import.meta.url), 'utf8')
  for (const field of ['MajorField', 'GraduationField', 'AiComfortField']) {
    assert.match(career, new RegExp(`from '\\.\\./profile/fields/${field}'`))
  }
})

/**
 * The batch host, driven as a page.
 *
 * The modal's test already exercises this form; this drives the OTHER host, so
 * the extraction is proven to have kept both working off one set of field
 * components rather than quietly leaving the page behind. What it checks is
 * what only the batch host can do: several fields answered together and
 * written in a single request.
 */
test('the /profile/complete page still saves through the recomposed form', { timeout: 45_000 }, async (t) => {
  const patches = []
  const apiPlugin = { name: 'profile-api', configureServer(server) { server.middlewares.use((request, response, next) => {
    if (request.url?.split('?')[0] === '/api/v2/student/me/profile' && request.method === 'PATCH') {
      let body = ''
      request.on('data', (chunk) => { body += chunk })
      request.on('end', () => {
        patches.push(JSON.parse(body))
        response.statusCode = 200
        response.setHeader('content-type', 'application/json')
        response.end(JSON.stringify({ ok: true }))
      })
      return
    }
    next()
  }) } }

  const server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    cacheDir: fileURLToPath(new URL('../node_modules/.vite-profile-page', import.meta.url)),
    logLevel: 'silent',
    plugins: [apiPlugin],
    server: { host: '127.0.0.1' },
  })
  await server.listen()
  t.after(async () => server.close())
  const address = server.httpServer?.address()
  assert.ok(address && typeof address === 'object')
  const browser = await chromium.launch()
  t.after(async () => browser.close())
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } })
  await page.goto(`http://127.0.0.1:${String(address.port)}/authenticated-dashboard-preview.html?mode=profile-complete`)
  await page.getByRole('heading', { name: 'Complete your profile' }).waitFor()

  // The same field components the Career tab renders inline, in batch layout.
  assert.equal(await page.getByLabel("I'm planning to switch majors").isChecked(), false)
  assert.equal(await page.getByLabel('Intended major').isDisabled(), true)
  assert.equal(await page.getByLabel('Season').inputValue(), 'Spring')
  assert.equal(await page.getByLabel('Year').inputValue(), '2028')
  assert.equal(await page.locator('input[name="ai-comfort"]:checked').count(), 0)

  // ?field= is honoured: the gap the student was sent here for is marked.
  await page.locator('.profile-form-field--needed').first().waitFor()

  // BOTH OR NEITHER still holds in the batch host -- the rule travelled with
  // the field, so neither surface carries its own copy to keep in sync.
  await page.getByLabel('Season').selectOption('')
  await page.getByRole('button', { name: 'Save changes' }).click()
  await page.getByText('Choose both a graduation season and year, or leave both blank.').waitFor()
  assert.equal(patches.length, 0, 'an invalid pair was sent from the page')

  // Several answers, one request. This is what the batch host is for, and the
  // reason it is not being retired in favour of the inline rows.
  await page.getByLabel('Season').selectOption('Fall')
  await page.getByLabel("I'm planning to switch majors").check()
  await page.getByLabel('Intended major').fill('Data Science')
  await page.getByLabel('High').check()
  await page.getByRole('button', { name: 'Save changes' }).click()
  await page.waitForFunction(() => document.body.dataset.profileReloaded === 'yes')
  assert.equal(patches.length, 1, 'the batch host split one submit into several requests')
  assert.deepEqual(patches[0], {
    major_intended: 'Data Science',
    expected_graduation: 'Fall 2028',
    ai_anxiety_level: 'high',
  })
})
