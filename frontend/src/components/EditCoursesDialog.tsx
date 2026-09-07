import { useEffect, useRef } from 'react';
import type { AnalysisIdentity } from '../api/analysisApi.mjs';
import type {
  CatalogSearchResult,
  CrossListingMap,
  ExistingCourseStatus,
} from '../lib/termPlanning.mjs';
import type {
  DegreeSchedulePlannedCourse,
  DegreeScheduleSuggestedCourse,
} from '../lib/degreeScheduleYears.mjs';
import { CourseSearchAdd } from './CourseSearchAdd';

/**
 * The per-term "Edit courses" popup for a future term card.
 *
 * WHY A NEW COMPONENT. The codebase has no reusable modal: ConfirmingOverlay
 * is a static, non-dismissible "saving…" scrim with no children, and
 * GuidedTour is bound to the onboarding step script. This is a small, scoped
 * dialog -- not a design-system primitive -- that follows the visual
 * convention both of those share (a fixed inset-0 scrim over a centered
 * --surface panel) and the a11y pattern GuidedTour already proved out:
 * role="dialog" + aria-modal, focus moved into the panel on open, Escape to
 * close. Focus is returned to the trigger by the caller's onClose.
 *
 * WRITES ARE STILL IMMEDIATE. onAdd / onRemove call the parent's existing
 * planned-course handlers, which write to the API on the spot and refetch --
 * there is no staging layer here. "Confirm" in the footer is a close button,
 * nothing more; it is named that way for the student, not because it submits.
 */
export function EditCoursesDialog({
  termKey,
  termLabel,
  identity,
  plannedCourses,
  suggestedCourses,
  alreadyAddedCodes,
  crossListings,
  existingCourseIndex,
  busyCode,
  onAdd,
  onRemove,
  onClose,
}: {
  termKey: string;
  termLabel: string;
  identity: AnalysisIdentity;
  plannedCourses: DegreeSchedulePlannedCourse[];
  /** Scheduler-placed no-choice courses for this term -- read-only headroom,
   *  relocated here from the term card. No add affordance. */
  suggestedCourses: DegreeScheduleSuggestedCourse[];
  /** Uppercased course codes already planned for this term, for disabling Add. */
  alreadyAddedCodes: Set<string>;
  /** See CourseSearchAdd -- passed straight through for the cross-listing-aware check. */
  crossListings: CrossListingMap;
  existingCourseIndex: Map<string, ExistingCourseStatus>;
  busyCode: string | null;
  onAdd: (result: CatalogSearchResult) => void;
  onRemove: (id: string) => void;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = `degree-schedule-edit-title-${termKey}`;

  // Move focus into the panel on open, matching GuidedTour's cardRef.focus().
  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  // Escape closes the dialog -- same window-level listener pattern as
  // GuidedTour. onClose (from the parent) is what returns focus to the trigger.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="degree-schedule-edit-overlay" role="presentation">
      <div
        className="degree-schedule-edit-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        ref={dialogRef}
      >
        <h5 id={titleId} className="degree-schedule-edit-title">
          Edit courses · {termLabel}
        </h5>

        {plannedCourses.length > 0 && (
          <ul className="degree-schedule-semester-courses">
            {plannedCourses.map((course) => (
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
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => onRemove(course.id)}
                    aria-label={`Remove ${course.course_code} from your plan`}
                  >
                    Remove
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}

        <div className="degree-schedule-suggested degree-schedule-add">
          <h6>Plan a course</h6>
          <CourseSearchAdd
            identity={identity}
            alreadyAddedCodes={alreadyAddedCodes}
            crossListings={crossListings}
            existingCourseIndex={existingCourseIndex}
            onAdd={onAdd}
            busyCode={busyCode}
            inputId={`degree-schedule-course-search-${termKey}`}
          />
        </div>

        {/* Scheduler-placed no-choice courses -- relocated verbatim from the
            term card. Read-only headroom: heading kept, no badge, no onClick,
            no add control. Reconciled against `planned` upstream in
            buildDegreeScheduleYears. */}
        {suggestedCourses.length > 0 && (
          <div className="degree-schedule-suggested degree-schedule-suggested--elective">
            <h6>If you have room</h6>
            <ul className="degree-schedule-semester-courses">
              {suggestedCourses.map((course) => (
                <li key={course.course_code} className="degree-schedule-semester-course">
                  <div className="degree-schedule-course-row">
                    <span><strong>{course.course_code}</strong></span>
                    <span>{course.credit_hours} credits</span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="degree-schedule-edit-footer">
          <button type="button" className="btn btn-primary btn-sm" onClick={onClose}>
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}
