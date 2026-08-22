import { useCallback, useState } from 'react';
import { fetchCareerOptimizedSchedule } from '../api/careerOptimizedSchedule';
import type { ScheduleResult } from '../api/degreeSchedule';
import {
  INITIAL_CAREER_OPTIMIZATION_STATE,
  careerChangeSummary,
  careerOptimizationCopy,
  careerChangeHeading,
  compareCareerSchedules,
  completedCareerOptimizationState,
  courseTermMoves,
  graduationTimingImpact,
  type CareerOptimizationRunState,
  type CareerOptimizationView,
} from '../lib/careerSchedulePresentation';
import { displayTermKey } from '../lib/degreeSchedulePresentation';
import { DegreeScheduleTerms } from './DegreeScheduleTerms';

function CourseList({ courses }: { courses: { courseCode: string; termKey: string }[] }) {
  if (courses.length === 0) return <span>None</span>;
  return <span>{courses.map((course) => `${course.courseCode} (${displayTermKey(course.termKey)})`).join(', ')}</span>;
}

function CoursesByCode({
  codes,
  courses,
}: {
  codes: string[];
  courses: { courseCode: string; termKey: string }[];
}) {
  return <CourseList courses={codes.flatMap((code) => courses.filter((course) => course.courseCode === code))} />;
}

export function CareerOptimizationPanel({
  accessToken,
  academicSchedule,
  targetRole,
  confirmedTargetRole,
}: {
  accessToken: string;
  academicSchedule: ScheduleResult;
  /** Optional explicit request override; omitted for the canonical confirmed-role path. */
  targetRole?: string;
  /** Display-only role already present in authenticated dashboard state. */
  confirmedTargetRole?: string;
}) {
  const [state, setState] = useState<CareerOptimizationRunState>(INITIAL_CAREER_OPTIMIZATION_STATE);
  const [scheduleExpanded, setScheduleExpanded] = useState(false);

  const run = useCallback((forceRefresh: boolean) => {
    if (!accessToken || state.phase === 'loading') return;
    setScheduleExpanded(false);
    setState({ phase: 'loading' });
    fetchCareerOptimizedSchedule(accessToken, {
      ...(targetRole ? { target_role: targetRole } : {}),
      force_refresh: forceRefresh,
    })
      .then((result) => setState(completedCareerOptimizationState(result)))
      .catch((error: unknown) => setState({
        phase: 'transport-error',
        message: error instanceof Error ? error.message : 'Career optimization is unavailable.',
      }));
  }, [accessToken, state.phase, targetRole]);

  const selectView = (view: CareerOptimizationView) => {
    setState((current) => current.phase === 'done' ? { ...current, view } : current);
  };

  const result = state.phase === 'done' ? state.result : null;
  const comparison = result
    ? compareCareerSchedules(result.academic_schedule, result.optimized_schedule, result.requirement_rankings)
    : null;
  const copy = result ? careerOptimizationCopy(result.status, result.summary) : null;
  const canPreview = result?.status === 'OPTIMIZED' || result?.status === 'PARTIAL';
  const showPreviewDisclosure = Boolean(canPreview && comparison?.hasChanges);
  const currentView = state.phase === 'done' ? state.view : 'academic';
  const viewedSchedule = result && currentView === 'optimized'
    ? result.optimized_schedule
    : academicSchedule;

  return (
    <section className="card career-optimization" aria-labelledby="career-optimization-title">
      <div className="career-optimization-header">
        <div>
          <h3 id="career-optimization-title">Career Optimization</h3>
          {state.phase === 'idle' && (
            <>
              {confirmedTargetRole && <p className="career-optimization-target"><span>Target</span><strong>{confirmedTargetRole}</strong></p>}
              <p>Compare academically valid choices already inside your degree plan based on your target career. This optional preview does not change your academic schedule.</p>
            </>
          )}
        </div>
        {(state.phase === 'idle' || state.phase === 'loading') && (
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => run(false)}
            disabled={!accessToken || state.phase === 'loading'}
            aria-busy={state.phase === 'loading'}
          >
            {state.phase === 'loading' ? 'Optimizing…' : 'Optimize for career'}
          </button>
        )}
      </div>

      {state.phase === 'loading' && (
        <div className="career-optimization-loading" role="status" aria-live="polite" aria-busy="true">
          <span className="spinner" aria-hidden="true" />
          <span>Finding career-aligned choices…</span>
        </div>
      )}

      {state.phase === 'transport-error' && (
        <div className="career-optimization-message career-optimization-message--warning" role="alert">
          <strong>Career optimization is unavailable</strong>
          <p>{state.message} Your academic plan remains unchanged.</p>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => run(false)}>Try again</button>
        </div>
      )}

      {result && copy && comparison && (
        <>
          <div className={`career-optimization-message career-optimization-message--${copy.tone}`} role="status" aria-live="polite">
            <div>
              <strong>{copy.heading}</strong>
              {result.target_role && <span className="career-optimization-role">{result.target_role}</span>}
            </div>
            <p>{copy.message}</p>
            {(result.status === 'OPTIMIZED' || result.status === 'PARTIAL') && (
              <p>Degree requirements remain academically valid, and Degree Planner still controls prerequisite order and graduation timing.</p>
            )}
          </div>

          {(result.status === 'OPTIMIZED' || result.status === 'PARTIAL') && (
            <section className="career-optimization-comparison" aria-labelledby="career-comparison-title">
              <p className="career-timing-impact">{graduationTimingImpact(result.academic_schedule, result.optimized_schedule)}</p>
              <h4 id="career-comparison-title">What changed</h4>
              <p>{careerChangeSummary(comparison)}</p>
              {comparison.hasChanges && (
                <ol className="career-change-list">
                  {comparison.changes.map((change) => (
                    <li key={change.requirementGroupId}>
                      <h5>{careerChangeHeading(change)}</h5>
                      <div className="career-change-delta">
                        {change.removedCourseCodes.length > 0 && (
                          <div className="career-change-delta-group career-change-delta-group--removed">
                            <span>Removed</span>
                            <CoursesByCode codes={change.removedCourseCodes} courses={change.academicCourses} />
                          </div>
                        )}
                        {change.addedCourseCodes.length > 0 && (
                          <div className="career-change-delta-group career-change-delta-group--added">
                            <span>Added</span>
                            <CoursesByCode codes={change.addedCourseCodes} courses={change.optimizedCourses} />
                          </div>
                        )}
                        {change.unchangedCourseCodes.length > 0 && (
                          <div className="career-change-delta-group">
                            <span>Unchanged in this path</span>
                            <CoursesByCode codes={change.unchangedCourseCodes} courses={change.optimizedCourses} />
                          </div>
                        )}
                      </div>
                      {change.movedCourseCodes.length > 0 && (
                        <div className="career-change-movement">
                          <strong>Moved</strong>
                          {courseTermMoves(change).map((move) => (
                            <p key={move.courseCode}>{move.courseCode}: {displayTermKey(move.fromTermKey)} → {displayTermKey(move.toTermKey)}</p>
                          ))}
                        </div>
                      )}
                      {change.careerRanked && change.rankingReason && (
                        <div className="career-change-explanation">
                          <strong>Why this choice</strong>
                          <p>{change.rankingReason}</p>
                          {change.skillAlignmentExplanation && (
                            <>
                              <strong>Skills supported</strong>
                              <p>{change.skillAlignmentExplanation}</p>
                            </>
                          )}
                        </div>
                      )}
                      {!change.careerRanked && (
                        <p className="career-change-no-provenance">No validated career-ranking explanation is available for this change.</p>
                      )}
                    </li>
                  ))}
                </ol>
              )}
              {comparison.hasChanges && <p className="career-optimization-unchanged">All other academically selected courses stayed unchanged.</p>}
            </section>
          )}

          {showPreviewDisclosure && (
            <section className="career-preview" aria-labelledby="career-preview-title">
              <button
                id="career-preview-title"
                type="button"
                className="btn btn-ghost btn-sm career-preview-disclosure"
                aria-expanded={scheduleExpanded}
                onClick={() => setScheduleExpanded((expanded) => !expanded)}
              >
                {scheduleExpanded ? 'Hide career-optimized schedule' : 'View complete career-optimized schedule'}
              </button>
              {scheduleExpanded && (
                <>
                  <div className="career-preview-header">
                    <p>This is a preview only. Nothing has been added to your official or planned coursework.</p>
                    <div className="career-preview-toggle" role="group" aria-label="Degree schedule view">
                      <button type="button" className={currentView === 'academic' ? 'is-active' : ''} aria-pressed={currentView === 'academic'} onClick={() => selectView('academic')}>Academic schedule</button>
                      <button type="button" className={currentView === 'optimized' ? 'is-active' : ''} aria-pressed={currentView === 'optimized'} onClick={() => selectView('optimized')}>Career-optimized preview</button>
                    </div>
                  </div>
                  <DegreeScheduleTerms terms={viewedSchedule.terms} ariaLabel={currentView === 'optimized' ? 'Career-optimized schedule preview' : 'Academic schedule'} />
                </>
              )}
            </section>
          )}

          <button type="button" className="btn btn-ghost btn-sm career-optimization-refresh" onClick={() => run(true)}>
            Refresh career optimization
          </button>
        </>
      )}
    </section>
  );
}
