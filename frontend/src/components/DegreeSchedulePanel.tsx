import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import {
  DegreeScheduleChoiceError,
  fetchDegreeSchedule,
  isSkippedDegreeSchedule,
  updateDegreeScheduleChoices,
  updateDegreeScheduleExclusions,
  type DegreeScheduleResponse,
  type RequirementCandidate,
} from '../api/degreeSchedule.mjs';
import { useAuth } from '../auth/useAuth';
import { useAnalysisRun } from '../hooks/useAnalysisRun';
import {
  degreeScheduleContentState,
} from '../lib/degreeSchedulePresentation.mjs';
import { CareerOptimizationPanel } from './CareerOptimizationPanel';
import { DegreeScheduleTerms } from './DegreeScheduleTerms';
import { DegreeScheduleYears } from './DegreeScheduleYears';
import {
  choiceConflictMessage,
  removeRequirementSelection,
  replaceRequirementSelection,
} from '../lib/degreeScheduleSelections.mjs';

interface CourseRecordLike {
  id: string;
  term_id: string | null;
  course_code: string;
  title: string | null;
  credit_hours: number | string;
  letter_grade: string | null;
  status: string;
}

export function DegreeSchedulePanel({
  targetRole,
  courses = [],
  onResult,
}: {
  targetRole?: string;
  // Only consumed by the authenticated (DegreeScheduleYears) branch below --
  // demo identities render the simpler DegreeScheduleTerms instead and never
  // need this, since DegreeScheduleYears itself calls session-scoped
  // /me/terms and /me/grading-schema with no demo counterpart.
  courses?: CourseRecordLike[];
  onResult?: (result: DegreeScheduleResponse) => void;
}) {
  // Same { slug, session } shared AuthContext CourseDiscoveryPanel already
  // reads: slug is set only for the demo picker, session only for a real
  // signed-in student, so identity here needs no caller-supplied prop.
  const { slug, session } = useAuth();
  const accessToken = session?.access_token ?? null;
  const identity = { slug, accessToken };
  const load = useCallback(() => fetchDegreeSchedule(identity), [slug, accessToken]);
  const { state, trigger, replaceResult } = useAnalysisRun(load);
  const [choiceMutation, setChoiceMutation] = useState<{
    requirementGroupId: string;
    action: 'choose' | 'change' | 'clear' | 'restore';
    candidateId?: string;
  } | null>(null);
  const [choiceMessage, setChoiceMessage] = useState<string | null>(null);
  const mutationInFlight = useRef(false);

  useEffect(() => { trigger(); }, [trigger]);

  useEffect(() => {
    if (state.phase === 'done') onResult?.(state.result);
  }, [onResult, state]);

  const skipped = state.phase === 'done' && isSkippedDegreeSchedule(state.result) ? state.result : null;
  const schedule = state.phase === 'done' && !isSkippedDegreeSchedule(state.result) ? state.result : null;
  const contentState = state.phase === 'done' ? degreeScheduleContentState(state.result) : null;
  const infeasible = contentState === 'infeasible';

  const refreshSchedule = useCallback(async () => {
    const refreshed = await fetchDegreeSchedule(identity);
    replaceResult(refreshed);
    return refreshed;
  }, [slug, accessToken, replaceResult]);

  const saveChoices = useCallback(async (
    requirementGroupId: string,
    action: 'choose' | 'change' | 'clear',
    selections: NonNullable<typeof schedule>['selection_state']['selections'],
    candidateId?: string,
  ) => {
    if (!schedule || !accessToken || mutationInFlight.current) return;
    mutationInFlight.current = true;
    setChoiceMutation({ requirementGroupId, action, candidateId });
    setChoiceMessage(null);
    try {
      await updateDegreeScheduleChoices(accessToken, {
        scheduleVersion: schedule.schedule_version,
        selections,
      });
      await refreshSchedule();
    } catch (error) {
      const code = error instanceof DegreeScheduleChoiceError ? error.code : 'UNKNOWN_ERROR';
      try { await refreshSchedule(); } catch { /* retain the current rendered schedule */ }
      setChoiceMessage(choiceConflictMessage(code));
    } finally {
      mutationInFlight.current = false;
      setChoiceMutation(null);
    }
  }, [schedule, accessToken, choiceMutation, refreshSchedule]);

  const chooseCandidate = useCallback((
    requirementGroupId: string,
    candidate: RequirementCandidate,
    action: 'choose' | 'change' | 'clear',
  ) => {
    if (!schedule) return;
    void saveChoices(
      requirementGroupId,
      action,
      replaceRequirementSelection(
        schedule.selection_state.selections,
        requirementGroupId,
        candidate,
      ),
      candidate.candidate_id,
    );
  }, [schedule, saveChoices]);

  const clearChoice = useCallback((requirementGroupId: string) => {
    if (!schedule) return;
    void saveChoices(
      requirementGroupId,
      'clear',
      removeRequirementSelection(schedule.selection_state.selections, requirementGroupId),
    );
  }, [schedule, saveChoices]);

  const restoreExcluded = useCallback((requirementGroupId: string) => {
    if (!schedule || !accessToken || mutationInFlight.current) return;
    mutationInFlight.current = true;
    setChoiceMutation({ requirementGroupId, action: 'restore' });
    setChoiceMessage(null);
    void (async () => {
      try {
        await updateDegreeScheduleExclusions(accessToken, {
          scheduleVersion: schedule.schedule_version,
          excludedGroupIds: schedule.exclusion_state.excluded_group_ids.filter(
            (id) => id !== requirementGroupId,
          ),
        });
        await refreshSchedule();
      } catch (error) {
        const code = error instanceof DegreeScheduleChoiceError ? error.code : 'UNKNOWN_ERROR';
        try { await refreshSchedule(); } catch { /* retain the current rendered schedule */ }
        setChoiceMessage(choiceConflictMessage(code));
      } finally {
        mutationInFlight.current = false;
        setChoiceMutation(null);
      }
    })();
  }, [schedule, accessToken, refreshSchedule]);

  return (
    <Fragment>
      <section className="card degree-schedule-panel" aria-labelledby="degree-schedule-title">
      <div className="editable-section-header">
        <div>
          <h3 id="degree-schedule-title" className="editable-section-title">Degree Schedule</h3>
          <p className="degree-schedule-subtitle">Your prerequisite-aware academic schedule for requirements with a fixed course path.</p>
        </div>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={trigger}
          disabled={state.phase === 'loading'}
          aria-busy={state.phase === 'loading'}
        >
          {state.phase === 'loading' ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {state.phase === 'idle' && <p className="analysis-empty">Preparing your degree schedule…</p>}

      {state.phase === 'loading' && (
        <div className="analysis-loading" role="status" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          <p>Retrieving your degree schedule…</p>
        </div>
      )}

      {state.phase === 'transport-error' && (
        <div className="analysis-failed">
          <p>{state.message}</p>
        </div>
      )}

      {skipped && (
        <div className="analysis-skipped">
          <p>{skipped.summary}</p>
        </div>
      )}

      {infeasible && (
        <div className="analysis-failed degree-schedule-infeasible">
          <strong>Schedule needs attention</strong>
          <p>{schedule?.failure?.safe_message ?? 'The remaining courses could not be scheduled safely.'}</p>
        </div>
      )}

      {schedule?.status === 'SCHEDULED' && (
        <>
          <p className="degree-schedule-partial-note">
            Your academic schedule is shown below. Choices you still need to make sit on the term they'd fall in.
          </p>

          {choiceMessage && (
            <div className="degree-schedule-choice-message" role="status" aria-live="polite">{choiceMessage}</div>
          )}

          {/* A saved course choice that no longer matches current requirements
              is a plan-level problem, not a single term's -- it stays a
              top-level alert above the year grid rather than moving onto a
              term card (a stale selection can also point at a group with no
              current feasible option, which would resolve to no term at all). */}
          {schedule.selection_state?.status === 'RESELECTION_REQUIRED' && (
            <div className="degree-schedule-reselection" role="alert">
              <strong>Your saved course choice needs attention</strong>
              <p>Your degree requirements changed since this choice was saved. Choose a current option on its term card, or clear the saved choice.</p>
              <div className="degree-schedule-choice-actions">
                {schedule.selection_state.selections.map((selection) => (
                  <button type="button" className="btn btn-ghost btn-sm" disabled={choiceMutation !== null}
                    aria-busy={choiceMutation?.requirementGroupId === selection.requirement_group_id}
                    onClick={() => clearChoice(selection.requirement_group_id)} key={selection.requirement_group_id}>
                    {choiceMutation?.requirementGroupId === selection.requirement_group_id ? 'Clearing…' : 'Clear saved choice'}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Demo identities get the simpler term list: DegreeScheduleYears
              calls session-scoped /me/terms + /me/grading-schema routes
              directly with no demo counterpart, so it can't run without a
              real session. */}
          {identity.slug ? (
            contentState === 'empty' ? (
              <p className="empty-state">No deterministic courses currently need scheduling.</p>
            ) : (
              <DegreeScheduleTerms terms={schedule.terms} ariaLabel="Academic degree schedule" />
            )
          ) : (
            <DegreeScheduleYears
              accessToken={accessToken ?? ''}
              scheduleTerms={schedule.terms}
              courses={courses}
              decisions={schedule.decisions}
              candidateSets={schedule.candidate_sets}
              mutation={choiceMutation}
              onChoose={chooseCandidate}
              onClear={clearChoice}
              onRestore={restoreExcluded}
            />
          )}
        </>
      )}
      </section>
      {/* Demo identities (identity.slug set) never get Career Optimization: it
          has no durable cache the way GAP/FIT/SHIFT/Course Discovery do, so a
          public, tokenless button in front of it would mean every demo
          visitor's click is a fresh paid AI call. */}
      {schedule?.status === 'SCHEDULED' && !identity.slug && (
        <CareerOptimizationPanel accessToken={identity.accessToken ?? ''} academicSchedule={schedule} confirmedTargetRole={targetRole} />
      )}
    </Fragment>
  );
}
