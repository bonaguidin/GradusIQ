import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchPlannedCourses, fetchTerms } from '../api/planning';
import type { PlannedCourse, PlanningTerm } from '../lib/termPlanning.mjs';
import type { AcademicCourse } from '../types/studentIntelligenceProfile';
import { GradeCard } from './GradeCard';
import {
  SyllabusApiError,
  calculateSyllabusGrade,
  confirmSyllabusGradeModel,
  deleteSyllabusGradeProfile,
  getSyllabusGradeProfile,
  ingestSyllabus,
  listSyllabusGradeProfiles,
  saveSyllabusGradeState,
  submitSyllabusCorrections,
  type SyllabusCalculationResult,
  type SyllabusCategory,
  type SyllabusFinding,
  type SyllabusGradeModel,
  type SyllabusProfileDetail,
  type SyllabusProfileSummary,
  type SyllabusRule,
  type SyllabusThreshold,
} from '../api/syllabusGradeProfiles';

// How long after the last keystroke in a score field the live projection
// waits before recalculating. The projection is computed server-side (the
// rules engine, letter thresholds and effective-weight logic have no
// faithful client-side equivalent that wouldn't drift from the backend), so
// this debounces the `/calculate` call rather than firing one per keystroke.
const PROJECTION_DEBOUNCE_MS = 500;

// Presentation copy for machine-readable reconciliation finding codes. The
// code itself stays available (data-finding-code) for tests/telemetry; this
// mapping is the ONLY place backend codes turn into student-facing text.
//
// Codes handled below in FINDING_TEMPLATES are deliberately absent here:
// their backend `message` already carries the one distinguishing detail
// (which rule, which two letters, which category) that tells two findings
// of the same code apart, and this flat map has no way to say that.
const FINDING_COPY: Record<string, string> = {
  possible_curve: 'Your syllabus says grades may be curved, but it does not provide a formula.',
  unknown_weight: "We couldn't determine this category's weight.",
  unknown_assessment_count: "The syllabus doesn't say exactly how many assessments are in this category.",
  ambiguous_rule: "We found a grading rule, but couldn't determine exactly how it works.",
  category_weight_validation: 'The category weights in this syllabus may not add up to 100%.',
  grading_method_unknown: "We couldn't determine how this course is graded.",
  missing_claim_evidence: "We found this value, but couldn't confirm it against the syllabus text.",
  partial_claim_evidence: "We found this value, but couldn't confirm it against the syllabus text.",
  claim_evidence_value_mismatch: 'This value may not match what the syllabus actually says.',
  claim_evidence_consistency_unverifiable: "We couldn't automatically confirm this value against the syllabus text.",
  evidence_page_out_of_range: "This citation doesn't match the syllabus pages we reviewed.",
};

// Per-code templates that parse the backend's specific `message` (which
// already names the rule/letters/category involved) into short,
// friendly text -- instead of the one-generic-sentence-per-code approach
// above, which made every occurrence of a code read identically even when
// each one was about a different rule or a different pair of letters.
const FINDING_TEMPLATES: Record<string, (finding: SyllabusFinding) => string | null> = {
  non_deterministic_grading_rule: (finding) => {
    const m = /^(\S+) rule is not structured precisely enough to apply deterministically: (.*)$/.exec(finding.message);
    if (!m) return null;
    const label = ruleTypeLabel(m[1] as SyllabusRule['rule_type']).toLowerCase();
    return `CampusIQ can't calculate this ${label} rule automatically: ${m[2]}`;
  },
  overlapping_grade_thresholds: (finding) => {
    const m = /^thresholds '(.+?)' \(([\d.]+)-([\d.]+)\) and '(.+?)' \(([\d.]+)-([\d.]+)\) overlap$/.exec(finding.message);
    if (!m) return null;
    return `Letter grades ${m[1]} and ${m[4]} have overlapping cutoffs: ${m[1]} is ${m[2]}–${m[3]}, ${m[4]} is ${m[5]}–${m[6]}.`;
  },
  grade_threshold_ordering_anomaly: (finding) => {
    const m = /^threshold '(.+?)' has a lower minimum \(([\d.]+)\) than the generally-lower grade '(.+?)' \(([\d.]+)\)$/.exec(finding.message);
    if (!m) return null;
    return `${m[1]} (${m[2]}) has a lower cutoff than ${m[3]} (${m[4]}), which is usually the lower grade.`;
  },
  unresolved_rule_reference: (finding) => {
    const m = /^rule (?:source|target)='(.+?)' does not match any known category or assessment$/.exec(finding.message);
    if (!m) return null;
    return `A grading rule references "${m[1]}", but CampusIQ couldn't match it to a category or assessment.`;
  },
  unresolved_assessment_category_reference: (finding) => {
    const m = /^assessment '(.+?)' references category '(.+?)', which is not a known category$/.exec(finding.message);
    if (!m) return null;
    return `"${m[1]}" references a category ("${m[2]}") CampusIQ couldn't find in this syllabus.`;
  },
  duplicate_category: (finding) => {
    if (!finding.field) return null;
    return `Multiple categories may be the same ("${finding.field}") — check for a duplicate.`;
  },
  duplicate_assessment: (finding) => {
    if (!finding.field) return null;
    return `Multiple assessments may be the same ("${finding.field.split(':')[0]}") — check for a duplicate.`;
  },
  // Category-weight mismatches only (field "category:<name>.weight") --
  // threshold/assessment mismatches never reach findingCopy() for this code
  // (CutoffTable renders its own inline copy instead), so returning null for
  // any other field shape falls through to the generic FINDING_COPY entry,
  // unaffected. Unlike the threshold case, a category mismatch is never
  // affirmable (reconciliation._check_category_weight_consistency), so the
  // copy says so plainly rather than implying a fix is one click away.
  claim_evidence_value_mismatch: (finding) => {
    if (!finding.field?.startsWith('category:')) return null;
    const m = /^category:.+\.weight claims ([\d.]+), but its cited evidence text \('(.*)'\) states ([\d.]+)$/.exec(
      finding.message,
    );
    if (!m) return null;
    return `You entered ${Number(m[1])}%, but the syllabus text ("${m[2]}") says ${Number(m[3])}%. Fix the weight below — this can't be confirmed as-is.`;
  },
};

function findingCopy(finding: SyllabusFinding): string {
  const templated = FINDING_TEMPLATES[finding.code]?.(finding);
  if (templated) return templated;
  return FINDING_COPY[finding.code] ?? finding.message;
}

// Mirrors the backend's _normalize_name (reconciliation.py): lowercase,
// collapsed whitespace. Findings whose `field` is a normalized name
// (duplicate_category) are matched against category rows through this.
function normalizeName(name: string): string {
  return name.toLowerCase().split(/\s+/).filter(Boolean).join(' ');
}

type FindingWithKey = { finding: SyllabusFinding; key: number };

/**
 * Groups findings by where they should render inline: next to the rule
 * card they're about (`rule:{index}`), next to the category row they're
 * about (`category:{name}`), or `general` as a fallback for every finding
 * whose `field` doesn't identify a row this panel currently renders
 * (course-level findings, threshold findings -- thresholds have no
 * dedicated row in the review step -- and evidence-coverage findings).
 * `key` is the finding's index in the source array, used as a stable,
 * session-only dismiss key (see dismissedFindingKeys in
 * GradeCalculatorPanel).
 */
function groupFindingsByAnchor(
  findings: SyllabusFinding[],
  model: SyllabusGradeModel | null,
): Map<string, FindingWithKey[]> {
  const map = new Map<string, FindingWithKey[]>();
  findings.forEach((finding, key) => {
    let anchor = 'general';
    if (finding.code === 'non_deterministic_grading_rule') {
      const m = /^rules\[(\d+)\]$/.exec(finding.field ?? '');
      if (m) anchor = `rule:${m[1]}`;
    } else if (finding.code === 'duplicate_category' && finding.field && model) {
      const match = model.categories.find((c) => normalizeName(c.name) === finding.field);
      if (match) anchor = `category:${match.name}`;
    }
    const bucket = map.get(anchor);
    if (bucket) bucket.push({ finding, key });
    else map.set(anchor, [{ finding, key }]);
  });
  return map;
}

function ruleTypeLabel(ruleType: SyllabusRule['rule_type']): string {
  switch (ruleType) {
    case 'replacement':
      return 'Score replacement';
    case 'drop':
      return 'Dropped score';
    case 'curve':
      return 'Curve';
    case 'extra_credit':
      return 'Extra credit';
    case 'late_work':
      return 'Late work';
    case 'makeup':
      return 'Makeup work';
    default:
      return 'Grading rule';
  }
}

function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${value}%`;
}

// Rule types that carry an informational grading policy -- a curve, a
// late-work / makeup rule, an extra-credit or catch-all "other" -- rather
// than a formula the calculator can execute. These feed the persistent
// "Professor's rules" panel next to the calculator. Deterministic
// replacement/drop rules are executed by the calculator itself and stay
// out of it; a malformed replacement/drop (missing source/target) is a
// broken deterministic rule, not a professor policy, so it's excluded too.
const PROFESSOR_RULE_TYPES: ReadonlySet<SyllabusRule['rule_type']> = new Set([
  'curve',
  'extra_credit',
  'late_work',
  'makeup',
  'other',
]);

// Reconciliation finding codes that became informational-only when PR #61
// moved them into NON_BLOCKING_WARNING_CODES: a correctly-extracted curve /
// late-work / makeup rule has no deterministic formula, but it's a fact to
// see while calculating, not an ambiguity to resolve. The backend still
// emits them for display; the calculator surfaces them in the Professor's
// rules panel, so they're filtered out of the "Needs your review" list.
const RULE_INFO_FINDING_CODES: ReadonlySet<string> = new Set([
  'non_deterministic_grading_rule',
  'possible_curve',
  'ambiguous_rule',
]);

// Other NON_BLOCKING_WARNING_CODES (reconciliation.py) that are purely
// informational and have no correction path -- they don't belong in the
// "Still needs your review" list. unknown_assessment_count in particular is
// moot since PR #64: the per-category count is never entered or displayed
// anymore (one average per category). NOT rule findings, so kept separate
// from RULE_INFO_FINDING_CODES.
const NON_BLOCKING_INFO_FINDING_CODES: ReadonlySet<string> = new Set([
  'unknown_assessment_count',
]);

// Findings relocated out of the review list because their explanation lives
// elsewhere in the UI. Unlike NON_BLOCKING_INFO_FINDING_CODES these are not
// moot.
//
// category_weight_validation / unknown_weight are relocated (not filtered
// like RULE_INFO/NON_BLOCKING_INFO) to the editable category-weight table
// (SyllabusGradingBreakdown's `editable` mode) as non-dismissible blocking
// notes -- both codes ARE still backend-blocking (neither is in
// reconciliation.py's NON_BLOCKING_WARNING_CODES), so they must never render
// with a dismiss affordance the way GeneralFindings gives every other
// relocated/general finding. CategoryWeightEditor reads them itself, straight
// from the raw (confirmed_reconciliation ?? reconciliation) findings -- same
// pattern CutoffTable already uses for CLAIM_EVIDENCE_THRESHOLD_CODES -- so
// removing them here only stops the dismissible copy, it does not stop them
// being shown.
//
// missing_grade_scale is deliberately NOT in this set: its only explainer was
// the Target Grade card (removed with the live-projection change), so it now
// flows through to the review list as a normal non-blocking finding.
const RELOCATED_FINDING_CODES: ReadonlySet<string> = new Set([
  'category_weight_validation',
  'unknown_weight',
]);

// Order-independent key for a letter pair, so an overlapping_grade_thresholds
// finding (field "B,C", threshold-list order) matches a cutoff_overlap_
// resolution entry ([winner, loser] order).
function cutoffPairKey(a: string, b: string): string {
  return [a.trim(), b.trim()].sort().join('|');
}

function clarifyingKey(winner: string, loser: string): string {
  return `cutoff_overlap:${winner},${loser}`;
}

// Pair keys for cleanly-resolvable overlaps: their raw
// overlapping_grade_thresholds finding is replaced by the CutoffTable's
// "higher grade wins" banner, so it's dropped from the review list (same
// idea as RULE_INFO_FINDING_CODES). Unresolved overlaps keep their raw
// finding.
function resolvedOverlapPairKeys(
  resolution: SyllabusProfileDetail['cutoff_overlap_resolution'] | undefined,
): Set<string> {
  const keys = new Set<string>();
  for (const r of resolution?.resolved ?? []) keys.add(cutoffPairKey(r.winner, r.loser));
  return keys;
}

function overlapFindingPair(finding: SyllabusFinding): [string, string] | null {
  const parts = (finding.field ?? '').split(',').map((s) => s.trim()).filter(Boolean);
  return parts.length === 2 ? [parts[0], parts[1]] : null;
}

// Per-threshold "we couldn't verify this value against the syllabus text"
// findings. Backend: reconciliation._check_threshold_range_consistency.
// A student affirms the extracted value ("Yes, that's correct") via a
// CONFIRM_THRESHOLD_VALUE correction, which suppresses the finding without
// touching the threshold or its evidence. Both are surfaced per-row in the
// unified CutoffTable, so the raw finding is dropped from the review list
// (see reviewFindings).
const CLAIM_EVIDENCE_THRESHOLD_CODES: ReadonlySet<string> = new Set([
  'claim_evidence_consistency_unverifiable',
  'claim_evidence_value_mismatch',
]);

function valueClaimKey(letter: string): string {
  return `claim_evidence:threshold:${letter.trim().toLowerCase()}`;
}

// "threshold:B" -> "B"; null for a finding whose field is any other shape.
// (category: claim-evidence findings have their own confirm path -- see
// categoryClaimEvidenceCategoryName / categoryValueClaimKey below --
// keyed separately from this one, never merged into it.)
function thresholdFindingLetter(finding: SyllabusFinding): string | null {
  const m = /^threshold:(.+)$/.exec(finding.field ?? '');
  return m ? m[1].trim() : null;
}

// Backend: reconciliation.py's confirmed_category_value_claims is a
// SEPARATE, narrower parameter from the threshold one (service.py:
// _confirmed_category_value_claim_names, api.py: _confirmed_suppression_sets'
// 'claim_evidence:category:' branch) -- it only suppresses
// claim_evidence_consistency_unverifiable, never claim_evidence_value_
// mismatch (reconciliation._check_category_weight_consistency). This mirrors
// that split on the frontend: a category weight claim is a distinct
// identifier space from a threshold letter, with its own clarifying-answer
// key namespace and its own (narrower) affirm eligibility.
function categoryValueClaimKey(name: string): string {
  return `claim_evidence:category:${normalizeName(name)}`;
}

// "category:Midterm Exam.weight" -> "Midterm Exam"; null for any other
// field shape (assessment:/threshold: claim-evidence findings use their
// own paths). Greedy on the name group so a category name that itself
// contains a literal ".weight" substring still resolves against the
// trailing ".weight" the backend always appends (reconciliation.py's
// `label = f"category:{category.name}.weight"`).
function categoryClaimEvidenceCategoryName(finding: SyllabusFinding): string | null {
  const m = /^category:(.+)\.weight$/.exec(finding.field ?? '');
  return m ? m[1].trim() : null;
}

function formatThresholdRange(t: SyllabusThreshold | null | undefined): string {
  if (!t) return '—';
  const lo = t.minimum ?? null;
  const hi = t.maximum ?? null;
  if (lo === null && hi === null) return '—';
  if (lo === null) return `up to ${hi}`;
  if (hi === null) return `${lo}+`;
  return `${lo}–${hi}`;
}

// The corrections a per-row cutoff edit submits: a set_minimum / set_maximum
// for every bound the student actually changed (the diff-and-emit the old
// ManualThresholdEditor did), plus -- for each letter touched -- a
// confirm_threshold_value so the student is never re-prompted to affirm a
// bound they just typed. The backend's _apply_confirm_threshold_value is a
// tolerated no-op when that edit left no residual claim-evidence finding,
// so the auto-appended affirmation never fails the atomic batch. Returns []
// when nothing changed.
function thresholdEditCorrections(
  letters: string[],
  thresholdOf: (letter: string) => SyllabusThreshold | null,
  draft: Record<string, string>,
): SyllabusProfileDetail['corrections'] {
  const setCorrections: SyllabusProfileDetail['corrections'] = [];
  const editedLetters: string[] = [];
  for (const letter of letters) {
    const t = thresholdOf(letter);
    let touched = false;
    for (const bound of ['minimum', 'maximum'] as const) {
      const raw = (draft[`${letter}:${bound}`] ?? '').trim();
      if (raw === '') continue;
      const value = Number(raw);
      if (Number.isNaN(value)) continue;
      const current = bound === 'minimum' ? t?.minimum : t?.maximum;
      if (current != null && current === value) continue;
      setCorrections.push({
        target_type: 'threshold',
        operation: bound === 'minimum' ? 'set_minimum' : 'set_maximum',
        threshold_letter: letter,
        value,
      });
      touched = true;
    }
    if (touched) editedLetters.push(letter);
  }
  if (setCorrections.length === 0) return [];
  return [
    ...setCorrections,
    ...editedLetters.map((letter) => ({
      target_type: 'threshold' as const,
      operation: 'confirm_threshold_value',
      threshold_letter: letter,
    })),
  ];
}

// The category-editor analog of thresholdEditCorrections: diffs a
// {name:weight, name:count} draft against each category's current values
// and emits only the existing category/set_weight + category/set_count
// corrections (corrections.py's _apply_category_correction already handles
// both) for fields the student actually touched. A blank field is never
// submitted as a clear-to-null -- same convention thresholdEditCorrections
// uses for blank bounds -- so leaving a field empty is a no-op, not a
// delete. No confirm-style no-op is auto-appended (unlike
// thresholdEditCorrections' confirm_threshold_value): there is no existing
// correction type that plays that role for categories, and this build adds
// none.
function categoryWeightEditCorrections(
  categories: SyllabusCategory[],
  draft: Record<string, string>,
): SyllabusProfileDetail['corrections'] {
  const corrections: SyllabusProfileDetail['corrections'] = [];
  for (const c of categories) {
    const weightRaw = (draft[`${c.name}:weight`] ?? '').trim();
    if (weightRaw !== '') {
      const value = Number(weightRaw);
      if (!Number.isNaN(value) && value !== c.weight) {
        corrections.push({ target_type: 'category', operation: 'set_weight', category_name: c.name, value });
      }
    }
    const countRaw = (draft[`${c.name}:count`] ?? '').trim();
    if (countRaw !== '') {
      const value = Number(countRaw);
      if (!Number.isNaN(value) && value !== c.count) {
        corrections.push({ target_type: 'category', operation: 'set_count', category_name: c.name, value });
      }
    }
  }
  return corrections;
}

interface UploadFields {
  institution: string;
  courseCode: string;
  term: string;
  section: string;
}

type GradeStateDraft = Record<string, { actual: string; projected: string }>;

function draftFromModel(model: SyllabusGradeModel | null): GradeStateDraft {
  const draft: GradeStateDraft = {};
  if (!model) return draft;
  for (const category of model.categories) {
    if (category.weight !== null) draft[`category:${category.name}`] = { actual: '', projected: '' };
  }
  for (const assessment of model.assessments) {
    if ((assessment.weight !== null || assessment.points !== null) && assessment.category === null) {
      draft[`assessment:${assessment.name}`] = { actual: '', projected: '' };
    }
  }
  return draft;
}

function draftFromSavedState(draft: GradeStateDraft, detail: SyllabusProfileDetail): GradeStateDraft {
  const next: GradeStateDraft = { ...draft };
  for (const c of detail.grade_state?.category_scores ?? []) {
    const key = `category:${c.category_name}`;
    if (key in next) {
      next[key] = { actual: c.actual_score != null ? String(c.actual_score) : '', projected: '' };
    }
  }
  for (const a of detail.grade_state?.assessment_scores ?? []) {
    const key = `assessment:${a.assessment_name}`;
    if (key in next) {
      next[key] = { actual: a.actual_score != null ? String(a.actual_score) : '', projected: '' };
    }
  }
  return next;
}

// `allowProjected` splits the two consumers of the draft:
//   false -> persistence (PUT /grade-state): actuals only, What-if ignored.
//   true  -> the /calculate path: a non-empty What-if takes PRECEDENCE over
//            the row's actual. The student is asking "what if this score were
//            X instead", so the row is submitted as { projected_score } with
//            no actual_score -- CategoryScoreInput / AssessmentScoreInput
//            forbid setting both (exactly_one_score), and a projected row is
//            deliberately pulled out of the completed-weight pool, so the
//            current grade re-normalises over the remaining real scores.
function buildGradeState(draft: GradeStateDraft, allowProjected: boolean) {
  const category_scores: { category_name: string; actual_score?: number; projected_score?: number }[] = [];
  const assessment_scores: { assessment_name: string; actual_score?: number; projected_score?: number }[] = [];
  for (const [key, values] of Object.entries(draft)) {
    const [kind, name] = key.split(/:(.*)/s);
    const actual = values.actual.trim() === '' ? null : Number(values.actual);
    const projected = values.projected.trim() === '' ? null : Number(values.projected);
    let entry: { actual_score?: number; projected_score?: number } | null = null;
    if (allowProjected && projected !== null && !Number.isNaN(projected)) {
      entry = { projected_score: projected };
    } else if (actual !== null && !Number.isNaN(actual)) {
      entry = { actual_score: actual };
    }
    if (!entry) continue;
    if (kind === 'category') category_scores.push({ category_name: name, ...entry });
    else assessment_scores.push({ assessment_name: name, ...entry });
  }
  return { category_scores, assessment_scores };
}

function actualOnlyState(draft: GradeStateDraft) {
  return buildGradeState(draft, false);
}

interface Props {
  accessToken: string | null;
  courses: AcademicCourse[];
  institutionName: string | null;
}

interface EligibleCourse {
  code: string;
  title: string | null;
}

export function GradeCalculatorPanel({ accessToken, courses, institutionName }: Props) {
  const [profiles, setProfiles] = useState<SyllabusProfileSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedProfileId, setSelectedProfileId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SyllabusProfileDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [showUpload, setShowUpload] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [fields, setFields] = useState<UploadFields>({ institution: '', courseCode: '', term: '', section: '' });
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [academicTerms, setAcademicTerms] = useState<PlanningTerm[]>([]);
  const [plannedCourses, setPlannedCourses] = useState<PlannedCourse[]>([]);
  const [academicDataLoaded, setAcademicDataLoaded] = useState(false);

  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Dismissed inline findings, session-only: NOT persisted anywhere (no API
  // call, no backend field). Keyed by the finding's index in its source
  // findings array, so it resets whenever that array is recreated -- a
  // fresh page load, or reselecting a calculator -- because a stale index
  // set is meaningless against a different or re-fetched findings array. If
  // this ever needs to survive reload, it needs a real backend field (see
  // the investigation: `findings` has no dismissed/acknowledged concept at
  // all today), not just re-reading this state.
  const [dismissedFindingKeys, setDismissedFindingKeys] = useState<Set<number>>(new Set());

  const [gradeDraft, setGradeDraft] = useState<GradeStateDraft>({});
  const [calcResult, setCalcResult] = useState<SyllabusCalculationResult | null>(null);
  const [calcError, setCalcError] = useState<string | null>(null);
  const [showBreakdown, setShowBreakdown] = useState(false);

  // Opt-in re-open of the letter-grade cutoff editor once the calculator is
  // ready. Off by default (most students never need it); submitting an edit
  // from here drops the profile back to 'reconfirm_required' on the backend,
  // which re-renders the normal review card, so this toggle only has to
  // surface CutoffTable, not manage the return trip.
  const [showCutoffReview, setShowCutoffReview] = useState(false);

  const [removingId, setRemovingId] = useState<string | null>(null);

  // Pending live-projection debounce timer (null when none is scheduled), so
  // "Save & calculate" can cancel it before running its own calculation.
  const projectionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Monotonic id for every /calculate dispatch (debounced or button). A
  // response is only applied if its id is still the latest one issued, so
  // whichever call was dispatched last wins regardless of network arrival
  // order -- and the button, by dispatching last, is always authoritative.
  const calcRunIdRef = useRef(0);

  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;
    listSyllabusGradeProfiles(accessToken)
      .then((items) => { if (!cancelled) setProfiles(items); })
      .catch((err: unknown) => {
        if (cancelled) return;
        setListError(err instanceof SyllabusApiError ? err.message : 'Could not load your grade calculators.');
        setProfiles([]);
      });
    return () => { cancelled = true; };
  }, [accessToken]);

  useEffect(() => {
    if (!accessToken || !showUpload) return;
    let cancelled = false;
    setAcademicDataLoaded(false);
    void Promise.all([
      fetchTerms({ slug: null, accessToken }),
      fetchPlannedCourses({ slug: null, accessToken }),
    ]).then(([termResult, plannedResult]) => {
      if (cancelled) return;
      setAcademicTerms(termResult.terms);
      setPlannedCourses(plannedResult.plannedCourses);
      setAcademicDataLoaded(true);
    });
    return () => { cancelled = true; };
  }, [accessToken, showUpload]);

  const eligibleCoursesByTerm = useMemo(() => {
    const byTerm = new Map<string, Map<string, EligibleCourse>>();
    const add = (termId: string | null, code: string, title: string | null) => {
      if (!termId || !code.trim()) return;
      const normalizedCode = code.trim().toUpperCase();
      const termCourses = byTerm.get(termId) ?? new Map<string, EligibleCourse>();
      const existing = termCourses.get(normalizedCode);
      termCourses.set(normalizedCode, {
        code: existing?.code ?? code.trim(),
        title: existing?.title ?? title,
      });
      byTerm.set(termId, termCourses);
    };
    courses.filter((course) => course.status === 'in_progress')
      .forEach((course) => add(course.term_id, course.course_code, course.title));
    plannedCourses.forEach((course) => add(course.term_id, course.course_code, course.title));
    return byTerm;
  }, [courses, plannedCourses]);

  const eligibleTerms = useMemo(() => {
    const inProgressTermIds = new Set(
      courses.filter((course) => course.status === 'in_progress').map((course) => course.term_id),
    );
    const byLabel = new Map<string, PlanningTerm>();
    for (const term of academicTerms) {
      if (term.id !== null && eligibleCoursesByTerm.has(term.id) && !byLabel.has(term.label)) {
        byLabel.set(term.label, term);
      }
    }
    return [...byLabel.values()].sort((a, b) => {
      const relevance = (term: PlanningTerm) => term.id && inProgressTermIds.has(term.id) ? 0 : term.is_upcoming ? 1 : 2;
      const relevanceDelta = relevance(a) - relevance(b);
      if (relevanceDelta !== 0) return relevanceDelta;
      if (a.year !== b.year) return b.year - a.year;
      return (b.sequence ?? 0) - (a.sequence ?? 0) || a.label.localeCompare(b.label);
    });
  }, [academicTerms, courses, eligibleCoursesByTerm]);

  const selectedTerm = eligibleTerms.find((term) => term.label === fields.term) ?? null;
  const selectedTermCourses = useMemo(() => {
    if (!selectedTerm?.id) return [];
    return [...(eligibleCoursesByTerm.get(selectedTerm.id)?.values() ?? [])]
      .sort((a, b) => a.code.localeCompare(b.code));
  }, [eligibleCoursesByTerm, selectedTerm]);

  useEffect(() => {
    if (!showUpload || fields.term || eligibleTerms.length === 0) return;
    const inProgressTermIds = new Set(
      courses.filter((course) => course.status === 'in_progress').map((course) => course.term_id),
    );
    const defaultTerm = eligibleTerms.find((term) => term.id && inProgressTermIds.has(term.id))
      ?? eligibleTerms.find((term) => term.is_upcoming)
      ?? eligibleTerms[0];
    setFields((current) => ({ ...current, term: defaultTerm.label, courseCode: '' }));
  }, [courses, eligibleTerms, fields.term, showUpload]);

  function loadDetail(profileId: string) {
    if (!accessToken) return;
    setSelectedProfileId(profileId);
    setDetail(null);
    setDetailError(null);
    setCalcResult(null);
    setCalcError(null);
    setGradeDraft({});
    getSyllabusGradeProfile(accessToken, profileId)
      .then((d) => {
        setDetail(d);
        setGradeDraft(draftFromSavedState(draftFromModel(d.confirmed_grade_model ?? d.extracted_grade_model), d));
      })
      .catch((err: unknown) => {
        setDetailError(err instanceof SyllabusApiError ? err.message : 'Could not load this grade calculator.');
      });
  }

  async function handleRemoveProfile(profileId: string, label: string) {
    if (!accessToken) return;
    // Destructive from the student's perspective (the calculator and any
    // grades they entered vanish from their list) even though the backend
    // keeps the row -- so gate it behind a confirm.
    if (!window.confirm(`Remove the grade calculator for ${label}? You can re-upload the syllabus later to start over.`)) {
      return;
    }
    setRemovingId(profileId);
    setListError(null);
    try {
      await deleteSyllabusGradeProfile(accessToken, profileId);
      setProfiles((prev) => (prev ?? []).filter((p) => p.id !== profileId));
    } catch (err) {
      setListError(err instanceof SyllabusApiError ? err.message : 'Could not remove this grade calculator.');
    } finally {
      setRemovingId(null);
    }
  }

  async function refreshDetail() {
    if (!accessToken || !selectedProfileId) return;
    const d = await getSyllabusGradeProfile(accessToken, selectedProfileId);
    setDetail(d);
    setGradeDraft((prev) => draftFromSavedState({ ...draftFromModel(d.confirmed_grade_model ?? d.extracted_grade_model), ...prev }, d));
    return d;
  }

  async function handleUpload() {
    if (!accessToken || !file) return;
    setUploading(true);
    setUploadError(null);
    try {
      const created = await ingestSyllabus(accessToken, file, {
        institution: institutionName || fields.institution || undefined,
        course_code: fields.courseCode || undefined,
        term: fields.term || undefined,
        section: fields.section || undefined,
      });
      const summary: SyllabusProfileSummary = {
        id: created.id,
        institution: created.course.institution,
        course_code: created.course.course_code,
        term: created.course.term,
        section: created.course.section,
        review_state: created.review_state,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        calculator_ready: created.calculator_ready,
        current_grade: null,
      };
      // The backend reuses an existing profile row when the same
      // student/institution/course_code/term is re-uploaded (get_or_create_
      // profile), so key on id: replace the matching summary if present,
      // otherwise append -- never render two rows for one profile.
      setProfiles((prev) => [...(prev ?? []).filter((p) => p.id !== summary.id), summary]);
      setShowUpload(false);
      setFile(null);
      setDetail(created);
      setSelectedProfileId(created.id);
      setGradeDraft(draftFromModel(created.confirmed_grade_model ?? created.extracted_grade_model));
    } catch (err) {
      setUploadError(err instanceof SyllabusApiError ? err.message : "CampusIQ couldn't process this syllabus.");
    } finally {
      setUploading(false);
    }
  }

  async function handleConfirm() {
    if (!accessToken || !selectedProfileId) return;
    setBusy(true);
    setActionError(null);
    try {
      const updated = await confirmSyllabusGradeModel(accessToken, selectedProfileId);
      setDetail(updated);
      setGradeDraft((prev) => ({ ...draftFromModel(updated.confirmed_grade_model ?? updated.extracted_grade_model), ...prev }));
    } catch (err) {
      setActionError(err instanceof SyllabusApiError ? err.message : 'Could not confirm this grading model.');
    } finally {
      setBusy(false);
    }
  }

  // Corrections are cumulative on the backend (the candidate is rebuilt
  // from the extraction + the whole list every time), so always resend the
  // accumulated list plus the new entries. Returns the updated detail on
  // success, null on failure.
  async function submitCorrections(
    next: SyllabusProfileDetail['corrections'],
    failureCopy: string,
  ): Promise<SyllabusProfileDetail | null> {
    if (!accessToken || !selectedProfileId) return null;
    setBusy(true);
    setActionError(null);
    try {
      const updated = await submitSyllabusCorrections(accessToken, selectedProfileId, next);
      setDetail(updated);
      setGradeDraft((prev) => ({ ...draftFromModel(updated.confirmed_grade_model ?? updated.extracted_grade_model), ...prev }));
      return updated;
    } catch (err) {
      setActionError(err instanceof SyllabusApiError ? err.message : failureCopy);
      return null;
    } finally {
      setBusy(false);
    }
  }

  // Every action in the unified CutoffTable -- a per-row bounds edit (with
  // its auto-appended confirm_threshold_value), affirming an unverified
  // value, confirming a "higher grade wins" overlap default -- plus every
  // CategoryWeightEditor save (set_weight / set_count) lands here as one
  // appended correction batch. Corrections are cumulative, so this always
  // resends detail.corrections plus the new entries (see submitCorrections).
  function handleReviewCorrections(newCorrections: SyllabusProfileDetail['corrections']) {
    if (!detail || newCorrections.length === 0) return;
    void submitCorrections([...detail.corrections, ...newCorrections], 'Could not save your corrections.');
  }

  // The one path that talks to /calculate -- shared by the debounced live
  // projection and by "Save & calculate". Every call takes a fresh run id;
  // a resolved response whose id has since been superseded is dropped, so
  // out-of-order arrivals never overwrite a newer calculation. Sends
  // What-If scores with precedence over their row's actual
  // (buildGradeState(..., true)) and never persists anything.
  async function dispatchCalculation() {
    if (!accessToken || !selectedProfileId) return;
    const runId = ++calcRunIdRef.current;
    setCalcError(null);
    try {
      const combined = buildGradeState(gradeDraft, true);
      const result = await calculateSyllabusGrade(accessToken, selectedProfileId, combined);
      if (runId !== calcRunIdRef.current) return;
      setCalcResult(result);
    } catch (err) {
      if (runId !== calcRunIdRef.current) return;
      setCalcError(err instanceof SyllabusApiError ? err.message : 'Could not calculate your grade.');
      setCalcResult(null);
    }
  }

  function cancelPendingProjection() {
    if (projectionTimerRef.current !== null) {
      clearTimeout(projectionTimerRef.current);
      projectionTimerRef.current = null;
    }
  }

  // Single "Save & calculate" flow: persist the entered actuals, then run
  // the calculation. Separate endpoints (PUT /grade-state, POST /calculate),
  // so they're sequenced -- a failed save surfaces before any result, and
  // the calculation reflects the persisted actuals.
  async function handleSaveAndCalculate() {
    if (!accessToken || !selectedProfileId || !detail) return;

    // A queued live-projection call must not land after (and overwrite) this
    // button's calculation. Cancel the pending debounce, and bump the run id
    // now so any projection request already in flight during the save await
    // is discarded when it resolves.
    cancelPendingProjection();
    calcRunIdRef.current += 1;

    // Snapshot the student's What-If entries before any refetch: a 409
    // reload re-seeds persisted actuals from the server and would otherwise
    // clear these, but the conflict concerns persisted actuals only --
    // hypotheticals are local draft state and should survive.
    const whatIfSnapshot: Record<string, string> = {};
    for (const [key, value] of Object.entries(gradeDraft)) {
      if (value.projected.trim() !== '') whatIfSnapshot[key] = value.projected;
    }

    setBusy(true);
    setActionError(null);
    let saved = false;
    try {
      const state = actualOnlyState(gradeDraft);
      const result = await saveSyllabusGradeState(accessToken, selectedProfileId, state, detail.grade_state_revision);
      setDetail((prev) => (prev ? { ...prev, grade_state: state, grade_state_revision: result.revision } : prev));
      saved = true;
    } catch (err) {
      if (err instanceof SyllabusApiError && err.status === 409) {
        setActionError('Your saved grades changed in another session. Reloading the latest values.');
        const fresh = await refreshDetail();
        if (fresh) {
          setGradeDraft((prev) => {
            const next: GradeStateDraft = {};
            for (const key of new Set([...Object.keys(prev), ...Object.keys(whatIfSnapshot)])) {
              next[key] = {
                actual: prev[key]?.actual ?? '',
                projected: whatIfSnapshot[key] ?? prev[key]?.projected ?? '',
              };
            }
            return next;
          });
        }
      } else {
        setActionError(err instanceof SyllabusApiError ? err.message : 'Could not save your grades.');
      }
    } finally {
      setBusy(false);
    }

    if (saved) await dispatchCalculation();
  }

  const scoreableNames = useMemo(() => {
    const model = detail?.confirmed_grade_model ?? detail?.extracted_grade_model ?? null;
    if (!model) return [];
    const names: string[] = [];
    for (const c of model.categories) if (c.weight !== null) names.push(c.name);
    for (const a of model.assessments) if ((a.weight !== null || a.points !== null) && a.category === null) names.push(a.name);
    return names;
  }, [detail]);

  // Rows where a What-if is standing in for a real score the student also
  // entered: buildGradeState(.., true) submits these as projected_score, so
  // they drop out of the completed-weight pool and the current grade shifts.
  // A What-if on an empty row displaces nothing (it never counted), so it
  // is not tallied here.
  const displacedActualCount = useMemo(
    () =>
      Object.values(gradeDraft).filter((v) => v.actual.trim() !== '' && v.projected.trim() !== '').length,
    [gradeDraft],
  );

  // Reselecting a calculator (or the initial load of one) starts review
  // findings fresh -- dismissal is session-only and must not leak between
  // calculators or survive a reopen. See dismissedFindingKeys above.
  useEffect(() => {
    setDismissedFindingKeys(new Set());
    setShowCutoffReview(false);
  }, [selectedProfileId]);

  // Live projection: any change to an actual OR What-If score recalculates
  // after a short pause, with no explicit action. Debounced (not per
  // keystroke) because the calculation is server-side -- see
  // PROJECTION_DEBOUNCE_MS. Only ever calls /calculate; persistence stays
  // with "Save & calculate". dispatchCalculation's run-id guard means a
  // slow response here can't clobber a newer one.
  useEffect(() => {
    if (!accessToken || !selectedProfileId || !detail?.calculator_ready) return;
    const hasAnyEntry = Object.values(gradeDraft).some(
      (v) => v.actual.trim() !== '' || v.projected.trim() !== '',
    );
    if (!hasAnyEntry) return;
    const handle = setTimeout(() => {
      projectionTimerRef.current = null;
      void dispatchCalculation();
    }, PROJECTION_DEBOUNCE_MS);
    projectionTimerRef.current = handle;
    return () => {
      clearTimeout(handle);
      if (projectionTimerRef.current === handle) projectionTimerRef.current = null;
    };
    // dispatchCalculation reads gradeDraft/accessToken/selectedProfileId at
    // call time; re-running on gradeDraft is what resets the debounce.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gradeDraft, accessToken, selectedProfileId, detail?.calculator_ready]);

  // Findings that don't belong in the review list:
  // - RULE_INFO_FINDING_CODES: rule-informational (curve / late-work /
  //   makeup) -- shown in the Professor's rules panel instead.
  // - NON_BLOCKING_INFO_FINDING_CODES: non-blocking informational with no
  //   correction path (unknown_assessment_count).
  // - RELOCATED_FINDING_CODES: category_weight_validation / unknown_weight --
  //   shown in the editable category-weight table instead, so the dismissible
  //   copy here is dropped.
  // - overlapping_grade_thresholds for a cleanly-resolvable pair --
  //   handled by the CutoffTable's "higher grade wins" banner.
  //   Unresolved overlaps keep their raw finding.
  //
  // missing_grade_scale used to be filtered here and explained in the
  // Target Grade card; with that card removed it flows through to the
  // review list like any other non-blocking finding.
  const reviewFindings = useMemo(() => {
    const resolvedPairs = resolvedOverlapPairKeys(detail?.cutoff_overlap_resolution);
    return ((detail?.confirmed_reconciliation ?? detail?.reconciliation)?.findings ?? []).filter((finding) => {
      if (
        RULE_INFO_FINDING_CODES.has(finding.code) ||
        NON_BLOCKING_INFO_FINDING_CODES.has(finding.code) ||
        RELOCATED_FINDING_CODES.has(finding.code)
      )
        return false;
      if (finding.code === 'overlapping_grade_thresholds') {
        const pair = overlapFindingPair(finding);
        if (pair && resolvedPairs.has(cutoffPairKey(pair[0], pair[1]))) return false;
      }
      // Per-threshold claim-evidence findings are surfaced per-row in the
      // CutoffTable -- drop the raw finding here so it isn't also shown as
      // a bare dismiss.
      if (CLAIM_EVIDENCE_THRESHOLD_CODES.has(finding.code) && thresholdFindingLetter(finding)) return false;
      return true;
    });
  }, [detail]);

  const findingsByAnchor = useMemo(
    () => groupFindingsByAnchor(reviewFindings, detail?.extracted_grade_model ?? null),
    [reviewFindings, detail],
  );

  function handleDismissFinding(key: number) {
    setDismissedFindingKeys((prev) => {
      const next = new Set(prev);
      next.add(key);
      return next;
    });
  }

  if (!accessToken) {
    return (
      <div className="card grade-calculator-panel">
        <p className="empty-state">Sign in to use the Grade Calculator.</p>
      </div>
    );
  }

  // ── Detail view (upload processing / review / confirmed calculator) ──────
  if (selectedProfileId) {
    return (
      <div className="grade-calculator-panel" data-testid="grade-calculator-detail">
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setSelectedProfileId(null); setDetail(null); }}>
          ← Back to your calculators
        </button>

        {detailError && <p className="login-error" role="alert">{detailError}</p>}

        {!detail && !detailError && (
          <div className="card" role="status" aria-live="polite">
            <span className="spinner" aria-hidden="true" />
            <p>Loading your grade calculator…</p>
          </div>
        )}

        {detail && (
          <>
            <h2 className="academic-section-heading">
              {detail.course.course_code ?? 'Untitled course'}
              {detail.course.term ? ` — ${detail.course.term}` : ''}
            </h2>

            {actionError && <p className="login-error" role="alert">{actionError}</p>}

            {!detail.calculator_ready && (
              <div className="card grade-review-card">
                <h3 className="card-heading">
                  {detail.confirmed_reconciliation ? 'Still needs your review' : 'Needs your review'}
                </h3>
                <CutoffTable
                  key={detail.id}
                  detail={detail}
                  busy={busy}
                  onSubmitCorrections={handleReviewCorrections}
                />
                <GeneralFindings
                  findings={findingsByAnchor.get('general') ?? []}
                  dismissedFindingKeys={dismissedFindingKeys}
                  onDismissFinding={handleDismissFinding}
                />
                <SyllabusGradingBreakdown
                  model={detail.confirmed_grade_model ?? detail.extracted_grade_model}
                  findingsByAnchor={findingsByAnchor}
                  dismissedFindingKeys={dismissedFindingKeys}
                  onDismissFinding={handleDismissFinding}
                  editable
                  detail={detail}
                  busy={busy}
                  onSubmitCorrections={handleReviewCorrections}
                />
                <SyllabusRulesList
                  model={detail.extracted_grade_model}
                  findingsByAnchor={findingsByAnchor}
                  dismissedFindingKeys={dismissedFindingKeys}
                  onDismissFinding={handleDismissFinding}
                />
                <button type="button" className="btn btn-primary" onClick={handleConfirm} disabled={busy} aria-busy={busy}>
                  {busy ? 'Confirming…' : 'Confirm'}
                </button>
              </div>
            )}

            {detail.calculator_ready && detail.review_state !== 'confirmed' && (
              <div className="card grade-review-card">
                <h3 className="card-heading">Review grading breakdown</h3>
                <SyllabusGradingBreakdown model={detail.confirmed_grade_model} />
                <SyllabusRulesList model={detail.confirmed_grade_model} findingsByAnchor={EMPTY_FINDINGS_BY_ANCHOR} />
                <button type="button" className="btn btn-primary" onClick={handleConfirm} disabled={busy} aria-busy={busy}>
                  {busy ? 'Confirming…' : 'Confirm'}
                </button>
              </div>
            )}

            {detail.calculator_ready && (
              // Side-by-side region: the calculator cards ("Enter your
              // grades", "Current grade") in the main column, the
              // Professor's rules reference panel in a sticky sidebar so
              // it stays visible across every calculator interaction, not just
              // data entry (syllabus-review-redesign-spec.md §2C). Collapses
              // to a single column below 880px -- see .grade-calculator-layout
              // in index.css for why that breakpoint and not the 640px one.
              <div className="grade-calculator-layout">
                <div className="grade-calculator-main">
                  <div className="card">
                    <h3 className="card-heading">Enter your grades</h3>
                    <p className="empty-state">Leave a field blank if you don't know it yet — blank never counts as zero.</p>
                    {scoreableNames.map((name) => {
                      const key = `${detail.confirmed_grade_model?.categories.some((c) => c.name === name) ? 'category' : 'assessment'}:${name}`;
                      return (
                        <div className="grade-entry-row" key={key}>
                          <label htmlFor={`actual-${key}`}>{name}</label>
                          <input
                            id={`actual-${key}`}
                            type="number"
                            min={0}
                            max={100}
                            className="form-input"
                            value={gradeDraft[key]?.actual ?? ''}
                            onChange={(e) => setGradeDraft((prev) => ({ ...prev, [key]: { ...prev[key], actual: e.target.value, projected: prev[key]?.projected ?? '' } }))}
                            placeholder="—"
                          />
                          <label htmlFor={`hypo-${key}`} className="sr-only">Hypothetical {name} score</label>
                          <input
                            id={`hypo-${key}`}
                            type="number"
                            min={0}
                            max={100}
                            className="form-input grade-entry-hypothetical"
                            value={gradeDraft[key]?.projected ?? ''}
                            onChange={(e) => setGradeDraft((prev) => ({ ...prev, [key]: { ...prev[key], projected: e.target.value, actual: prev[key]?.actual ?? '' } }))}
                            placeholder="What if?"
                          />
                        </div>
                      );
                    })}
                    <p className="empty-state">Your grade updates as you type — the What-if column projects a score without saving it.</p>
                    <div className="grade-entry-actions">
                      <button type="button" className="btn btn-primary btn-sm" onClick={handleSaveAndCalculate} disabled={busy} aria-busy={busy}>
                        {busy ? 'Saving…' : 'Save & calculate'}
                      </button>
                    </div>
                  </div>

                  {calcError && <p className="login-error" role="alert">{calcError}</p>}

                  {calcResult && (
                    <div className="card" role="status" aria-live="polite">
                      <h3 className="card-heading">Current grade</h3>
                      <p className="overview-stat-value">{calcResult.current_grade !== null ? `${calcResult.current_grade}%` : '—'}</p>
                      <p className="empty-state">
                        {calcResult.completed_weight !== null
                          ? `Based on ${calcResult.completed_weight}% of the course completed.`
                          : 'No grades entered yet.'}
                      </p>
                      {displacedActualCount > 0 && (
                        <p className="empty-state">
                          {displacedActualCount === 1
                            ? '1 category is projected from a What-if score instead of counted.'
                            : `${displacedActualCount} categories are projected from What-if scores instead of counted.`}
                        </p>
                      )}

                      <h3 className="card-heading">Projected grade</h3>
                      {calcResult.projected_grade !== null ? (
                        <p className="overview-stat-value">{calcResult.projected_grade}%</p>
                      ) : (
                        <p className="empty-state">Enter a hypothetical score for every remaining component to see your projected grade.</p>
                      )}

                      {calcResult.applied_rules.filter((r) => r.changed_calculation).map((rule, i) => (
                        <p key={i} className="grade-rule-explanation">
                          {rule.rule_type === 'replacement'
                            ? `${rule.source} replacement applied: your ${rule.source} score replaces your ${rule.target} score in this scenario.`
                            : `${rule.description}`}
                        </p>
                      ))}

                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowBreakdown((v) => !v)}>
                        {showBreakdown ? 'Hide breakdown' : 'Show breakdown'}
                      </button>
                      {showBreakdown && (
                        <div className="real-course-table" role="table" aria-label="Calculation breakdown">
                          {calcResult.components.map((c) => (
                            <div className="real-course-row" role="row" key={c.name}>
                              <span role="cell">{c.name}</span>
                              <span role="cell">entered: {c.original_score ?? '—'}</span>
                              <span role="cell">effective: {c.effective_score ?? '—'}</span>
                              <span role="cell">weight: {formatPercent(c.weight_percent)}</span>
                              <span role="cell">contribution: {c.contribution ?? '—'}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {!showCutoffReview ? (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm grade-cutoff-revisit-toggle"
                      onClick={() => setShowCutoffReview(true)}
                    >
                      Review letter-grade cutoffs
                    </button>
                  ) : (
                    <div className="card grade-cutoff-revisit">
                      <p className="empty-state">
                        Saving a change here sends your calculator back for a quick re-confirm.
                      </p>
                      <CutoffTable
                        key={detail.id}
                        detail={detail}
                        busy={busy}
                        onSubmitCorrections={handleReviewCorrections}
                      />
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => setShowCutoffReview(false)}
                      >
                        Done
                      </button>
                    </div>
                  )}
                </div>

                <div className="grade-calculator-aside">
                  <ProfessorsRules model={detail.confirmed_grade_model ?? detail.extracted_grade_model} />
                </div>
              </div>
            )}
          </>
        )}
      </div>
    );
  }

  // ── List / empty state / upload form ──────────────────────────────────────
  return (
    <div className="grade-calculator-panel" data-testid="grade-calculator-list">
      <h2 className="academic-section-heading">Grade Calculator</h2>

      {!showUpload && (
        <>
          {profiles === null && !listError && <p className="empty-state">Loading your grade calculators…</p>}
          {listError && <p className="login-error" role="alert">{listError}</p>}

          {profiles !== null && profiles.length === 0 && (
            <div className="real-empty">
              <h3>See what you need to reach your target grade</h3>
              <p>Upload your syllabus and CampusIQ will identify how your course is graded, let you verify it, and calculate scenarios.</p>
              <button type="button" className="btn btn-primary" onClick={() => setShowUpload(true)}>
                Upload syllabus
              </button>
            </div>
          )}

          {profiles !== null && profiles.length > 0 && (
            <>
              <ul className="grade-card-grid" aria-label="Your grade calculators">
                {profiles.map((p) => (
                  <li key={p.id}>
                    <GradeCard
                      profile={p}
                      onOpen={() => loadDetail(p.id)}
                      onRemove={() => handleRemoveProfile(p.id, p.course_code ?? 'this course')}
                      removing={removingId === p.id}
                    />
                  </li>
                ))}
              </ul>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowUpload(true)}>
                Upload another syllabus
              </button>
            </>
          )}
        </>
      )}

      {showUpload && (
        <form
          className="login-form"
          onSubmit={(e) => { e.preventDefault(); void handleUpload(); }}
        >
          <label className="form-label" htmlFor="syllabus-file">Syllabus PDF</label>
          <input
            id="syllabus-file"
            type="file"
            accept="application/pdf"
            className="form-input"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <label className="form-label" htmlFor="syllabus-term">Term</label>
          <select
            id="syllabus-term"
            className="form-input"
            value={fields.term}
            onChange={(e) => setFields((f) => ({ ...f, term: e.target.value, courseCode: '' }))}
            disabled={!academicDataLoaded || eligibleTerms.length === 0}
          >
            <option value="">Select a term</option>
            {eligibleTerms.map((term) => <option key={term.key} value={term.label}>{term.label}</option>)}
          </select>
          <label className="form-label" htmlFor="syllabus-course-code">Course</label>
          <select
            id="syllabus-course-code"
            className="form-input"
            value={fields.courseCode}
            onChange={(e) => setFields((f) => ({ ...f, courseCode: e.target.value }))}
            disabled={!selectedTerm || selectedTermCourses.length === 0}
          >
            <option value="">Select a course</option>
            {selectedTermCourses.map((course) => (
              <option key={course.code.toUpperCase()} value={course.code}>
                {course.code}{course.title ? ` — ${course.title}` : ''}
              </option>
            ))}
          </select>
          {academicDataLoaded && eligibleTerms.length === 0 && (
            <p className="empty-state">No current or planned courses are available. Add your courses in Academic before uploading a syllabus.</p>
          )}
          {selectedTerm && selectedTermCourses.length === 0 && (
            <p className="empty-state">No courses are available for this term.</p>
          )}

          {uploading && (
            <p role="status" aria-live="polite">
              <span className="spinner" aria-hidden="true" /> Reading syllabus and finding grading information…
            </p>
          )}
          {uploadError && <p className="login-error" role="alert">{uploadError}</p>}

          <div className="grade-entry-actions">
            <button type="submit" className="btn btn-primary" disabled={!file || !selectedTerm || !fields.courseCode || uploading} aria-busy={uploading}>
              {uploading ? 'Processing…' : 'Upload syllabus'}
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => setShowUpload(false)} disabled={uploading}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

const EMPTY_FINDINGS_BY_ANCHOR: Map<string, FindingWithKey[]> = new Map();

/**
 * One finding, rendered small and inline where it's relevant -- not as a
 * card in a separate flat list. Styled after the .rv-field/.rv-glyph
 * provenance pattern (review/FieldRow.tsx): a small marker column plus
 * compact text. Dismiss reuses the .dash-notice-dismiss "x" pattern
 * (DashboardSuccessNotice.tsx), scaled down for inline use.
 */
function InlineFinding({
  finding,
  onDismiss,
  dismissible = true,
}: {
  finding: SyllabusFinding;
  onDismiss: () => void;
  // false for a finding that's genuinely blocking confirm (per its own
  // instance severity) with a real fix action anchored elsewhere -- e.g.
  // CategoryWeightEditor's category_weight_validation / unknown_weight
  // notes. The affordance must match the gate: a finding that still blocks
  // confirm must not offer a dismiss button that makes it look optional.
  dismissible?: boolean;
}) {
  return (
    <p className={`grade-inline-finding grade-inline-finding--${finding.severity}`} data-finding-code={finding.code}>
      <span className="grade-inline-finding-glyph" aria-hidden="true">
        {finding.severity === 'error' ? '!' : '·'}
      </span>
      <span className="grade-inline-finding-text">{findingCopy(finding)}</span>
      {dismissible && (
        <button
          type="button"
          className="grade-inline-finding-dismiss"
          onClick={onDismiss}
          aria-label="Dismiss this finding"
        >
          ×
        </button>
      )}
    </p>
  );
}

function InlineFindings({
  findings,
  dismissedFindingKeys,
  onDismissFinding,
}: {
  findings: FindingWithKey[];
  dismissedFindingKeys: Set<number>;
  onDismissFinding: (key: number) => void;
}) {
  const visible = findings.filter(({ finding, key }) => finding.severity !== 'valid' && !dismissedFindingKeys.has(key));
  if (visible.length === 0) return null;
  return (
    <div className="grade-inline-findings">
      {visible.map(({ finding, key }) => (
        <InlineFinding key={key} finding={finding} onDismiss={() => onDismissFinding(key)} />
      ))}
    </div>
  );
}

/**
 * Fallback for findings whose `field` doesn't identify a row this panel
 * currently renders (course-level findings like grading_method_unknown,
 * threshold findings -- there's no per-threshold row in the review step --
 * and evidence-coverage findings). Same inline/small-font/dismiss
 * treatment as InlineFindings, just grouped at the top of the review card
 * instead of anchored to a specific row.
 */
function GeneralFindings({
  findings,
  dismissedFindingKeys,
  onDismissFinding,
}: {
  findings: FindingWithKey[];
  dismissedFindingKeys: Set<number>;
  onDismissFinding: (key: number) => void;
}) {
  const visible = findings.filter(({ finding, key }) => finding.severity !== 'valid' && !dismissedFindingKeys.has(key));
  if (visible.length === 0) return null;
  return (
    <div className="grade-inline-findings grade-inline-findings--general" aria-label="Grading review notes">
      {visible.map(({ finding, key }) => (
        <InlineFinding key={key} finding={finding} onDismiss={() => onDismissFinding(key)} />
      ))}
    </div>
  );
}

/**
 * Unified letter-grade cutoff table for the review step -- one row per
 * grade_thresholds entry, sourced from confirmed_grade_model ??
 * extracted_grade_model. Replaces the three earlier card-based UIs
 * (overlap propose/confirm, per-threshold value affirm, manual bounds
 * editor) with a single view:
 *
 *  - Every row's minimum/maximum is editable in place. Saving diffs the
 *    draft and emits set_minimum / set_maximum for the bounds that
 *    changed, plus an auto-appended confirm_threshold_value for each
 *    letter touched (thresholdEditCorrections) -- so a student who types a
 *    bound is never re-prompted to affirm the value they just entered.
 *  - A resolvable overlap (cutoff_overlap_resolution.resolved) shows a
 *    cross-row banner proposing "higher grade wins the tie", confirmable
 *    in one click (resolve_cutoff_overlap). Its raw
 *    overlapping_grade_thresholds finding is filtered from the review list
 *    (reviewFindings). An unresolved overlap shows only a note -- editing
 *    the two rows directly is the fix, and its raw finding stays.
 *  - A row with an open claim_evidence_consistency_unverifiable /
 *    claim_evidence_value_mismatch finding and no pending edit shows its
 *    current value with a "Yes, that's correct" affirm
 *    (confirm_threshold_value). Once answered (clarifying_answers) the row
 *    shows a one-line confirmation and never asks again.
 *
 * Keyed on `detail.id` by the caller (stable across correction submits, so
 * switching profiles still forces a fresh mount). The edit draft is NOT
 * discarded on every submit: when a submit brings back new server values,
 * only bounds the student has not touched adopt them -- an in-progress edit
 * in another row survives a sibling row's affirm/resolve (see the
 * serverDraft sync effect below).
 */
function CutoffTable({
  detail,
  busy,
  onSubmitCorrections,
}: {
  detail: SyllabusProfileDetail;
  busy: boolean;
  onSubmitCorrections: (corrections: SyllabusProfileDetail['corrections']) => void;
}) {
  const model = detail.confirmed_grade_model ?? detail.extracted_grade_model;
  const thresholds = model?.grade_thresholds ?? [];
  const thresholdOf = (letter: string): SyllabusThreshold | null =>
    thresholds.find((t) => t.letter === letter) ?? null;

  const answers = detail.clarifying_answers ?? {};
  const rawFindings = (detail.confirmed_reconciliation ?? detail.reconciliation)?.findings ?? [];

  // Letters with an open (unanswered) per-threshold value-claim finding,
  // and letters already affirmed -- both normalized lowercase to match a
  // row regardless of casing.
  const openValueLetters = new Set<string>();
  for (const finding of rawFindings) {
    if (!CLAIM_EVIDENCE_THRESHOLD_CODES.has(finding.code)) continue;
    const letter = thresholdFindingLetter(finding);
    if (letter && !(valueClaimKey(letter) in answers)) openValueLetters.add(letter.trim().toLowerCase());
  }
  const answeredValueLetters = new Set(
    Object.keys(answers)
      .filter((k) => k.startsWith('claim_evidence:threshold:'))
      .map((k) => (answers[k]?.letter ?? k.slice('claim_evidence:threshold:'.length)).trim().toLowerCase()),
  );

  const resolution = detail.cutoff_overlap_resolution ?? { schema_version: '', resolved: [], unresolved: [] };
  const openResolved = resolution.resolved.filter((r) => !(clarifyingKey(r.winner, r.loser) in answers));
  const answeredResolved = resolution.resolved.filter((r) => clarifyingKey(r.winner, r.loser) in answers);

  // Server-truth bound values, recomputed only when the grade model itself
  // changes (a correction submit brought back a new `detail`) -- keyed on
  // `model`, not the `?? []` fallback, so it can't churn identity between
  // renders. Doubles as the initial draft and as the baseline the sync
  // effect diffs against.
  const serverDraft = useMemo((): Record<string, string> => {
    const d: Record<string, string> = {};
    for (const t of model?.grade_thresholds ?? []) {
      d[`${t.letter}:minimum`] = t.minimum != null ? String(t.minimum) : '';
      d[`${t.letter}:maximum`] = t.maximum != null ? String(t.maximum) : '';
    }
    return d;
  }, [model]);
  const [draft, setDraft] = useState<Record<string, string>>(serverDraft);

  // The table is no longer remounted on every correction submit (the caller
  // key is now just `detail.id`). Instead, when new server values arrive,
  // adopt them ONLY for bounds the student hasn't edited (draft still equals
  // the previous server value); a genuinely edited bound keeps the in-flight
  // value. Preserves the old "fresh values after a real data change" intent
  // without discarding a half-typed edit in another row when a sibling row's
  // affirm/resolve submits.
  const prevServerDraft = useRef(serverDraft);
  useEffect(() => {
    if (prevServerDraft.current === serverDraft) return;
    const prevServer = prevServerDraft.current;
    prevServerDraft.current = serverDraft;
    setDraft((current) => {
      const next: Record<string, string> = {};
      for (const key of Object.keys(serverDraft)) {
        const userEdited = (current[key] ?? '') !== (prevServer[key] ?? '');
        next[key] = userEdited ? (current[key] ?? '') : serverDraft[key];
      }
      return next;
    });
  }, [serverDraft]);

  function boundString(t: SyllabusThreshold | null, bound: 'minimum' | 'maximum'): string {
    const current = bound === 'minimum' ? t?.minimum : t?.maximum;
    return current != null ? String(current) : '';
  }
  function rowDirty(letter: string): boolean {
    const t = thresholdOf(letter);
    return (
      (draft[`${letter}:minimum`] ?? '').trim() !== boundString(t, 'minimum') ||
      (draft[`${letter}:maximum`] ?? '').trim() !== boundString(t, 'maximum')
    );
  }
  const anyDirty = thresholds.some((t) => rowDirty(t.letter));

  function handleSave() {
    const corrections = thresholdEditCorrections(thresholds.map((t) => t.letter), thresholdOf, draft);
    if (corrections.length > 0) onSubmitCorrections(corrections);
  }

  if (thresholds.length === 0) return null;

  return (
    <div className="grade-cutoff-table" data-testid="cutoff-table" aria-label="Letter grade cutoffs">
      <h4 className="card-heading">Letter grade cutoffs</h4>
      <p className="empty-state">Check each grade's range against your syllabus. Edit any value that's wrong.</p>

      {openResolved.map((r) => {
        const w = thresholdOf(r.winner);
        const l = thresholdOf(r.loser);
        const haveRanges =
          w?.minimum != null && w?.maximum != null && l?.minimum != null && l?.maximum != null;
        return (
          <div className="grade-cutoff-banner" key={`open:${r.winner},${r.loser}`} data-cutoff-pair={`${r.winner},${r.loser}`}>
            <p className="grade-cutoff-question-text">
              {haveRanges
                ? `Your syllabus lists ${r.winner} as ${w?.minimum}–${w?.maximum} and ${r.loser} as ${l?.minimum}–${l?.maximum} — these overlap at ${r.boundary}. `
                : `${r.winner} and ${r.loser} overlap at ${r.boundary}. `}
              We'll default to the higher grade winning ties, so {r.boundary} is {r.winner}, not {r.loser}. Sound right?
            </p>
            <div className="grade-cutoff-question-actions">
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={busy}
                aria-busy={busy}
                onClick={() => onSubmitCorrections([{ target_type: 'threshold', operation: 'resolve_cutoff_overlap', threshold_letter: r.winner }])}
              >
                Yes, that's right
              </button>
            </div>
            <p className="grade-cutoff-banner-hint">Or edit the {r.winner} and {r.loser} rows below and save.</p>
          </div>
        );
      })}

      {resolution.unresolved.map((u) => (
        <p
          className="grade-cutoff-banner grade-cutoff-banner--manual"
          key={`unresolved:${u.letters[0]},${u.letters[1]}`}
          data-cutoff-pair={`${u.letters[0]},${u.letters[1]}`}
        >
          The cutoffs for {u.letters[0]} and {u.letters[1]} overlap and CampusIQ can't pick a safe default — edit those
          rows below and save.
        </p>
      ))}

      <div className="grade-cutoff-table-rows" role="table" aria-label="Cutoffs">
        <div className="grade-cutoff-row grade-cutoff-row--head" role="row">
          <span role="columnheader">Grade</span>
          <span role="columnheader">Minimum</span>
          <span role="columnheader">Maximum</span>
          <span role="columnheader">Status</span>
        </div>
        {thresholds.map((t) => {
          const dirty = rowDirty(t.letter);
          const key = t.letter.trim().toLowerCase();
          return (
            <div className="grade-cutoff-row" role="row" key={t.letter} data-threshold-letter={t.letter}>
              <span className="grade-cutoff-row-letter" role="cell">{t.letter}</span>
              <span role="cell">
                <label htmlFor={`cutoff-${t.letter}-min`} className="sr-only">{t.letter} minimum</label>
                <input
                  id={`cutoff-${t.letter}-min`}
                  type="number"
                  inputMode="numeric"
                  className="form-input"
                  placeholder="—"
                  value={draft[`${t.letter}:minimum`] ?? ''}
                  onChange={(e) => setDraft((p) => ({ ...p, [`${t.letter}:minimum`]: e.target.value }))}
                />
              </span>
              <span role="cell">
                <label htmlFor={`cutoff-${t.letter}-max`} className="sr-only">{t.letter} maximum</label>
                <input
                  id={`cutoff-${t.letter}-max`}
                  type="number"
                  inputMode="numeric"
                  className="form-input"
                  placeholder="—"
                  value={draft[`${t.letter}:maximum`] ?? ''}
                  onChange={(e) => setDraft((p) => ({ ...p, [`${t.letter}:maximum`]: e.target.value }))}
                />
              </span>
              <span className="grade-cutoff-row-status" role="cell">
                {dirty ? (
                  <span className="grade-cutoff-row-note">edited — save below</span>
                ) : openValueLetters.has(key) ? (
                  <span className="grade-cutoff-row-affirm">
                    <span className="grade-cutoff-row-note">
                      {t.letter}: {formatThresholdRange(t)} — we couldn't confirm this against your syllabus.
                    </span>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={busy}
                      aria-busy={busy}
                      onClick={() => onSubmitCorrections([{ target_type: 'threshold', operation: 'confirm_threshold_value', threshold_letter: t.letter }])}
                    >
                      Yes, that's correct
                    </button>
                  </span>
                ) : answeredValueLetters.has(key) ? (
                  <span className="grade-cutoff-resolved" data-threshold-letter={t.letter}>
                    ✓ {t.letter} cutoff confirmed as correct.
                  </span>
                ) : null}
              </span>
            </div>
          );
        })}
      </div>

      {answeredResolved.map((r) => (
        <p className="grade-cutoff-resolved" key={`done:${r.winner},${r.loser}`} data-cutoff-pair={`${r.winner},${r.loser}`}>
          ✓ Cutoff conflict resolved: {r.boundary} counts as {r.winner}, not {r.loser}.
        </p>
      ))}

      {anyDirty && (
        <div className="grade-cutoff-question-actions">
          <button type="button" className="btn btn-primary btn-sm" disabled={busy} aria-busy={busy} onClick={handleSave}>
            Save cutoffs
          </button>
          <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => setDraft(serverDraft)}>
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * Read-only by default (the original behavior, unchanged: only categories
 * with a known weight render, in a flat percentage list). `editable` swaps
 * in CategoryWeightEditor -- used only from the "Needs your review" step,
 * where category_weight_validation / unknown_weight are genuinely blocking
 * and need a fix action, not just display.
 */
function SyllabusGradingBreakdown({
  model,
  findingsByAnchor = EMPTY_FINDINGS_BY_ANCHOR,
  dismissedFindingKeys = new Set(),
  onDismissFinding = () => {},
  editable = false,
  detail = null,
  busy = false,
  onSubmitCorrections = () => {},
}: {
  model: SyllabusGradeModel | null;
  findingsByAnchor?: Map<string, FindingWithKey[]>;
  dismissedFindingKeys?: Set<number>;
  onDismissFinding?: (key: number) => void;
  editable?: boolean;
  detail?: SyllabusProfileDetail | null;
  busy?: boolean;
  onSubmitCorrections?: (corrections: SyllabusProfileDetail['corrections']) => void;
}) {
  if (!model) return null;

  if (editable) {
    return <CategoryWeightEditor model={model} detail={detail} busy={busy} onSubmitCorrections={onSubmitCorrections} />;
  }

  const weighted: SyllabusCategory[] = model.categories.filter((c) => c.weight !== null);
  if (weighted.length === 0) return null;
  const total = weighted.reduce((sum, c) => sum + (c.weight ?? 0), 0);
  return (
    <div className="real-course-table" role="table" aria-label="Grading breakdown">
      <h4 className="card-heading">Grading breakdown</h4>
      {weighted.map((c) => (
        <div className="grade-breakdown-row" key={c.name}>
          <div className="real-course-row" role="row">
            <span role="cell">{c.name}</span>
            <span role="cell">{formatPercent(c.weight)}</span>
            <span role="cell" className="grade-evidence-note">
              {c.evidence?.page ? `Source: page ${c.evidence.page}` : ''}
            </span>
          </div>
          <InlineFindings
            findings={findingsByAnchor.get(`category:${c.name}`) ?? []}
            dismissedFindingKeys={dismissedFindingKeys}
            onDismissFinding={onDismissFinding}
          />
        </div>
      ))}
      <div className="real-course-row" role="row">
        <span role="cell"><strong>Total</strong></span>
        <span role="cell"><strong>{total}%</strong></span>
      </div>
    </div>
  );
}

/**
 * Inline-editable category weight/count table, following CutoffTable's
 * pattern exactly: a local draft keyed by field, a per-row dirty check
 * against server truth, a "Save" that diffs the draft and emits only
 * existing corrections (category/set_weight, category/set_count --
 * corrections.py's _apply_category_correction already supports both; no
 * new correction type is introduced here).
 *
 * Renders EVERY category, not just ones with a known weight -- unlike the
 * read-only breakdown above, a category with weight: null (exactly the
 * thing a student needs to fill in to close a sub-100 gap, e.g. a category
 * whose count is known but whose total weight was never stated -- the
 * unknown_weight case) would otherwise never appear at all.
 *
 * category_weight_validation (course-level), unknown_weight (per-category,
 * informational only -- see below), and the per-category claim-evidence
 * pair are all read directly from the raw reconciliation findings --
 * bypassing reviewFindings/findingsByAnchor, the same way CutoffTable reads
 * CLAIM_EVIDENCE_THRESHOLD_CODES findings itself. category_weight_
 * validation renders non-dismissible whenever its OWN instance is blocking
 * (severity !== 'valid'; it's VALID, not WARNING, once weights sum to ~100,
 * so a clean total shows nothing here rather than a stale "not accepted"
 * note). No ADD_CATEGORY / REMOVE_CATEGORY: only categories already in the
 * model can be edited.
 *
 * IMPORTANT lifecycle note, unlike every threshold finding CutoffTable
 * handles: claim_evidence_consistency_unverifiable / claim_evidence_value_
 * mismatch on a category weight do NOT exist at extraction time --
 * _check_category_weight_consistency (reconciliation.py) skips a category
 * outright while its weight is null, so these findings can only appear
 * AFTER a set_weight correction has already been submitted and answered
 * with a fresh server response. `rawFindings` is read from `detail` --
 * component state overwritten with the server's response on every
 * submitCorrections call (see submitCorrections/handleReviewCorrections) --
 * so this reads reactively off the MOST RECENT correction response, not a
 * stale initial-load snapshot; no separate wiring was needed for that.
 *
 * The two claim-evidence codes are handled asymmetrically, mirroring the
 * backend's own asymmetry (reconciliation._check_category_weight_
 * consistency): claim_evidence_consistency_unverifiable (WARNING -- the
 * checker couldn't parse a percent out of the evidence at all) gets the
 * same "Yes, that's correct" affirm CutoffTable offers for thresholds,
 * emitting category/confirm_category_value. claim_evidence_value_mismatch
 * (ERROR -- the evidence WAS parsed and it cites a different number) gets
 * NO affirm button -- the backend deliberately never suppresses it via
 * confirmed_category_value_claims, so offering one here would be a UI
 * promise the backend won't honor. It renders non-dismissible with an
 * explanation instead; the actual fix is editing the weight/count fields
 * above, not affirming past a real contradiction.
 */
function CategoryWeightEditor({
  model,
  detail,
  busy,
  onSubmitCorrections,
}: {
  model: SyllabusGradeModel;
  detail: SyllabusProfileDetail | null;
  busy: boolean;
  onSubmitCorrections: (corrections: SyllabusProfileDetail['corrections']) => void;
}) {
  const categories = model.categories;
  const rawFindings = (detail?.confirmed_reconciliation ?? detail?.reconciliation)?.findings ?? [];

  const totalFinding = rawFindings.find((f) => f.code === 'category_weight_validation') ?? null;

  // unknown_weight is non-blocking (reconciliation.NON_BLOCKING_WARNING_CODES)
  // -- category_weight_validation is what actually gates confirm on this
  // fact. It's kept here rather than moved to the general list because it's
  // still category-scoped info worth anchoring to the right row, but its
  // text ("we couldn't determine this category's weight") goes factually
  // stale the moment `weight` is actually set -- most commonly via this
  // very editor's own set_weight correction, which never clears the
  // warning (only DISMISS_WARNING touches GradeModel.warnings). So it's
  // only shown while weight is still genuinely unknown; once answered, the
  // category's row status is driven by the claim-evidence checks below
  // instead, and this note would just be wrong to keep displaying.
  // Two distinct steps, deliberately not collapsed into one predicate: (1)
  // find the category by name alone, (2) only then decide whether to
  // suppress it. related_field is untyped free text (extraction.py:132,
  // "the category/assessment/rule this concerns") with no guarantee it
  // names a category at all -- it could name an assessment or rule
  // instead, or just not match anything (typo, extraction drift). If both
  // steps were one `&&` condition, a genuine no-match would be
  // indistinguishable from step 2's intentional suppression and both would
  // silently vanish. A real no-match is surfaced instead (see
  // unmatchedUnknownWeightFindings below), never dropped.
  const unknownWeightByCategory = new Map<string, SyllabusFinding>();
  const unmatchedUnknownWeightFindings: SyllabusFinding[] = [];
  for (const f of rawFindings) {
    if (f.code !== 'unknown_weight' || !f.field) continue;
    const match = categories.find((c) => normalizeName(c.name) === normalizeName(f.field as string));
    if (!match) {
      unmatchedUnknownWeightFindings.push(f);
      continue;
    }
    // Suppress once the category's weight is actually known -- the "we
    // couldn't determine this weight" text goes factually stale the moment
    // `weight` is set (most commonly via this editor's own set_weight
    // correction, which never clears the ExtractionWarning backing this
    // finding).
    if (match.weight === null) unknownWeightByCategory.set(match.name, f);
  }

  // Per-category claim-evidence findings -- see the component docstring for
  // why these can only appear after a set_weight correction, and why the
  // two codes are handled asymmetrically. `answers` mirrors CutoffTable's
  // clarifying-answer lookup, but under the SEPARATE 'claim_evidence:
  // category:' key namespace (categoryValueClaimKey), never the threshold
  // one.
  const answers = detail?.clarifying_answers ?? {};
  const openCategoryValueClaims = new Map<string, SyllabusFinding>();
  const categoryMismatchByName = new Map<string, SyllabusFinding>();
  for (const f of rawFindings) {
    if (!CLAIM_EVIDENCE_THRESHOLD_CODES.has(f.code)) continue;
    const name = categoryClaimEvidenceCategoryName(f);
    if (!name) continue;
    const match = categories.find((c) => normalizeName(c.name) === normalizeName(name));
    if (!match) continue;
    if (f.code === 'claim_evidence_value_mismatch') {
      // Never affirmable -- reconciliation._check_category_weight_consistency
      // only suppresses claim_evidence_consistency_unverifiable, deliberately
      // narrower than the threshold path. No key is ever written for this
      // one, so there's no "answered" state to check here.
      categoryMismatchByName.set(match.name, f);
    } else if (!(categoryValueClaimKey(match.name) in answers)) {
      openCategoryValueClaims.set(match.name, f);
    }
  }
  const answeredCategoryValueClaims = new Set(
    Object.keys(answers)
      .filter((k) => k.startsWith('claim_evidence:category:'))
      .map((k) => (answers[k]?.category_name ?? k.slice('claim_evidence:category:'.length)).trim().toLowerCase()),
  );

  // Server-truth draft, same pattern as CutoffTable's serverDraft/draft
  // pair: recomputed only when the categories themselves change (a
  // correction submit brought back a new model), preserving any in-progress
  // edit to a field the student hasn't touched.
  const serverDraft = useMemo((): Record<string, string> => {
    const d: Record<string, string> = {};
    for (const c of categories) {
      d[`${c.name}:weight`] = c.weight != null ? String(c.weight) : '';
      d[`${c.name}:count`] = c.count != null ? String(c.count) : '';
    }
    return d;
  }, [categories]);
  const [draft, setDraft] = useState<Record<string, string>>(serverDraft);

  const prevServerDraft = useRef(serverDraft);
  useEffect(() => {
    if (prevServerDraft.current === serverDraft) return;
    const prevServer = prevServerDraft.current;
    prevServerDraft.current = serverDraft;
    setDraft((current) => {
      const next: Record<string, string> = {};
      for (const key of Object.keys(serverDraft)) {
        const userEdited = (current[key] ?? '') !== (prevServer[key] ?? '');
        next[key] = userEdited ? (current[key] ?? '') : serverDraft[key];
      }
      return next;
    });
  }, [serverDraft]);

  function rowDirty(name: string): boolean {
    return (draft[`${name}:weight`] ?? '') !== (serverDraft[`${name}:weight`] ?? '')
      || (draft[`${name}:count`] ?? '') !== (serverDraft[`${name}:count`] ?? '');
  }
  const anyDirty = categories.some((c) => rowDirty(c.name));

  // Live running total: a category contributes its typed draft weight if
  // one is present, otherwise its server weight, otherwise nothing (same
  // "unweighted categories don't count" semantics the read-only breakdown's
  // own total already uses) -- so the gap visibly closes keystroke by
  // keystroke, before Save is ever clicked.
  let liveTotal = 0;
  let anyWeighted = false;
  for (const c of categories) {
    const raw = (draft[`${c.name}:weight`] ?? '').trim();
    if (raw !== '') {
      const value = Number(raw);
      if (!Number.isNaN(value)) {
        liveTotal += value;
        anyWeighted = true;
        continue;
      }
    }
    if (c.weight != null) {
      liveTotal += c.weight;
      anyWeighted = true;
    }
  }
  const roundedTotal = Math.round(liveTotal * 100) / 100;
  const gap = Math.round((100 - liveTotal) * 100) / 100;

  function handleSave() {
    const corrections = categoryWeightEditCorrections(categories, draft);
    if (corrections.length > 0) onSubmitCorrections(corrections);
  }

  if (categories.length === 0) return null;

  return (
    <div className="grade-weight-table" data-testid="category-weight-table" aria-label="Grading breakdown">
      <h4 className="card-heading">Grading breakdown</h4>
      <p className="empty-state">Check each category's weight and count against your syllabus. Edit any value that's wrong.</p>

      {totalFinding && totalFinding.severity !== 'valid' && (
        <InlineFinding finding={totalFinding} onDismiss={() => {}} dismissible={false} />
      )}

      {/* related_field named something that doesn't match any category in
          this model -- can't anchor it to a row, so it renders here instead
          of disappearing. unknown_weight is non-blocking backend-side, so
          this is purely informational: no affirm affordance, no blocking
          styling (plain warning glyph, same as every other unknown_weight
          note). Custom copy (not findingCopy's generic text) so the student
          sees exactly what the extractor said, verbatim. */}
      {unmatchedUnknownWeightFindings.map((f, i) => (
        <p
          key={`unmatched-unknown-weight-${i}`}
          className="grade-inline-finding grade-inline-finding--warning"
          data-finding-code={f.code}
        >
          <span className="grade-inline-finding-glyph" aria-hidden="true">·</span>
          <span className="grade-inline-finding-text">
            The syllabus doesn't state a weight for "{f.field}", but CampusIQ couldn't match that to one of the categories below.
          </span>
        </p>
      ))}

      <div className="grade-weight-table-rows" role="table" aria-label="Category weights">
        <div className="grade-weight-row grade-weight-row--head" role="row">
          <span role="columnheader">Category</span>
          <span role="columnheader">Weight</span>
          <span role="columnheader">Count</span>
          <span role="columnheader">Status</span>
        </div>
        {categories.map((c) => {
          const dirty = rowDirty(c.name);
          const unknownWeight = unknownWeightByCategory.get(c.name);
          const mismatch = categoryMismatchByName.get(c.name);
          const openClaim = openCategoryValueClaims.get(c.name);
          const answered = answeredCategoryValueClaims.has(normalizeName(c.name));
          return (
            <div className="grade-weight-row" role="row" key={c.name} data-category-name={c.name}>
              <span className="grade-weight-row-name" role="cell">{c.name}</span>
              <span role="cell">
                <label htmlFor={`weight-${c.name}`} className="sr-only">{c.name} weight</label>
                <input
                  id={`weight-${c.name}`}
                  type="number"
                  inputMode="decimal"
                  className="form-input"
                  placeholder="—"
                  value={draft[`${c.name}:weight`] ?? ''}
                  onChange={(e) => setDraft((p) => ({ ...p, [`${c.name}:weight`]: e.target.value }))}
                />
              </span>
              <span role="cell">
                <label htmlFor={`count-${c.name}`} className="sr-only">{c.name} count</label>
                <input
                  id={`count-${c.name}`}
                  type="number"
                  inputMode="numeric"
                  className="form-input"
                  placeholder="—"
                  value={draft[`${c.name}:count`] ?? ''}
                  onChange={(e) => setDraft((p) => ({ ...p, [`${c.name}:count`]: e.target.value }))}
                />
              </span>
              <span className="grade-weight-row-status" role="cell">
                {dirty ? (
                  <span className="grade-cutoff-row-note">edited — save below</span>
                ) : mismatch ? (
                  // ERROR, never affirmable -- see the component docstring.
                  <InlineFinding finding={mismatch} onDismiss={() => {}} dismissible={false} />
                ) : openClaim ? (
                  <span className="grade-cutoff-row-affirm">
                    <span className="grade-cutoff-row-note">
                      We couldn't confirm {c.name}'s weight against your syllabus.
                    </span>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={busy}
                      aria-busy={busy}
                      onClick={() =>
                        onSubmitCorrections([
                          { target_type: 'category', operation: 'confirm_category_value', category_name: c.name },
                        ])
                      }
                    >
                      Yes, that's correct
                    </button>
                  </span>
                ) : answered ? (
                  <span className="grade-cutoff-resolved" data-category-name={c.name}>
                    ✓ {c.name} weight confirmed as correct.
                  </span>
                ) : unknownWeight ? (
                  <InlineFinding finding={unknownWeight} onDismiss={() => {}} dismissible={false} />
                ) : null}
              </span>
            </div>
          );
        })}
      </div>

      <p className="grade-weight-total" aria-live="polite">
        <strong>Total: {anyWeighted ? `${roundedTotal}%` : '—'}</strong>
        {anyWeighted && Math.abs(gap) > 0.01 && (
          <span className="grade-weight-total-gap">
            {gap > 0 ? ` — ${gap}% short of 100%` : ` — ${Math.abs(gap)}% over 100%`}
          </span>
        )}
      </p>

      {anyDirty && (
        <div className="grade-cutoff-question-actions">
          <button type="button" className="btn btn-primary btn-sm" disabled={busy} aria-busy={busy} onClick={handleSave}>
            Save weights
          </button>
          <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => setDraft(serverDraft)}>
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}

function SyllabusRulesList({
  model,
  findingsByAnchor = EMPTY_FINDINGS_BY_ANCHOR,
  dismissedFindingKeys = new Set(),
  onDismissFinding = () => {},
}: {
  model: SyllabusGradeModel | null;
  findingsByAnchor?: Map<string, FindingWithKey[]>;
  dismissedFindingKeys?: Set<number>;
  onDismissFinding?: (key: number) => void;
}) {
  if (!model || model.rules.length === 0) return null;
  return (
    <div className="grade-rules-list">
      <h4 className="card-heading">Special grading rules</h4>
      {model.rules.map((rule, index) => {
        const isDeterministic = rule.rule_type === 'replacement' && rule.source && rule.target;
        return (
          <div className="grade-rule-card" key={index}>
            <p className="grade-rule-title">{ruleTypeLabel(rule.rule_type)}</p>
            <p>{rule.description}</p>
            {rule.evidence?.page && <p className="grade-evidence-note">Source: page {rule.evidence.page}</p>}
            {!isDeterministic && (
              <p className="empty-state">The syllabus does not provide enough information for CampusIQ to calculate this rule.</p>
            )}
            <InlineFindings
              findings={findingsByAnchor.get(`rule:${index}`) ?? []}
              dismissedFindingKeys={dismissedFindingKeys}
              onDismissFinding={onDismissFinding}
            />
          </div>
        );
      })}
    </div>
  );
}

/**
 * Persistent "Professor's rules" reference panel, shown beside the What-If
 * calculator. Renders the informational grading policies (curve, late
 * work, makeup, extra credit, other) straight from the grade model's
 * rules[] -- NOT from the reconciliation findings array. Per the
 * syllabus-review redesign (planning-docs/syllabus-review-redesign-spec.md
 * §2C): these are facts to see while running scenarios, never things to
 * resolve or dismiss, so there's no dismiss control and no blocking
 * behavior. Deterministic replacement/drop rules are executed by the
 * calculator and reported in its own output, so they're not repeated here.
 */
function ProfessorsRules({ model }: { model: SyllabusGradeModel | null }) {
  const rules = (model?.rules ?? []).filter((rule) => PROFESSOR_RULE_TYPES.has(rule.rule_type));
  if (rules.length === 0) return null;
  return (
    <div className="card professors-rules" data-testid="professors-rules" aria-label="Professor's rules">
      <h3 className="card-heading">Professor's rules</h3>
      {rules.map((rule, index) => (
        <div className="professors-rule" key={index}>
          <p className="professors-rule-type">{ruleTypeLabel(rule.rule_type)}</p>
          <p className="professors-rule-text">{rule.description}</p>
          {rule.evidence?.page && <p className="grade-evidence-note">Source: page {rule.evidence.page}</p>}
        </div>
      ))}
    </div>
  );
}
