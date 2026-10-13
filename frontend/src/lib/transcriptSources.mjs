// Where a student downloads their unofficial transcript, per school. Shown on
// the upload screen so "go find your transcript" is a link and three steps
// rather than a scavenger hunt. Steps are taken from each registrar's own
// help page (linked in `source`); re-check them if a portal is redesigned.
// transcriptSources.test.mjs pins the lookup.

const SOURCES = [
  {
    match: /texas a&m|texas a & m|\btamu\b/i,
    portalName: 'Howdy',
    portalUrl: 'https://howdy.tamu.edu',
    steps: [
      'Sign in to Howdy',
      'Open My Record, then Academic Record',
      'Choose the unofficial transcript as a PDF and save it',
    ],
    source: 'https://aggie.tamu.edu/academic-records/order-transcripts/index.html',
  },
  {
    match: /southern methodist|\bsmu\b/i,
    portalName: 'my.SMU',
    portalUrl: 'https://my.smu.edu',
    steps: [
      'Sign in to my.SMU and open your Student Homepage',
      'Click Academic Records, then View Unofficial Transcript, then Go',
      'Save the page as a PDF (Print, then Save as PDF)',
    ],
    source: 'https://smu.edu/EnrollmentServices/registrar/TranscriptRequests/UnofficialTranscripts',
  },
]

export const GENERIC_TRANSCRIPT_STEPS = [
  "Sign in to your school's student portal",
  'Find the unofficial transcript under academic records',
  'Download or print it to PDF',
]

export function transcriptSourceFor(institutionName) {
  if (typeof institutionName !== 'string' || !institutionName.trim()) return null
  const found = SOURCES.find((entry) => entry.match.test(institutionName))
  if (!found) return null
  const { match: _match, ...rest } = found
  return rest
}

// Accepted by the upload route: PDF and Word. Checked on drop because a drop
// bypasses the file input's `accept` filter.
export function isAcceptedTranscriptFile(name) {
  return typeof name === 'string' && /\.(pdf|docx)$/i.test(name.trim())
}
