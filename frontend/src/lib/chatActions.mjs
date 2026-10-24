// Action buttons under assistant replies (chat overhaul, Phase 3).
//
// The backend only ever returns ids from this list (CHAT_ACTIONS in
// GradusIQ_career/ai/chat_actions.py; a test checks the two match). Each id's
// label and destination live here, so the model can point at a page but
// never write a URL of its own.
//
// `to` is a path, or a dashboard query when `dashboard` is set (the preview
// harness mounts the dashboard somewhere other than /dashboard). `scrollTo`
// is a selector to bring into view once the page is there; `dialog` names a
// pop-up to open instead of navigating.

/** @typedef {{ label: string, to?: string, dashboard?: string, scrollTo?: string, dialog?: 'report-issue', accountOnly?: boolean }} ChatAction */

/** @type {Record<string, ChatAction>} */
export const CHAT_ACTIONS = {
  'gpa-calculator': { label: 'Open GPA Calculator', dashboard: 'section=academic&academic=gpa-calculator' },
  'grade-calculator': { label: 'Open Grade Calculator', dashboard: 'section=academic&academic=grade-calculator' },
  'course-discovery': { label: 'Open Course Discovery', dashboard: 'section=academic&academic=course-discovery' },
  'degree-progress': { label: 'See degree progress', dashboard: 'section=academic' },
  'career-intelligence': { label: 'Open Career Intelligence', dashboard: 'section=career&career=intelligence' },
  'job-search': { label: 'Open Job Search', dashboard: 'section=career&career=job-search' },
  'career-profile': { label: 'Edit Career Profile', dashboard: 'section=career&career=profile' },
  'transcript': { label: 'Upload transcript', to: '/transcript', accountOnly: true },
  'resume': { label: 'Upload resume', to: '/resume', accountOnly: true },
  'canvas-calendar': {
    label: 'Connect Canvas calendar',
    dashboard: 'section=academic',
    scrollTo: '.academic-overview-canvas-calendar',
    accountOnly: true,
  },
  'report-issue': { label: 'Report a bug', dialog: 'report-issue' },
}

export const MAX_CHAT_ACTIONS = 3

/**
 * The ids worth drawing: known, not repeated, and available to this kind of
 * account (demo personas have no transcript, resume or Canvas pages).
 * @param {unknown} ids
 * @param {{ demo: boolean }} who
 * @returns {string[]}
 */
export function usableActions(ids, { demo }) {
  if (!Array.isArray(ids)) return []
  /** @type {string[]} */
  const out = []
  for (const id of ids) {
    if (typeof id !== 'string' || !Object.hasOwn(CHAT_ACTIONS, id) || out.includes(id)) continue
    if (demo && CHAT_ACTIONS[id].accountOnly) continue
    out.push(id)
  }
  return out.slice(0, MAX_CHAT_ACTIONS)
}
