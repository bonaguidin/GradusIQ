// Pure helpers for the bug / feature report pop-up (components/
// ReportIssueDialog.tsx). The backend route is GradusIQ_career/api.py's
// POST /api/v2/student/me/feedback, which emails the team inbox; the limits
// below sit just under the backend's own (feedback/report.py) so a report the
// form accepts is never one the server rejects for size.
// reportIssue.test.mjs pins these.

export const REPORT_URL = '/api/v2/student/me/feedback'

export const REPORT_LIMITS = Object.freeze({
  maxScreenshots: 3,
  // Backend caps are 1.5 MB each and 3.5 MB total. Vercel refuses request
  // bodies over 4.5 MB before they reach the backend at all.
  maxScreenshotBytes: 1_400_000,
  maxTotalBytes: 3_400_000,
  // Longest side a screenshot is scaled down to before upload.
  maxImageDimension: 1600,
  minDescription: 10,
  maxDescription: 5000,
})

export const REPORT_KINDS = Object.freeze([
  { value: 'bug', label: 'Something is broken' },
  { value: 'feature', label: 'I have an idea' },
])

const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

/** Field-level messages for the form; an empty object means it can be sent. */
export function validateReport({ description, email }) {
  const errors = {}
  const text = (description ?? '').trim()
  if (text.length < REPORT_LIMITS.minDescription) {
    errors.description = 'Tell us a little more so we can act on it.'
  } else if (text.length > REPORT_LIMITS.maxDescription) {
    errors.description = `Keep it under ${REPORT_LIMITS.maxDescription.toLocaleString('en-US')} characters.`
  }
  if (!EMAIL_PATTERN.test((email ?? '').trim())) {
    errors.email = 'Enter an email we can reply to.'
  }
  return errors
}

/** Whether one more image of `size` bytes fits next to the ones already attached. */
export function screenshotFits(existingSizes, size) {
  if (existingSizes.length >= REPORT_LIMITS.maxScreenshots) return 'count'
  if (size > REPORT_LIMITS.maxScreenshotBytes) return 'size'
  const total = existingSizes.reduce((sum, n) => sum + n, 0) + size
  if (total > REPORT_LIMITS.maxTotalBytes) return 'total'
  return 'ok'
}

/** Scaled dimensions that keep the aspect ratio and fit maxImageDimension. */
export function fitWithin(width, height, max = REPORT_LIMITS.maxImageDimension) {
  const longest = Math.max(width, height)
  if (longest <= max) return { width, height }
  const scale = max / longest
  return { width: Math.round(width * scale), height: Math.round(height * scale) }
}

/**
 * The multipart body. `website` is the hidden honeypot field: always sent,
 * normally empty. `screenshots` is a list of { blob, name }.
 */
export function buildReportFormData(fields, screenshots = []) {
  const form = new FormData()
  form.set('kind', fields.kind)
  form.set('description', fields.description.trim())
  form.set('email', fields.email.trim())
  if (fields.name && fields.name.trim()) form.set('name', fields.name.trim())
  if (fields.page) form.set('page', fields.page)
  if (fields.userAgent) form.set('user_agent', fields.userAgent)
  form.set('website', fields.website ?? '')
  for (const shot of screenshots) form.append('screenshots', shot.blob, shot.name)
  return form
}

export function normalizeReportResponse(status, body) {
  if (status === 200) return { ok: true }
  const detail = body && typeof body === 'object' && typeof body.detail === 'string' ? body.detail : null
  if (status === 0) {
    return { ok: false, message: "We couldn't reach GradusIQ. Check your connection and try again." }
  }
  if (status === 413) {
    return { ok: false, message: 'Those screenshots are too large together. Remove one and try again.' }
  }
  if (status === 422 || status === 429 || status === 503 || status === 502) {
    return { ok: false, message: detail ?? 'Something went wrong sending your report. Please try again.' }
  }
  return { ok: false, message: 'Something went wrong sending your report. Please try again.' }
}
