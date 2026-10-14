import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const read = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('dashboard loaders show skeleton shapes, not a line of Loading text', async () => {
  const loaders = {
    'components/CanvasCalendarPanel.tsx': 'Loading your Canvas calendar…',
    'components/TermPlanner.tsx': 'Loading terms…',
    'components/JobSearchPanel.tsx': 'Checking cached postings…',
    'components/GradeCalculatorPanel.tsx': 'Loading your grade calculator…',
  }
  for (const [path, label] of Object.entries(loaders)) {
    const source = await read(path)
    // The words stay, for screen readers, as the skeleton's label.
    assert.match(source, new RegExp(`<SkeletonRows label="${label}"`), path)
    assert.doesNotMatch(source, new RegExp(`<p[^>]*>${label}</p>`), path)
  }
  const skeleton = await read('components/Skeleton.tsx')
  assert.match(skeleton, /role="status"/)
  assert.match(skeleton, /className="sr-only">\{label\}/)
  assert.match(skeleton, /aria-hidden="true"/)
})

test('skeletons only pulse, so reduced motion leaves them standing still', async () => {
  const css = await read('index.css')
  const block = css.slice(css.indexOf('ACADEMIC + JOB SEARCH'))
  assert.match(block, /\.skeleton-item \{[^}]*animation: skeleton-pulse /)
  // The cards variant keeps its white card solid; only the shapes breathe.
  assert.match(block, /\.skeleton-block--cards \.skeleton-item \{[^}]*animation: none;/)
  assert.match(block, /\.skeleton-block--cards \.skeleton-item::before \{[^}]*animation: skeleton-pulse /)
})

test('Academic and Job Search empty slots use the shared block', async () => {
  const lines = {
    'components/CanvasCalendarPanel.tsx': 'Nothing due in the next three weeks.',
    'components/TermPlanner.tsx': 'No terms on record yet.',
    'components/CourseDiscoveryPanel.tsx': 'No verified course recommendations found from the current evidence.',
    'components/DegreeSchedulePanel.tsx': 'No deterministic courses currently need scheduling.',
    'components/DegreeScheduleYears.tsx': 'No academic years on record or scheduled yet.',
    'pages/AuthenticatedDashboard.tsx': 'No in-progress coursework on record.',
  }
  for (const [path, line] of Object.entries(lines)) {
    const source = await read(path)
    const at = source.indexOf(line)
    assert.ok(at > 0, `${path}: ${line}`)
    const opener = source.lastIndexOf('<EmptyState', at)
    assert.ok(opener > 0 && !source.slice(opener, at).includes('</EmptyState>'), `${path}: ${line}`)
    assert.match(source.slice(opener, at), /icon="[a-z]+"/, `${path}: ${line}`)
  }
})

test('Academic Overview marks in-progress courses with the shared badge and pairs its shortcuts', async () => {
  const dashboard = await read('pages/AuthenticatedDashboard.tsx')
  const overview = dashboard.slice(dashboard.indexOf('Academic Overview</h2>'), dashboard.indexOf('GPA Calculator</h2>'))
  assert.match(overview, /<span className="degree-schedule-badge degree-schedule-badge--in-progress">In progress<\/span>/)
  const shortcuts = overview.slice(overview.indexOf('className="academic-overview-shortcuts"'))
  assert.ok(shortcuts.indexOf('academic-overview-course-discovery') < shortcuts.indexOf('academic-overview-grade-calculator'))
})

test('job cards lead with an employer mark and keep the posting link on the card', async () => {
  const panel = await read('components/JobSearchPanel.tsx')
  const card = panel.slice(panel.indexOf('function JobCardView'))
  const mark = card.indexOf('className="job-card-mark"')
  const body = card.indexOf('className="job-card-body"')
  const link = card.indexOf('View posting')
  assert.ok(mark > 0 && mark < body && body < link)
  assert.match(card, /className="job-card-mark" aria-hidden="true"/)
  // A legal suffix is not the employer's name.
  assert.match(panel, /LEGAL_SUFFIXES = new Set\(\[[^\]]*'inc'/)
})
