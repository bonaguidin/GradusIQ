import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  TERM_STATUS_LABELS,
  currentGradeOptions,
  existingCourseStatusIndex,
  finalGradeOptions,
  formatTermDates,
  isTermActivated,
  pickDefaultTermKey,
  plannedCodes,
  termCourseGroups,
  termStatus,
} from '../lib/termPlanning.mjs';
import type {
  CatalogSearchResult,
  CrossListingMap,
  GradingSchema,
  PendingFinalGrade,
  PlannedCourse,
  PlanningTerm,
} from '../lib/termPlanning.mjs';
import {
  addPlannedCourse,
  editInProgressCourse,
  fetchCrossListings,
  fetchGradingSchema,
  fetchPendingFinalGrades,
  fetchPlannedCourses,
  fetchTerms,
  finalizeCourseGrade,
  removePlannedCourse,
} from '../api/planning';
import type { AnalysisIdentity } from '../api/analysisApi.mjs';
import { CourseSearchAdd } from './CourseSearchAdd';

/**
 * The Academic Record's term view: a term dropdown, that term's coursework, and
 * -- for a term that has not started -- a search box for planning courses.
 *
 * TWO DATA SOURCES, NEVER CONFLATED. Completed and in-progress rows come from
 * course_records via the profile the dashboard already holds. Planned rows come
 * from planned_courses, a different table, fetched here. A planned course
 * carries no grade, has not been verified against a transcript, and counts
 * toward nothing, so it always keeps its own badge, its own dashed styling and
 * its Remove control -- whichever list it is sitting in.
 *
 * WHERE THEY SIT DEPENDS ON THE TERM. For the upcoming term (`is_upcoming`,
 * computed server-side in term_view.py) planned rows render inside Coursework,
 * after the confirmed ones: that term is the student's working set, and reading
 * "what am I taking next semester" out of two stacked tables is reading one
 * list that happens to be split. For any term further out, planned rows stay in
 * their own Planned section -- there is no confirmed coursework to interleave
 * with yet, and the separation is what makes a speculative term legible as
 * speculative.
 *
 * Note that `is_upcoming` is NOT the same predicate as termStatus()'s
 * 'upcoming'. The latter means "has not started", which is true of every future
 * term; is_upcoming names the single next one. The search box gates on the
 * former (planning is offered for any term not yet begun); this merge gates on
 * the latter.
 */

interface TermPlannerProps {
  /**
   * The session identity, passed as two primitives rather than a prebuilt
   * `{ slug, accessToken }` object. A parent that constructs that object inline
   * hands a fresh reference on every render; this component's terms-loading
   * effect keys on it, so an unstable identity re-fires that effect on every
   * unrelated parent re-render and resets the term dropdown. Taking primitives
   * moves the single memoized construction in here, where it belongs.
   */
  slug: string | null;
  accessToken: string | null;
  /** course_records rows the dashboard already loaded, for the selected term. */
  courses: Array<{
    id: string;
    course_code: string;
    title: string | null;
    credit_hours: number | string;
    letter_grade: string | null;
    term_id: string | null;
    status: string;
  }>;
  /**
   * Course-records were changed by an action this component owns (finalizing
   * a grade, editing/dropping an in-progress course, or a planned course
   * activating straight to in-progress on add). None of those are reflected
   * in `courses` until the dashboard's own profile fetch runs again -- this
   * is how that gets triggered.
   */
  onCourseRecordsChanged: () => void;
}

export function TermPlanner({ slug, accessToken, courses, onCourseRecordsChanged }: TermPlannerProps) {
  const [terms, setTerms] = useState<PlanningTerm[]>([]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [planned, setPlanned] = useState<PlannedCourse[]>([]);
  const [termsLoaded, setTermsLoaded] = useState(false);
  const [busyCode, setBusyCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [gradingSchema, setGradingSchema] = useState<GradingSchema | null>(null);
  const [crossListings, setCrossListings] = useState<CrossListingMap>({});
  const [pendingGrades, setPendingGrades] = useState<PendingFinalGrade[]>([]);
  const [finalizeDrafts, setFinalizeDrafts] = useState<Record<string, string>>({});
  const [finalizeBusyId, setFinalizeBusyId] = useState<string | null>(null);
  const [courseBusyId, setCourseBusyId] = useState<string | null>(null);

  // `today` is captured once per mount rather than read at each comparison, so
  // a term cannot change status midway through a render pass.
  const today = useMemo(() => new Date(), []);

  // The one place the identity object is built. Memoized on the primitives so
  // every effect and callback below that lists `identity` as a dependency sees
  // a stable reference until the session actually changes -- see the prop
  // comment for what an unstable one breaks.
  const identity = useMemo<AnalysisIdentity>(
    () => ({ slug, accessToken }),
    [slug, accessToken],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const result = await fetchTerms(identity);
      if (cancelled) return;
      setTerms(result.terms);
      // Only pick a default when there is nothing to preserve: the first load
      // (selectedKey still null), or a refetch whose term list no longer
      // contains what the user had chosen. Otherwise this effect running again
      // -- a discarded useMemo cache, a StrictMode double-invoke, a later
      // identity change -- must not overwrite a live selection.
      setSelectedKey((current) =>
        current !== null && result.terms.some((term) => term.key === current)
          ? current
          : pickDefaultTermKey(
              { terms: result.terms, upcoming_term_key: result.upcomingTermKey },
              today,
            ),
      );
      setTermsLoaded(true);
    })();
    return () => { cancelled = true; };
  }, [identity, today]);

  // Every planned course for the student, not per-term: the payload is small,
  // and refetching on each dropdown change would make switching terms flicker
  // through an empty list.
  const loadPlanned = useCallback(async () => {
    const result = await fetchPlannedCourses(identity);
    setPlanned(result.plannedCourses);
  }, [identity]);

  useEffect(() => { void loadPlanned(); }, [loadPlanned]);

  // The student's own institution's grade vocabulary -- see
  // lib/termPlanning.mjs's currentGradeOptions/finalGradeOptions. Fetched
  // once; it does not change within a session, and every current-grade and
  // final-grade selector on this page reads from this same state so there is
  // exactly one list, not one per selector.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const result = await fetchGradingSchema(identity);
      if (!cancelled) setGradingSchema(result.schema);
    })();
    return () => { cancelled = true; };
  }, [identity]);

  const currentGradeLetters = useMemo(() => currentGradeOptions(gradingSchema), [gradingSchema]);
  const finalGradeLetters = useMemo(() => finalGradeOptions(gradingSchema), [gradingSchema]);

  // Same "load once" shape as gradingSchema above. Powers CourseSearchAdd's
  // cross-listing-aware duplicate check: a course already in progress,
  // completed, or planned under its OTHER departmental code must not look
  // freely addable just because the exact searched code is new.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const result = await fetchCrossListings(identity);
      if (!cancelled) setCrossListings(result.crossListings);
    })();
    return () => { cancelled = true; };
  }, [identity]);

  // Student-wide (every term, not just the one selected in the dropdown):
  // see existingCourseStatusIndex.
  const existingCourseIndex = useMemo(
    () => existingCourseStatusIndex(courses, planned),
    [courses, planned],
  );

  // "How did last semester go?" -- confirmed courses from an ended term still
  // sitting at in_progress. Loaded once on mount alongside planned courses;
  // reconciliation on the backend (get_me_terms/get_me_planned_courses/
  // get_me_profile) already promoted anything due, so this list only shrinks
  // as the student finalizes grades below, never needs polling.
  const loadPendingGrades = useCallback(async () => {
    const result = await fetchPendingFinalGrades(identity);
    setPendingGrades(result.pendingFinalGrades);
  }, [identity]);

  useEffect(() => { void loadPendingGrades(); }, [loadPendingGrades]);

  async function handleFinalize(courseId: string) {
    const grade = (finalizeDrafts[courseId] ?? '').trim();
    if (!grade) return;
    setFinalizeBusyId(courseId);
    setError(null);
    const response = await finalizeCourseGrade(identity, courseId, grade);
    setFinalizeBusyId(null);
    if (!response.ok) {
      setError(response.message);
      return;
    }
    setPendingGrades((current) => current.filter((row) => row.id !== courseId));
    setFinalizeDrafts((current) => {
      const next = { ...current };
      delete next[courseId];
      return next;
    });
    onCourseRecordsChanged();
  }

  async function handleCurrentGradeChange(courseId: string, grade: string) {
    setCourseBusyId(courseId);
    setError(null);
    const response = await editInProgressCourse(identity, courseId, {
      letter_grade: grade || null,
    });
    setCourseBusyId(null);
    if (!response.ok) {
      setError(response.message);
      return;
    }
    onCourseRecordsChanged();
  }

  async function handleDrop(courseId: string) {
    setCourseBusyId(courseId);
    setError(null);
    const response = await editInProgressCourse(identity, courseId, { status: 'dropped' });
    setCourseBusyId(null);
    if (!response.ok) {
      setError(response.message);
      return;
    }
    onCourseRecordsChanged();
  }

  const selectedTerm = useMemo(
    () => terms.find((term) => term.key === selectedKey) ?? null,
    [terms, selectedKey],
  );

  const status = selectedTerm ? termStatus(selectedTerm, today) : 'unknown';
  // Planning is offered for a term that has not started. A term already
  // underway or finished shows its coursework and no search box -- adding a
  // "plan" to a term whose registration closed is not a thing to offer.
  const canPlan = status === 'upcoming' || status === 'unknown';

  const { records, planned: plannedForTerm } = useMemo(
    () => termCourseGroups(selectedTerm?.id ?? null, courses, planned),
    [selectedTerm, courses, planned],
  );

  const alreadyPlanned = useMemo(() => plannedCodes(plannedForTerm), [plannedForTerm]);

  // Preview only -- see isTermActivated. The backend still decides at write
  // time, against its own clock; this just tells the student ahead of
  // clicking Add what will happen.
  const willActivateOnAdd = selectedTerm ? isTermActivated(selectedTerm, today) : false;

  const renderConfirmedRow = (course: (typeof courses)[number]) => {
    const busy = courseBusyId === course.id;
    if (course.status === 'dropped') {
      return (
        <div className="real-course-row real-course-row--dropped" role="row" key={course.id}>
          <span role="cell">
            <span className="course-status-badge course-status-badge--dropped">Dropped</span>
            <strong>{course.course_code}</strong>
            <small>{course.title ?? 'Untitled course'}</small>
          </span>
          <span role="cell">{course.credit_hours} credits</span>
          <span role="cell">—</span>
        </div>
      );
    }
    if (course.status === 'in_progress') {
      return (
        <div className="real-course-row real-course-row--in-progress" role="row" key={course.id}>
          <span role="cell">
            <span className="course-status-badge course-status-badge--in-progress">In progress</span>
            <strong>{course.course_code}</strong>
            <small>{course.title ?? 'Untitled course'}</small>
          </span>
          <span role="cell">{course.credit_hours} credits</span>
          <span role="cell" className="current-grade-cell">
            <label className="current-grade-label" htmlFor={`current-grade-${course.id}`}>
              Current grade
            </label>
            <select
              id={`current-grade-${course.id}`}
              className="current-grade-select"
              value={course.letter_grade ?? ''}
              disabled={busy}
              onChange={(event) => { void handleCurrentGradeChange(course.id, event.target.value); }}
            >
              <option value="">Not entered</option>
              {currentGradeLetters.map((letter) => (
                <option key={letter} value={letter}>{letter}</option>
              ))}
            </select>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={busy}
              onClick={() => { void handleDrop(course.id); }}
            >
              Drop
            </button>
          </span>
        </div>
      );
    }
    // Completed (or any status this build does not otherwise special-case):
    // finalized history, no destructive controls.
    return (
      <div className="real-course-row" role="row" key={course.id}>
        <span role="cell">
          <strong>{course.course_code}</strong>
          <small>{course.title ?? 'Untitled course'}</small>
        </span>
        <span role="cell">{course.credit_hours} credits</span>
        <span role="cell">{course.letter_grade ?? '—'}</span>
      </div>
    );
  };

  // Server's flag, not a client-side re-derivation: term_view.py compares
  // against the server's date, and two clocks disagreeing about which term is
  // next would move courses between sections on a page refresh.
  const mergePlanned = selectedTerm?.is_upcoming === true;
  const inlinePlanned = mergePlanned ? plannedForTerm : [];
  const separatePlanned = mergePlanned ? [] : plannedForTerm;

  // No sort is applied to either list. Both arrive ordered -- records in the
  // order the dashboard's profile read returned them, planned rows by
  // created_at (planned.py) -- and planned rows follow confirmed ones because
  // that is the order of certainty, which is what the merged list is ranked by.
  const renderPlannedRow = (course: PlannedCourse) => (
    <div className="real-course-row real-course-row--planned" role="row" key={course.id}>
      <span role="cell">
        <span className="planned-badge">Planned</span>
        <strong>{course.course_code}</strong>
        <small>{course.title ?? 'Untitled course'}</small>
      </span>
      <span role="cell">
        {course.credit_hours === null ? 'Credits TBD' : `${course.credit_hours} credits`}
      </span>
      <span role="cell">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => { void handleRemove(course.id); }}
          aria-label={`Remove ${course.course_code} from your plan`}
        >
          Remove
        </button>
      </span>
    </div>
  );

  async function handleAdd(result: CatalogSearchResult) {
    if (!selectedTerm) return;
    setBusyCode(result.code);
    setError(null);
    const response = await addPlannedCourse(identity, {
      course_code: result.code,
      year: selectedTerm.year,
      season: selectedTerm.season,
      term_label: selectedTerm.label,
      title: result.title,
      // Only a fixed-credit course carries its hours across. A variable-credit
      // course (credit_min !== credit_max) is left null rather than guessing
      // which end of the range the student will register for.
      credit_hours:
        result.credit_min !== null && result.credit_min === result.credit_max
          ? result.credit_min
          : null,
      catalog_course_id: result.id,
    });
    setBusyCode(null);
    if (!response.ok || !response.course) {
      setError(response.message);
      return;
    }
    // Refetch rather than pushing the returned row: adding a course to a term
    // the student had never enrolled in creates its academic_terms row, so the
    // term list itself may now have an id it did not have a moment ago.
    if (response.course.kind === 'planned') {
      await loadPlanned();
    } else {
      // The term was already inside its activation window: the course was
      // written straight into course_records as in_progress. It never
      // touched planned_courses, so the dashboard's own profile fetch is what
      // needs to run again, not loadPlanned.
      onCourseRecordsChanged();
    }
    if (selectedTerm.id === null) {
      const refreshed = await fetchTerms(identity);
      setTerms(refreshed.terms);
    }
  }

  async function handleRemove(id: string) {
    setError(null);
    const response = await removePlannedCourse(identity, id);
    if (!response.ok) {
      setError('Could not remove that course.');
      return;
    }
    setPlanned((current) => current.filter((row) => row.id !== id));
  }

  if (!termsLoaded) return <p className="term-planner-loading">Loading terms…</p>;

  if (terms.length === 0) {
    return (
      <p className="empty-state">
        No terms on record yet. Upload a transcript, or check back once your institution&rsquo;s
        academic calendar is loaded.
      </p>
    );
  }

  const dateRange = selectedTerm ? formatTermDates(selectedTerm) : null;
  const statusLabel = TERM_STATUS_LABELS[status];

  return (
    <div className="term-planner">
      {pendingGrades.length > 0 && (
        <section className="grade-request-banner" role="region" aria-label="Final grades needed">
          <h3 className="grade-request-heading">How did last semester go?</h3>
          <p className="grade-request-copy">
            We need your final grade{pendingGrades.length > 1 ? 's' : ''} for{' '}
            {pendingGrades[0].term_label ?? 'last term'} to update your academic record.
          </p>
          <div className="grade-request-list">
            {pendingGrades.map((course) => (
              <div className="grade-request-row" key={course.id}>
                <span>
                  <strong>{course.course_code}</strong>
                  <small>{course.title ?? 'Untitled course'}</small>
                </span>
                <label className="sr-only" htmlFor={`final-grade-${course.id}`}>
                  Final grade for {course.course_code}
                </label>
                <select
                  id={`final-grade-${course.id}`}
                  className="current-grade-select"
                  value={finalizeDrafts[course.id] ?? ''}
                  onChange={(event) =>
                    setFinalizeDrafts((current) => ({ ...current, [course.id]: event.target.value }))
                  }
                >
                  <option value="">Select…</option>
                  {finalGradeLetters.map((letter) => (
                    <option key={letter} value={letter}>{letter}</option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={!finalizeDrafts[course.id] || finalizeBusyId === course.id}
                  onClick={() => { void handleFinalize(course.id); }}
                >
                  {finalizeBusyId === course.id ? 'Saving…' : 'Save'}
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="term-planner-header">
        <label className="term-select-label" htmlFor="term-select">Term</label>
        <select
          id="term-select"
          className="term-select"
          value={selectedKey ?? ''}
          onChange={(event) => setSelectedKey(event.target.value)}
        >
          {terms.map((term) => (
            <option key={term.key} value={term.key}>
              {term.label}
              {term.enrolled ? '' : ' (no coursework yet)'}
            </option>
          ))}
        </select>
        <div className="term-meta">
          {statusLabel && <span className={`term-badge term-badge--${status}`}>{statusLabel}</span>}
          {dateRange
            ? <span className="term-dates">{dateRange}</span>
            : <span className="term-dates term-dates--unknown">Calendar dates not on record</span>}
        </div>
      </div>

      {error && <p className="term-planner-error" role="alert">{error}</p>}

      <section className="term-courses">
        <h3 className="term-courses-heading">
          Coursework
          {/* The section header goes away when planned rows move in here, but
              the caveat it carried does not: it is a disclosure about the rows
              themselves, and it matters more, not less, once they sit beside
              graded ones. */}
          {inlinePlanned.length > 0 && (
            <span className="term-courses-note">
              Planned courses are not yet taken &middot; not counted in GPA or hours
            </span>
          )}
        </h3>
        {records.length === 0 && inlinePlanned.length === 0 ? (
          <p className="empty-state">No confirmed coursework in this term.</p>
        ) : (
          <div className="real-course-table" role="table" aria-label="Coursework in this term">
            {records.map(renderConfirmedRow)}
            {inlinePlanned.map(renderPlannedRow)}
          </div>
        )}
      </section>

      {separatePlanned.length > 0 && (
        <section className="term-courses term-courses--planned">
          <h3 className="term-courses-heading">
            Planned
            <span className="term-courses-note">Not yet taken &middot; not counted in GPA or hours</span>
          </h3>
          <div className="real-course-table" role="table" aria-label="Planned courses in this term">
            {separatePlanned.map(renderPlannedRow)}
          </div>
        </section>
      )}

      {canPlan && (
        <section className="term-search">
          <h3 className="term-courses-heading">Plan a course</h3>
          <CourseSearchAdd
            identity={identity}
            alreadyAddedCodes={alreadyPlanned}
            crossListings={crossListings}
            existingCourseIndex={existingCourseIndex}
            onAdd={(result) => { void handleAdd(result); }}
            busyCode={busyCode}
            hint={willActivateOnAdd ? (
              <p className="term-search-hint term-search-hint--activation">
                {selectedTerm?.label} starts soon &mdash; courses you add here will be treated as
                current (in progress), not planned.
              </p>
            ) : null}
          />
        </section>
      )}
    </div>
  );
}
