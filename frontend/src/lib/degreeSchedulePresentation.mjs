import { isSkippedDegreeSchedule } from '../api/degreeSchedule.mjs';

export function displayTermKey(termKey) {
  const match = /^(\d{4})-(Fall|Spring)$/.exec(termKey);
  return match ? `${match[2]} ${match[1]}` : termKey;
}

export function formatCredits(value) {
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} credit${value === 1 ? '' : 's'}`;
}

// The backend order is authoritative. This helper deliberately maps without
// sorting so presentation tests can lock that contract down.
export function termPresentation(terms) {
  return terms.map((term) => ({
    ...term,
    displayName: displayTermKey(term.term_key),
    totalLabel: formatCredits(term.total_credit_hours),
  }));
}

export function degreeScheduleContentState(result) {
  if (isSkippedDegreeSchedule(result)) return 'skipped';
  if (result.status === 'ERROR') return 'infeasible';
  return result.terms.length === 0 ? 'empty' : 'scheduled';
}

export function nextPlannedTerm(schedule) {
  if (!schedule || isSkippedDegreeSchedule(schedule) || schedule.status !== 'SCHEDULED') return null;
  return termPresentation(schedule.terms)[0] ?? null;
}

// Phase 3 retired buildDegreeScheduleDecisions and adviserReviewCount: the
// separate "Decisions needed" / "Your academic choices" section is gone, its
// LOCKED/CHOICE_REQUIRED/EXCLUDED cards now live on the term they resolve to
// (see degreeScheduleYears.mjs::bucketDecisionsByTerm), and ADVISER_REVIEW /
// DATA_UNRESOLVED / freeform-manual-review requirements are no longer
// surfaced in the planner UI at all -- not as a card, a list, or a count.
