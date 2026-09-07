import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const YEARS = new URL('../src/components/DegreeScheduleYears.tsx', import.meta.url)
const SEARCH = new URL('../src/components/CourseSearchAdd.tsx', import.meta.url)
const DIALOG = new URL('../src/components/EditCoursesDialog.tsx', import.meta.url)
const TERM_PLANNER = new URL('../src/components/TermPlanner.tsx', import.meta.url)
const CSS = new URL('../src/index.css', import.meta.url)

test('CourseSearchAdd is shared, not reinvented: TermPlanner delegates its search to it', async () => {
  const [planner, search] = await Promise.all([readFile(TERM_PLANNER, 'utf8'), readFile(SEARCH, 'utf8')])
  // The debounce + catalog search moved into the shared component.
  assert.match(search, /SEARCH_DEBOUNCE_MS/)
  assert.match(search, /searchCatalog\(identity/)
  assert.match(planner, /import \{ CourseSearchAdd \} from '\.\/CourseSearchAdd'/)
  assert.match(planner, /<CourseSearchAdd/)
  // TermPlanner no longer carries its own copy of the search machinery.
  assert.doesNotMatch(planner, /searchCatalog/)
  assert.doesNotMatch(planner, /SEARCH_DEBOUNCE_MS/)
  // Its activation notice still rides along, as the hint slot.
  assert.match(planner, /hint=\{willActivateOnAdd/)
})

test('year view: the future term card mounts the Edit-courses popup, gated on state === future', async () => {
  const years = await readFile(YEARS, 'utf8')
  // The search box no longer lives on the card -- it moved into the popup.
  assert.doesNotMatch(years, /<CourseSearchAdd/)
  assert.match(years, /import \{ EditCoursesDialog \} from '\.\/EditCoursesDialog'/)
  // The popup is mounted only inside the state === 'future' branch.
  const futureBranch = years.slice(years.indexOf("semester.state === 'future'"))
  assert.match(futureBranch, /<EditCoursesDialog/)
  assert.doesNotMatch(
    years.slice(0, years.indexOf("semester.state === 'future'")),
    /<EditCoursesDialog/,
  )
  // The trigger that opens it.
  assert.match(futureBranch, /Edit courses/)
  assert.match(futureBranch, /aria-haspopup="dialog"/)
})

test('the term card no longer renders the "If you have room" suggested-course section', async () => {
  const years = await readFile(YEARS, 'utf8')
  // The whole elective block relocated into EditCoursesDialog.
  assert.doesNotMatch(years, /degree-schedule-suggested--elective/)
  assert.doesNotMatch(years, /If you have room/)
  assert.doesNotMatch(years, /semester\.suggestedCourses\.map/)
  // It is handed to the popup instead.
  assert.match(years, /suggestedCourses=\{semester\.suggestedCourses\}/)
})

test('the card empty-state keys on planned + decisions only, not on (now hidden) suggestions', async () => {
  const years = await readFile(YEARS, 'utf8')
  assert.match(
    years,
    /semester\.planned\.length === 0 && semester\.decisions\.length === 0 && \(\s*<p className="empty-state">No courses confirmed yet\.<\/p>/,
  )
  // suggestedCourses must not gate the empty-state any more.
  assert.doesNotMatch(years, /semester\.suggestedCourses\.length === 0 && semester\.decisions\.length === 0/)
})

test('EditCoursesDialog renders "If you have room" read-only, below the search box', async () => {
  const dialog = await readFile(DIALOG, 'utf8')
  assert.match(dialog, /suggestedCourses: DegreeScheduleSuggestedCourse\[\]/)
  assert.match(dialog, /degree-schedule-suggested--elective/)
  assert.match(dialog, /<h6>If you have room<\/h6>/)
  // Read-only: the elective block carries no onClick and no button.
  const block = dialog.slice(dialog.indexOf('degree-schedule-suggested--elective'), dialog.indexOf('degree-schedule-edit-footer'))
  assert.doesNotMatch(block, /onClick|<button/)
  // Ordering: elective block sits after the "Plan a course" search box.
  assert.ok(
    dialog.indexOf('degree-schedule-suggested--elective') > dialog.indexOf('<CourseSearchAdd'),
  )
})

test('year view: the add write still opts out of activation promotion and hits the planned route', async () => {
  const years = await readFile(YEARS, 'utf8')
  // handleAddPlanned is unchanged -- the popup just calls it.
  assert.match(years, /force_planned: true/)
  assert.match(years, /addPlannedCourse\(identity/)
})

test('the Edit-courses popup owns the search box and the removable planned list', async () => {
  const dialog = await readFile(DIALOG, 'utf8')
  assert.match(dialog, /import \{ CourseSearchAdd \} from '\.\/CourseSearchAdd'/)
  assert.match(dialog, /<CourseSearchAdd/)
  // The Remove button moved here from the card, behaviour unchanged: it still
  // calls the parent's onRemove immediately (no staging).
  assert.match(dialog, /onClick=\{\(\) => onRemove\(course\.id\)\}/)
  assert.match(dialog, /aria-label=\{`Remove \$\{course\.course_code\} from your plan`\}/)
  // "Confirm" is a close-only action -- it calls onClose, it does not submit.
  assert.match(dialog, /onClick=\{onClose\}>\s*Confirm/)
  assert.doesNotMatch(dialog, /addPlannedCourse|removePlannedCourse|fetch\(/)
})

test('the Edit-courses popup meets the dialog a11y bar: role, modal, focus-in, Escape-out', async () => {
  const dialog = await readFile(DIALOG, 'utf8')
  assert.match(dialog, /role="dialog"/)
  assert.match(dialog, /aria-modal="true"/)
  assert.match(dialog, /aria-labelledby=\{titleId\}/)
  // Focus moves into the panel on open (same pattern as GuidedTour's cardRef).
  assert.match(dialog, /dialogRef\.current\?\.focus\(\)/)
  // Escape closes it.
  assert.match(dialog, /event\.key === 'Escape'\) onClose\(\)/)
  assert.match(dialog, /addEventListener\('keydown'/)
  assert.match(dialog, /removeEventListener\('keydown'/)
})

test('closing the popup returns focus to the trigger; only one popup opens at a time', async () => {
  const years = await readFile(YEARS, 'utf8')
  // A single string of state is the whole single-popup guarantee.
  assert.match(years, /const \[editingTermKey, setEditingTermKey\] = useState<string \| null>\(null\)/)
  assert.match(years, /isEditOpen=\{editingTermKey === semester\.termKey\}/)
  assert.match(years, /onOpenEdit=\{\(\) => setEditingTermKey\(semester\.termKey\)\}/)
  // Switching year tabs also dismisses any open popup.
  assert.match(years, /setActiveYearKey\(year\.yearKey\); setEditingTermKey\(null\)/)
  // The close path refocuses the trigger button (covers both Confirm and Escape).
  assert.match(years, /editTriggerRef\.current\?\.focus\(\)/)
  assert.match(years, /ref=\{editTriggerRef\}/)
})

test('year view: card planned rows keep the Added badge but no longer carry an inline Remove', async () => {
  const years = await readFile(YEARS, 'utf8')
  // The read-only card summary keeps code / credits / "Added".
  assert.match(years, /degree-schedule-badge--added">Added</)
  // The Remove button and its handler no longer live on the card.
  assert.doesNotMatch(years, /aria-label=\{`Remove \$\{course\.course_code\} from your plan`\}/)
  assert.doesNotMatch(years, /onClick=\{\(\) => onRemove\(course\.id\)\}/)
  // handleRemovePlanned itself is unchanged and still passed down for the popup.
  assert.match(years, /removePlannedCourse\(identity, id\)/)
  assert.match(years, /Promise\.all\(\[loadPlanned\(\), loadTerms\(\)\]\)/)
})

test('the Added badge is defined in the filled-tint family, achromatic (neutral), distinct from gold/green', async () => {
  const css = await readFile(CSS, 'utf8')
  const block = css.slice(css.indexOf('.degree-schedule-badge--added'))
  assert.match(block.slice(0, 160), /color: var\(--pending\)/)
  assert.match(block.slice(0, 160), /background: var\(--pending-tint\)/)
})

test('a decision-option course row uses the exact .degree-schedule-course-row shape, badge stacked below', async () => {
  const years = await readFile(YEARS, 'utf8')
  // The per-course row markup lives in the shared CandidateCourseRows helper
  // now -- reused by DecisionCandidatePath's "Option N" box and a LOCKED
  // card's boxless course list alike -- rather than being inlined at each
  // .degree-schedule-candidate-courses call site.
  const path = years.slice(years.indexOf('function CandidateCourseRows'))
  // Same row div as the Fall / planned lists: code+title span, then credits span.
  assert.match(path, /<div className="degree-schedule-course-row">\s*<span>\s*<strong>\{course\.course_code\}<\/strong>\s*\{course\.title && <small>\{course\.title\}<\/small>\}\s*<\/span>/)
  // Real credits by default; the fallback is the genuine-exception path.
  assert.match(path, /course\.credits !== null \? `\$\{course\.credits\} credits` : 'Credits unavailable'/)
  // The badge is a SIBLING of the row div now, not nested inside it.
  assert.match(path, /<\/div>\s*\{\/\*[\s\S]*?\*\/\}\s*<span className="degree-schedule-badge degree-schedule-badge--decision">Planned course<\/span>\s*<\/li>/)
})

test('decision-option rows resolve the "Planned course" badge to --accent, not the muted row default', async () => {
  const css = await readFile(CSS, 'utf8')
  // The <li> dropped out of the shared flex rule and is a plain block now,
  // so the row div's own flex does the layout (matching the Fall list).
  assert.doesNotMatch(css, /\.degree-schedule-candidate-courses > li \{\s*display: flex/)
  const liBlock = css.slice(css.indexOf('.degree-schedule-candidate-courses > li {'))
  assert.match(liBlock.slice(0, 60), /display: block/)
  // Fourth badge state: --accent / --accent-tint, distinct from --added's
  // --pending, --grade's --ready, --in-progress's --gold. The two-class
  // selector keeps it ahead of the base badge font-size and any inherited
  // row colour now that it sits as a bare `> li > span`.
  const badge = css.slice(css.indexOf('.degree-schedule-candidate-courses .degree-schedule-badge--decision'))
  assert.match(badge.slice(0, 200), /color: var\(--accent\)/)
  assert.match(badge.slice(0, 200), /background: var\(--accent-tint\)/)
  assert.match(badge.slice(0, 200), /font-size: var\(--text-xs\)/)
})

// ── cross-listing-aware duplicate detection in the add-course search ───────

test('CourseSearchAdd computes a cross-listed match only when the exact code is not already added', async () => {
  const search = await readFile(SEARCH, 'utf8')
  assert.match(search, /import \{[\s\S]*?findCrossListedMatch[\s\S]*?\} from '\.\.\/lib\/termPlanning\.mjs'/)
  // Gated on !isAdded: an identical code keeps the existing "Planned"
  // treatment untouched, this check only covers the alias case.
  assert.match(
    search,
    /const crossListedMatch = !isAdded && existingCourseIndex\s*\n\s*\? findCrossListedMatch\(result\.code, crossListings, existingCourseIndex\)\s*\n\s*: null;/,
  )
})

test('CourseSearchAdd shows a specific note and disables Add for a cross-listed match, without touching the exact-match "Planned" case', async () => {
  const search = await readFile(SEARCH, 'utf8')
  // The note names the matched code and its status -- not a silent disable.
  assert.match(
    search,
    /\{`Already \$\{STATUS_PHRASE\[crossListedMatch\.status\]\} as \$\{crossListedMatch\.code\}\.`\}/,
  )
  assert.match(search, /className="term-search-result-note"/)
  // Both isAdded and a cross-listed match disable Add; only isAdded keeps
  // the pre-existing "Planned" button label.
  assert.match(search, /disabled=\{isBlocked \|\| busyCode === result\.code\}/)
  assert.match(
    search,
    /isAdded \? 'Planned' : crossListedMatch \? 'Added' : busyCode === result\.code \? 'Adding…' : 'Add'/,
  )
})

test('EditCoursesDialog and TermPlanner both thread crossListings/existingCourseIndex through to CourseSearchAdd', async () => {
  const [dialog, planner] = await Promise.all([readFile(DIALOG, 'utf8'), readFile(TERM_PLANNER, 'utf8')])
  for (const source of [dialog, planner]) {
    assert.match(source, /crossListings=\{crossListings\}/)
    assert.match(source, /existingCourseIndex=\{existingCourseIndex\}/)
  }
})

test('DegreeScheduleYears fetches cross-listings once and feeds the same student-wide index to every term column', async () => {
  const years = await readFile(YEARS, 'utf8')
  assert.match(years, /fetchCrossListings\(identity\)/)
  assert.match(years, /existingCourseStatusIndex\(courses, planned\)/)
  // Also threaded into buildDegreeScheduleYears, for the suggested-vs-planned
  // reconciliation (Part 4) -- not just the add-time check (Part 2).
  assert.match(years, /crossListings,\s*\n\s*\}\),/)
})
