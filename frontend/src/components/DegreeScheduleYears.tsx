import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  addPlannedCourse,
  fetchCrossListings,
  fetchGradingSchema,
  fetchPlannedCourses,
  fetchTerms,
  removePlannedCourse,
} from '../api/planning';
import type { AnalysisIdentity } from '../api/analysisApi.mjs';
import type {
  CandidateCourseDisplay,
  RequirementCandidate,
  RequirementCandidateSet,
  RequirementDecision,
} from '../api/degreeSchedule.mjs';
import {
  existingCourseStatusIndex,
} from '../lib/termPlanning.mjs';
import type {
  CatalogSearchResult,
  CrossListingMap,
  ExistingCourseStatus,
  GradingSchema,
  PlannedCourse,
  PlanningTerm,
} from '../lib/termPlanning.mjs';
import { buildDegreeScheduleYears } from '../lib/degreeScheduleYears.mjs';
import type { DegreeScheduleSemester, DegreeScheduleTermDecision, DegreeScheduleYear } from '../lib/degreeScheduleYears.mjs';
import { displayTermKey, formatCredits } from '../lib/degreeSchedulePresentation.mjs';
import type { TermPlan } from '../api/degreeSchedule.mjs';
import { EditCoursesDialog } from './EditCoursesDialog';

interface CourseRecordLike {
  id: string;
  term_id: string | null;
  course_code: string;
  title: string | null;
  credit_hours: number | string;
  letter_grade: string | null;
  status: string;
}

type DecisionAction = 'choose' | 'change' | 'clear' | 'restore';

export interface DegreeScheduleChoiceMutation {
  requirementGroupId: string;
  action: DecisionAction;
  candidateId?: string;
}

interface DegreeScheduleYearsProps {
  accessToken: string;
  scheduleTerms: TermPlan[];
  courses: CourseRecordLike[];
  // Phase 3: the decision evidence the backend serializes alongside the
  // schedule. LOCKED/CHOICE_REQUIRED/EXCLUDED decisions render on the term
  // card the backend resolved for each; everything else is ignored here.
  decisions: RequirementDecision[];
  candidateSets: RequirementCandidateSet[];
  mutation: DegreeScheduleChoiceMutation | null;
  onChoose: (requirementGroupId: string, candidate: RequirementCandidate, action: 'choose' | 'change') => void;
  onClear: (requirementGroupId: string) => void;
  onRestore: (requirementGroupId: string) => void;
}

// The per-course rows shared by a decision option's box (DecisionCandidatePath,
// below) and a LOCKED card's bare course list (TermDecisionCard) -- identical
// row shape either way, only the surrounding wrapper (bordered "Option N" box
// vs. no box at all) differs.
function CandidateCourseRows({ courses }: { courses: CandidateCourseDisplay[] }) {
  return (
    <>
      {courses.map((course) => (
        <li key={course.course_code}>
          {/* The exact .degree-schedule-course-row shape the Fall/planned
              lists use, so a decision option's courses read as the same
              kind of row. With the backend tree-traversal fix (a3c4746)
              real title + credits arrive by default; 'Credits unavailable'
              is now the genuine-exception path (an unresolved course code),
              not the common case -- if it fires constantly, something
              upstream is still wrong. */}
          <div className="degree-schedule-course-row">
            <span>
              <strong>{course.course_code}</strong>
              {course.title && <small>{course.title}</small>}
            </span>
            <span>{course.credits !== null ? `${course.credits} credits` : 'Credits unavailable'}</span>
          </div>
          {/* Prospective -- these courses enter the plan only if this option
              is chosen -- so the same marker a confirmed planned row carries,
              in the institution accent rather than --added's achromatic grey.
              Sibling of the row div (stacked below), matching the Fall list. */}
          <span className="degree-schedule-badge degree-schedule-badge--decision">Planned course</span>
        </li>
      ))}
    </>
  );
}

// One grouped academic path inside a decision card. Trimmed from the retired
// DegreeScheduleDecisionSection's CandidatePath -- same markup/classes so the
// existing candidate-path CSS carries over unchanged.
function DecisionCandidatePath({ candidate, optionNumber, requirementName, selected, changing, busy, loading, onChoose }: {
  candidate: RequirementCandidate;
  optionNumber: number;
  requirementName: string;
  selected: boolean;
  changing: boolean;
  busy: boolean;
  loading: boolean;
  onChoose: () => void;
}) {
  const isMultiCourse = candidate.candidate_courses.length > 1;
  return (
    <li className={`degree-schedule-candidate-path${selected ? ' is-selected' : ''}`}>
      <div className="degree-schedule-candidate-header">
        <strong>Option {optionNumber}</strong>
        {selected && <span className="degree-schedule-selected-label">Selected</span>}
        {isMultiCourse && candidate.additional_credits !== null && <span>{formatCredits(candidate.additional_credits)} total</span>}
      </div>
      <ul className="degree-schedule-candidate-courses" aria-label={`Courses included in option ${optionNumber}`}>
        <CandidateCourseRows courses={candidate.candidate_courses} />
      </ul>
      {!selected && (
        <div className="degree-schedule-candidate-action">
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy} aria-busy={loading}
            aria-label={`${changing ? 'Change to' : 'Choose'} ${candidate.course_codes.join(' and ')} for ${requirementName}`}
            onClick={onChoose}>
            {loading ? `${changing ? 'Changing' : 'Choosing'}…` : `${changing ? 'Change to' : 'Choose'} option`}
          </button>
        </div>
      )}
    </li>
  );
}

// A single relocated decision, rendered inside its resolved term column
// alongside the scheduled/planned/suggested rows.
function TermDecisionCard({ decision, mutation, onChoose, onClear, onRestore }: {
  decision: DegreeScheduleTermDecision;
  mutation: DegreeScheduleChoiceMutation | null;
  onChoose: (requirementGroupId: string, candidate: RequirementCandidate, action: 'choose' | 'change') => void;
  onClear: (requirementGroupId: string) => void;
  onRestore: (requirementGroupId: string) => void;
}) {
  const [changing, setChanging] = useState(false);
  const busy = mutation !== null;
  const rgid = decision.requirementGroupId;
  const rowBusy = mutation?.requirementGroupId === rgid;
  const { requirementName, candidates, selectedCandidateId } = decision;

  if (decision.state === 'LOCKED') {
    const selected = candidates.find((candidate) => candidate.candidate_id === selectedCandidateId) ?? candidates[0] ?? null;
    return (
      // While changing, this is functionally a CHOICE_REQUIRED menu (a real
      // set of Option N boxes to pick from) so it keeps that boxed
      // decision-card treatment unchanged. Not-changing is the true LOCKED
      // resting view -- full visual parity with the Fall/planned plain rows
      // it sits beside: no border, no background, no "Selected" label, no
      // per-group credits total (see degree-schedule-locked-decision below).
      <li className={changing ? 'degree-schedule-decision-card is-locked degree-schedule-term-decision' : 'degree-schedule-locked-decision degree-schedule-term-decision'}>
        {changing && (
          <div className="degree-schedule-decision-heading">
            <h6>{requirementName}</h6>
            <div><strong>Selected</strong></div>
          </div>
        )}
        {/* The resting (non-changing) view carries no heading at all -- the
            requirement name moved to a "Required courses" note in the term
            header instead (SemesterColumn), since a per-card heading here
            was the last thing keeping this from reading as a plain row. */}
        {changing ? (
          <ol className="degree-schedule-candidate-list">
            {candidates.map((candidate, index) => (
              <DecisionCandidatePath key={candidate.candidate_id} candidate={candidate} optionNumber={index + 1}
                requirementName={requirementName} selected={candidate.candidate_id === selectedCandidateId}
                changing busy={busy} loading={mutation?.candidateId === candidate.candidate_id}
                onChoose={() => onChoose(rgid, candidate, 'change')} />
            ))}
          </ol>
        ) : selected ? (
          // A LOCKED, not-changing card has exactly one candidate -- the
          // "Option 1" heading and its bordered box existed only to
          // distinguish between candidates, which there's nothing to do here.
          // Course rows render directly inside the outer card instead.
          <ul className="degree-schedule-candidate-courses" aria-label={`Courses satisfying ${requirementName}`}>
            <CandidateCourseRows courses={selected.candidate_courses} />
          </ul>
        ) : null}
        <div className="degree-schedule-choice-actions">
          <button type="button" className={changing ? 'btn btn-secondary btn-sm' : 'degree-schedule-text-action'} disabled={busy}
            onClick={() => setChanging((value) => !value)}>
            {changing ? 'Cancel change' : 'Change choice'}
          </button>
          <button type="button" className={changing ? 'btn btn-ghost btn-sm' : 'degree-schedule-text-action'} disabled={busy}
            aria-busy={rowBusy && mutation?.action === 'clear'}
            onClick={() => onClear(rgid)}>
            {rowBusy && mutation?.action === 'clear' ? 'Clearing…' : 'Clear choice'}
          </button>
        </div>
      </li>
    );
  }

  if (decision.state === 'EXCLUDED') {
    const codes = [...new Set(candidates.flatMap((candidate) => candidate.course_codes))];
    return (
      <li className="degree-schedule-decision-card degree-schedule-term-decision">
        <div className="degree-schedule-decision-heading">
          <h6>{requirementName}</h6>
          <div><strong>Set aside</strong><span>{`Est. ${displayTermKey(decision.termKey)}`}</span></div>
        </div>
        {codes.length > 0 && <p className="degree-schedule-term-decision-codes">{codes.join(', ')}</p>}
        <p>You set this requirement aside. It's still required. The term shown is an estimate of where it would land, not a confirmed placement — add it back to schedule it.</p>
        <div className="degree-schedule-choice-actions">
          <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
            aria-busy={rowBusy && mutation?.action === 'restore'}
            onClick={() => onRestore(rgid)}>
            {rowBusy && mutation?.action === 'restore' ? 'Adding…' : 'Add it back'}
          </button>
        </div>
      </li>
    );
  }

  // CHOICE_REQUIRED
  return (
    <li className="degree-schedule-decision-card degree-schedule-term-decision">
      <div className="degree-schedule-decision-heading">
        <h6>{requirementName}</h6>
        <div><strong>Choice required</strong><span>{`${candidates.length} valid option${candidates.length === 1 ? '' : 's'}`}</span></div>
      </div>
      <p>Pick an option to schedule this requirement. This term is an estimate — it may shift depending on which option you choose.</p>
      <ol className="degree-schedule-candidate-list">
        {candidates.map((candidate, index) => (
          <DecisionCandidatePath key={candidate.candidate_id} candidate={candidate} optionNumber={index + 1}
            requirementName={requirementName} selected={false} changing={false}
            busy={busy} loading={mutation?.candidateId === candidate.candidate_id}
            onChoose={() => onChoose(rgid, candidate, 'choose')} />
        ))}
      </ol>
    </li>
  );
}

function SemesterColumn({ semester, identity, busyCode, mutation, isEditOpen, onOpenEdit, onCloseEdit, onAdd, onRemove, onChoose, onClear, onRestore, crossListings, existingCourseIndex }: {
  semester: DegreeScheduleSemester;
  identity: AnalysisIdentity;
  busyCode: string | null;
  mutation: DegreeScheduleChoiceMutation | null;
  // Only one "Edit courses" popup may be open across the whole grid, so which
  // term (if any) owns it is lifted to DegreeScheduleYears -- this column just
  // reports whether it's the open one and asks to open/close.
  isEditOpen: boolean;
  onOpenEdit: () => void;
  onCloseEdit: () => void;
  onAdd: (semester: DegreeScheduleSemester, result: CatalogSearchResult) => void;
  onRemove: (id: string) => void;
  onChoose: (requirementGroupId: string, candidate: RequirementCandidate, action: 'choose' | 'change') => void;
  onClear: (requirementGroupId: string) => void;
  onRestore: (requirementGroupId: string) => void;
  /** See CourseSearchAdd -- fetched once by DegreeScheduleYears, passed through unchanged. */
  crossListings: CrossListingMap;
  existingCourseIndex: Map<string, ExistingCourseStatus>;
}) {
  const editTriggerRef = useRef<HTMLButtonElement>(null);

  const addedCodes = useMemo(
    () => new Set(semester.planned.map((course) => course.course_code.toUpperCase())),
    [semester.planned],
  );

  // The LOCKED card's own heading was removed for full Fall-row parity (see
  // TermDecisionCard); this is where that "there's a required-courses
  // decision here" signal now lives instead -- folded into the same header
  // span as totalCreditsLabel, not a new competing label.
  const hasLockedDecision = semester.decisions.some((decision) => decision.state === 'LOCKED');

  // Closing always returns focus to the trigger, per the dialog a11y contract.
  // Both the footer "Confirm" button and Escape route through here.
  const closeEdit = useCallback(() => {
    onCloseEdit();
    editTriggerRef.current?.focus();
  }, [onCloseEdit]);

  return (
    <section className="degree-schedule-semester" aria-label={`${semester.season} ${semester.termKey.split('-')[0]}`}>
      <div className="degree-schedule-semester-header">
        <h5>{semester.season}</h5>
        <span>{hasLockedDecision ? `${semester.totalCreditsLabel ?? '—'} · Required courses` : (semester.totalCreditsLabel ?? '—')}</span>
      </div>

      {(semester.state === 'past' || semester.state === 'in_progress') && (
        semester.courses.length === 0 ? (
          <p className="empty-state">No confirmed coursework this term.</p>
        ) : (
          <ul className="degree-schedule-semester-courses">
            {semester.courses.map((course) => (
              <li key={course.course_code} className="degree-schedule-semester-course">
                <div className="degree-schedule-course-row">
                  <span>
                    <strong>{course.course_code}</strong>
                    {course.title && <small>{course.title}</small>}
                  </span>
                  <span>{course.credit_hours} credits</span>
                </div>
                {semester.state === 'in_progress' ? (
                  <span className="degree-schedule-badge degree-schedule-badge--in-progress">In progress</span>
                ) : (
                  course.gradeBadge && (
                    <span className="degree-schedule-badge degree-schedule-badge--grade">{course.gradeBadge}</span>
                  )
                )}
              </li>
            ))}
          </ul>
        )
      )}

      {semester.state === 'future' && (
        <>
          {semester.decisions.length > 0 && (
            <ul className="degree-schedule-term-decisions">
              {semester.decisions.map((decision) => (
                <TermDecisionCard
                  key={decision.requirementGroupId}
                  decision={decision}
                  mutation={mutation}
                  onChoose={onChoose}
                  onClear={onClear}
                  onRestore={onRestore}
                />
              ))}
            </ul>
          )}

          {/* Keys on planned + decisions only. Scheduler headroom no longer
              renders on the card -- it moved into the Edit-courses popup --
              and "No courses confirmed yet." stays literally true whether or
              not the scheduler produced any, so a term that has only headroom
              should still show this line pointing at the Edit courses button
              rather than a bare, contextless button. */}
          {semester.planned.length === 0 && semester.decisions.length === 0 && (
            <p className="empty-state">No courses confirmed yet.</p>
          )}

          {/* Read-only on the card: code / credits / "Added" badge. Adding and
              removing both live in the Edit-courses popup now (the Remove
              button moved there), so the card stays a summary. */}
          {semester.planned.length > 0 && (
            <ul className="degree-schedule-semester-courses">
              {semester.planned.map((course) => (
                <li key={course.id} className="degree-schedule-semester-course">
                  <div className="degree-schedule-course-row">
                    <span>
                      <strong>{course.course_code}</strong>
                      {course.title && <small>{course.title}</small>}
                    </span>
                    <span>{course.credit_hours === null ? 'Credits TBD' : `${course.credit_hours} credits`}</span>
                  </div>
                  <div className="degree-schedule-course-row">
                    <span className="degree-schedule-badge degree-schedule-badge--added">Added</span>
                  </div>
                </li>
              ))}
            </ul>
          )}

          <div className="degree-schedule-suggested degree-schedule-add">
            <button
              ref={editTriggerRef}
              type="button"
              className="btn btn-secondary btn-sm"
              aria-haspopup="dialog"
              onClick={onOpenEdit}
            >
              Edit courses
            </button>
          </div>

          {isEditOpen && (
            <EditCoursesDialog
              termKey={semester.termKey}
              termLabel={displayTermKey(semester.termKey)}
              identity={identity}
              plannedCourses={semester.planned}
              suggestedCourses={semester.suggestedCourses}
              alreadyAddedCodes={addedCodes}
              crossListings={crossListings}
              existingCourseIndex={existingCourseIndex}
              busyCode={busyCode}
              onAdd={(result) => onAdd(semester, result)}
              onRemove={onRemove}
              onClose={closeEdit}
            />
          )}
        </>
      )}
    </section>
  );
}

export function DegreeScheduleYears({
  accessToken,
  scheduleTerms,
  courses,
  decisions,
  candidateSets,
  mutation,
  onChoose,
  onClear,
  onRestore,
}: DegreeScheduleYearsProps) {
  const [terms, setTerms] = useState<PlanningTerm[]>([]);
  const [gradingSchema, setGradingSchema] = useState<GradingSchema | null>(null);
  const [crossListings, setCrossListings] = useState<CrossListingMap>({});
  const [planned, setPlanned] = useState<PlannedCourse[]>([]);
  const [busyCode, setBusyCode] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);
  const [activeYearKey, setActiveYearKey] = useState<number | null>(null);
  // The termKey of the one future term whose "Edit courses" popup is open, or
  // null. A single value is the whole single-popup-at-a-time guarantee:
  // opening another term's popup just reassigns it.
  const [editingTermKey, setEditingTermKey] = useState<string | null>(null);
  const handleCloseEdit = useCallback(() => setEditingTermKey(null), []);

  const identity = useMemo<AnalysisIdentity>(() => ({ slug: null, accessToken }), [accessToken]);

  // Real academic terms and the institution's grade map -- the two pieces
  // of context TermPlanner already self-fetches for the same purpose.
  // schedule.terms and course_records both arrive as props: they are
  // already loaded by DegreeSchedulePanel and the dashboard respectively,
  // so fetching them again here would just be a second copy of the same
  // request in flight. planned_courses has no such prop, so it is fetched
  // here (full list, no term filter), matching realTerms/gradingSchema.
  const loadTerms = useCallback(async () => {
    const result = await fetchTerms(identity);
    setTerms(result.terms);
  }, [identity]);

  const loadPlanned = useCallback(async () => {
    const result = await fetchPlannedCourses(identity);
    setPlanned(result.plannedCourses);
  }, [identity]);

  useEffect(() => { void loadTerms(); }, [loadTerms]);
  useEffect(() => { void loadPlanned(); }, [loadPlanned]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const result = await fetchGradingSchema(identity);
      if (!cancelled) setGradingSchema(result.schema);
    })();
    return () => { cancelled = true; };
  }, [identity]);

  // Fetched once and cached, same shape as gradingSchema -- see
  // fetchCrossListings. Powers the cross-listing-aware duplicate check in
  // CourseSearchAdd (a course already in progress/completed/planned under
  // its OTHER departmental code must not look freely addable).
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const result = await fetchCrossListings(identity);
      if (!cancelled) setCrossListings(result.crossListings);
    })();
    return () => { cancelled = true; };
  }, [identity]);

  // Student-wide (every term, not just the one being edited): a course
  // already in progress/completed anywhere in course_records, or already
  // planned anywhere in planned_courses. See existingCourseStatusIndex.
  const existingCourseIndex = useMemo(
    () => existingCourseStatusIndex(courses, planned),
    [courses, planned],
  );

  // Captured once per mount, matching TermPlanner's reasoning: a semester's
  // state must not change mid-render as the clock ticks past midnight.
  const today = useMemo(() => new Date(), []);

  const years: DegreeScheduleYear[] = useMemo(
    () => buildDegreeScheduleYears({
      realTerms: terms,
      scheduleTerms,
      courseRecords: courses,
      gradingSchema,
      today,
      plannedCourses: planned,
      decisions,
      candidateSets,
      crossListings,
    }),
    [terms, scheduleTerms, courses, gradingSchema, today, planned, decisions, candidateSets, crossListings],
  );

  const handleAddPlanned = useCallback(async (semester: DegreeScheduleSemester, result: CatalogSearchResult) => {
    setBusyCode(result.code);
    setAddError(null);
    const year = Number(semester.termKey.split('-')[0]);
    const response = await addPlannedCourse(identity, {
      course_code: result.code,
      year,
      season: semester.season,
      term_label: `${semester.season} ${year}`,
      title: result.title,
      // Only a fixed-credit course carries its hours across, matching
      // TermPlanner: a variable-credit course is left null rather than
      // guessing which end of the range the student registers for.
      credit_hours:
        result.credit_min !== null && result.credit_min === result.credit_max
          ? result.credit_min
          : null,
      catalog_course_id: result.id,
      force_planned: true,
    });
    setBusyCode(null);
    if (!response.ok) {
      setAddError(response.message ?? 'Could not add that course to your plan.');
      return;
    }
    // Adding to a term the student had never enrolled in creates its
    // academic_terms row, so refetch terms too -- the planned row is matched
    // against realTerm.id, which may only now exist.
    await Promise.all([loadPlanned(), loadTerms()]);
  }, [identity, loadPlanned, loadTerms]);

  const handleRemovePlanned = useCallback(async (id: string) => {
    setAddError(null);
    const response = await removePlannedCourse(identity, id);
    if (!response.ok) {
      setAddError('Could not remove that course.');
      return;
    }
    await loadPlanned();
  }, [identity, loadPlanned]);

  const inProgressYearKey = useMemo(() => {
    const withCurrentTerm = years.find((year) => year.semesters.some((s) => s.state === 'in_progress'));
    return withCurrentTerm?.yearKey ?? null;
  }, [years]);

  useEffect(() => {
    if (years.length === 0) return;
    const stillValid = years.some((year) => year.yearKey === activeYearKey);
    if (stillValid) return;
    setActiveYearKey(inProgressYearKey ?? years[0].yearKey);
    // Only re-picks when the current selection stops existing (e.g. first
    // load) -- a student clicking between tabs must not get bounced back.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [years, inProgressYearKey]);

  if (years.length === 0) {
    return <p className="empty-state">No academic years on record or scheduled yet.</p>;
  }

  const activeYear = years.find((year) => year.yearKey === activeYearKey) ?? years[0];

  return (
    <div className="degree-schedule-years">
      <div className="academic-tabs" role="tablist" aria-label="Academic years">
        {years.map((year) => (
          <button
            key={year.yearKey}
            type="button"
            role="tab"
            id={`degree-schedule-year-tab-${year.yearKey}`}
            aria-selected={activeYear.yearKey === year.yearKey}
            aria-controls={`degree-schedule-year-panel-${year.yearKey}`}
            className={`academic-tab${activeYear.yearKey === year.yearKey ? ' academic-tab--active' : ''}`}
            onClick={() => { setActiveYearKey(year.yearKey); setEditingTermKey(null); }}
          >
            {year.label}
          </button>
        ))}
      </div>

      {addError && <p className="term-planner-error" role="alert">{addError}</p>}

      <div
        role="tabpanel"
        id={`degree-schedule-year-panel-${activeYear.yearKey}`}
        aria-labelledby={`degree-schedule-year-tab-${activeYear.yearKey}`}
        className="degree-schedule-year-columns"
      >
        {activeYear.semesters.map((semester) => (
          <SemesterColumn
            key={semester.termKey}
            semester={semester}
            identity={identity}
            busyCode={busyCode}
            mutation={mutation}
            isEditOpen={editingTermKey === semester.termKey}
            onOpenEdit={() => setEditingTermKey(semester.termKey)}
            onCloseEdit={handleCloseEdit}
            onAdd={handleAddPlanned}
            onRemove={handleRemovePlanned}
            onChoose={onChoose}
            onClear={onClear}
            onRestore={onRestore}
            crossListings={crossListings}
            existingCourseIndex={existingCourseIndex}
          />
        ))}
      </div>
    </div>
  );
}
