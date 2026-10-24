// Which page the student has open, as the assistant chat names it.
//
// The key travels with every chat message so the backend can tell the model
// where the student is ("what am I looking at?"). Keys are a fixed set that
// the backend checks against the same list (CHAT_PAGE_LABELS in api.py); an
// unknown page is simply not sent.

const SECTIONS = ['overview', 'academic', 'career']
const ACADEMIC_TABS = ['gpa-calculator', 'grade-calculator', 'course-discovery']
const CAREER_TABS = ['intelligence', 'job-search', 'profile']

const ROUTE_KEYS = {
  '/transcript': 'transcript',
  '/resume': 'resume',
  '/profile/complete': 'profile-complete',
}

/**
 * @param {string} pathname
 * @param {URLSearchParams} params
 * @param {string} [dashboardPath] where the dashboard is mounted; the preview
 *   harness serves it from its own .html path
 * @returns {string | null}
 */
export function chatPageKey(pathname, params, dashboardPath = '/dashboard') {
  if (pathname in ROUTE_KEYS) return ROUTE_KEYS[pathname]
  if (pathname !== dashboardPath) return null
  const section = params.get('section')
  if (!section || !SECTIONS.includes(section) || section === 'overview') return 'overview'
  const tab = params.get(section)
  const tabs = section === 'academic' ? ACADEMIC_TABS : CAREER_TABS
  return tab && tabs.includes(tab) ? `${section}/${tab}` : section
}

const OVERVIEW = [
  'What are my biggest skill gaps for my target roles?',
  'Which courses should I prioritize next term?',
  'How ready am I for an internship right now?',
]

const ACADEMIC = [
  'How is my GPA trending?',
  'What do I have due in the next two weeks?',
  'Which degree requirements do I still need?',
]

const CAREER = [
  'What are my biggest skill gaps for my target roles?',
  'Which of my target roles fits me best right now?',
  'What should I add to my resume next?',
]

const PROFILE = [
  'Why does GradusIQ ask for these details?',
  'Which details matter most for my analyses?',
  'Can I change these later?',
]

const UPLOADS = [
  'What file types can I upload?',
  'What happens after I upload?',
  'What if something on it is read wrong?',
]

/**
 * Starter questions for the empty chat, matched to the page.
 * @param {string | null} key
 * @returns {string[]}
 */
export function chatSuggestions(key) {
  if (!key || key === 'overview') return OVERVIEW
  if (key.startsWith('academic')) return ACADEMIC
  if (key.startsWith('career')) return CAREER
  if (key === 'profile-complete') return PROFILE
  return UPLOADS
}
