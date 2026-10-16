/**
 * Decides which degree requirements get the Overview's "requirement done"
 * celebration (components/RequirementCelebration.tsx).
 *
 * ONCE PER REQUIREMENT, EVER. The ids already celebrated are remembered, and a
 * requirement that drops back out (a course removed) and is satisfied again
 * does not replay: the set only grows. The tour reopening on every login was
 * the lesson here -- a "moment" that repeats stops being one.
 *
 * FIRST SIGHT IS SILENT. With nothing remembered yet (a new browser, or the
 * first load after this shipped) everything already satisfied is recorded
 * without a burst. Otherwise every existing student would get a fireworks
 * show for requirements they finished semesters ago, and a second device
 * would replay all of them.
 *
 * Leaves only, matching the ring (requirementProgress.mjs): compound groups
 * are containers, so "3 of 8" in the message means the same thing as the
 * ring beside it.
 */

const STORAGE_PREFIX = 'gradusiq:celebrated-requirements:'

/** localStorage key for one student's celebrated requirement ids. */
export function celebrationStorageKey(studentId) {
  return `${STORAGE_PREFIX}${studentId}`
}

/** Satisfied leaf requirements, in tree order, as { id, name }. */
export function satisfiedLeafRequirements(groups) {
  const found = []
  function walk(group) {
    const children = Array.isArray(group.children) ? group.children : []
    if (children.length === 0) {
      if (group.status === 'SATISFIED') found.push({ id: group.id, name: group.name })
      return
    }
    for (const child of children) walk(child)
  }
  for (const group of Array.isArray(groups) ? groups : []) walk(group)
  return found
}

/** Reads the remembered ids; null when nothing (or nothing readable) is stored. */
export function parseCelebrated(raw) {
  if (typeof raw !== 'string') return null
  try {
    const value = JSON.parse(raw)
    return Array.isArray(value) ? value.filter((id) => typeof id === 'string') : null
  } catch {
    return null
  }
}

/**
 * `celebrated` is the remembered id list (null when none), `satisfied` the
 * current satisfied leaves. Returns the requirements to celebrate now and the
 * id list to remember afterwards.
 */
export function planCelebration(celebrated, satisfied) {
  const ids = satisfied.map((leaf) => leaf.id)
  if (celebrated === null) return { fresh: [], remember: ids }
  const known = new Set(celebrated)
  const fresh = satisfied.filter((leaf) => !known.has(leaf.id))
  return { fresh, remember: [...celebrated, ...fresh.map((leaf) => leaf.id)] }
}

/** "Core Math", "Core Math and Writing", "Core Math, Writing and 2 more". */
function nameList(names) {
  if (names.length === 1) return names[0]
  if (names.length === 2) return `${names[0]} and ${names[1]}`
  return `${names[0]}, ${names[1]} and ${String(names.length - 2)} more`
}

/** The one line under the burst. */
export function celebrationMessage(fresh, { satisfied, total }) {
  const done = `${nameList(fresh.map((leaf) => leaf.name))} done.`
  if (total > 0 && satisfied >= total) return `${done} Every requirement is satisfied.`
  return `${done} ${String(satisfied)} of ${String(total)} requirements complete.`
}
