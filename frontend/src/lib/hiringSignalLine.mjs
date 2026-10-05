/**
 * Pure text/state decision for FIT's hiring_signal bullet (see fit.py's
 * _hiring_signal_by_role -- coverage is "available" | "no_market_data" |
 * "unavailable", employers is capped at 3 and deduped by normalized key).
 * Kept separate from RoleMatchCard's JSX so the three coverage states are
 * testable without a DOM/rendering harness, matching how careerReadinessCards
 * separates pick logic from its card's JSX.
 *
 * Returns null when nothing should render: hiring_signal is absent (older
 * cached/demo results predate this field), coverage is "unavailable" (skip
 * the bullet entirely per the prompt's own rule), or coverage is "available"
 * with no named employers (nothing to say).
 */
export function hiringSignalLine(hiringSignal) {
  if (!hiringSignal) {
    return null
  }

  if (hiringSignal.coverage === 'unavailable') {
    return null
  }

  if (hiringSignal.coverage === 'no_market_data') {
    return { variant: 'empty', text: 'No posting data found for this role.' }
  }

  const employers = Array.isArray(hiringSignal.employers) ? hiringSignal.employers : []
  if (employers.length === 0) {
    return null
  }

  const employerList = employers.join(', ')
  const count = hiringSignal.posting_count
  const countLabel = typeof count === 'number' ? ` (${count} listing${count === 1 ? '' : 's'})` : ''

  return { variant: 'signal', text: `Hiring now: ${employerList}${countLabel}` }
}
