import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useFocusTrap } from '../hooks/useFocusTrap';
import './GuidedTour.css';

// ── Types ────────────────────────────────────────────────────────────────────

export type TourSection = 'overview' | 'academic' | 'career';

/** A deep-link offered on the final step (e.g. "Add transcript"). Only the
 *  authenticated dashboard supplies these; the demo dashboard leaves them off,
 *  so its final step shows just the "Explore on my own" escape. */
export interface TourAction {
  label: string;
  onClick: () => void;
}

interface TourStep {
  /** Dashboard tab this step walks the viewer to. */
  section: TourSection;
  /** 'info' walks a tab; 'cta' is the closing action step. */
  kind: 'info' | 'cta';
  /** Small mono eyebrow — the tab / context label. */
  eyebrow: string;
  /** Serif display headline. */
  title: string;
  /** Body copy explaining what lives on this tab. */
  body: ReactNode;
}

// ── Tour Script ──────────────────────────────────────────────────────────────
// Written for a brand-new account whose Academic and Career tabs are still
// empty: each step says what the tab is for AND how to populate it. Ends on a
// call to action (add transcript / add resume) rather than a passive "Finish".

const TOUR_STEPS: TourStep[] = [
  {
    section: 'overview',
    kind: 'info',
    eyebrow: 'Welcome',
    title: 'Welcome to GradusIQ',
    body: (
      <>
        Your AI career and academic companion. This quick tour shows the three
        areas of your profile and how to fill them in. Take it now, or{' '}
        <strong>skip</strong> and reopen it anytime from the <strong>?</strong>{' '}
        button up top.
      </>
    ),
  },
  {
    section: 'overview',
    kind: 'info',
    eyebrow: 'Overview',
    title: 'Your snapshot at a glance',
    body: (
      <>
        Your name, GPA, major and university, plus{' '}
        <strong>Readiness</strong> and <strong>Profile Completeness</strong> so
        you always know what to add next. At the top, chat with the assistant
        about your academics and career.
      </>
    ),
  },
  {
    section: 'academic',
    kind: 'info',
    eyebrow: 'Academic',
    title: 'Add your transcript',
    body: (
      <>
        Your classes and grades live here. To populate them, upload your{' '}
        <strong>transcript</strong> — we read the courses off it and you confirm
        each line. Direct <strong>Canvas &amp; Blackboard sync is coming soon</strong>.
        Once your record is in: AI analysis of your grades and professor
        comments, plus an exam-topic breakdown.
      </>
    ),
  },
  {
    section: 'career',
    kind: 'info',
    eyebrow: 'Career · the core',
    title: 'Add your resume to unlock GAP, FIT & SHIFT',
    body: (
      <>
        The heart of GradusIQ. Add your <strong>resume</strong> and it fills in
        your experience, projects and target roles — unlocking{' '}
        <strong>GAP</strong> (a readiness check against your target roles),{' '}
        <strong>FIT</strong> (how well you match each role and why), and{' '}
        <strong>SHIFT</strong> (how those roles are evolving and adjacent paths
        worth exploring).
      </>
    ),
  },
  {
    section: 'overview',
    kind: 'cta',
    eyebrow: 'Get started',
    title: "You're all set — first steps",
    body: (
      <>
        Add your transcript and resume to bring your profile to life. You can
        always do this later from the Overview tab.
      </>
    ),
  },
];

// ── Component ────────────────────────────────────────────────────────────────

interface GuidedTourProps {
  /** Switch the underlying dashboard tab as the tour advances. */
  onNavigate: (section: TourSection) => void;
  /** Called when the tour ends (any dismissal). `completed` is true when the
   *  viewer reached the final step (Explore / a CTA), false on Skip/Escape. */
  onClose: (completed: boolean) => void;
  /** Optional deep-links shown as buttons on the final step. */
  endActions?: TourAction[];
}

export function GuidedTour({ onNavigate, onClose, endActions }: GuidedTourProps) {
  const [index, setIndex] = useState(0);
  const cardRef = useRef<HTMLDivElement>(null);

  const step = TOUR_STEPS[index];
  const isFirst = index === 0;
  const isCta = step.kind === 'cta';

  // Drive the underlying tab whenever the step changes, and move focus to the
  // card so keyboard users follow along.
  useEffect(() => {
    onNavigate(step.section);
    cardRef.current?.focus();
  }, [index, step.section, onNavigate]);

  // Escape skips the tour.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose(false);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Keeps Tab/Shift+Tab from walking focus out into the dashboard behind
  // the tour -- see useFocusTrap.
  useFocusTrap(cardRef);

  function next() {
    setIndex((i) => Math.min(TOUR_STEPS.length - 1, i + 1));
  }

  function back() {
    setIndex((i) => Math.max(0, i - 1));
  }

  // A final-step deep-link: mark the tour done, then navigate away.
  function runAction(action: TourAction) {
    onClose(true);
    action.onClick();
  }

  return (
    <div className="tour-overlay" role="presentation">
      <div
        className="tour-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        aria-describedby="tour-body"
        tabIndex={-1}
        ref={cardRef}
      >
        <div className="tour-eyebrow">{step.eyebrow}</div>
        <h2 className="tour-title" id="tour-title">
          {step.title}
        </h2>
        <p className="tour-body" id="tour-body">
          {step.body}
        </p>

        {/* Final step: the call-to-action buttons (deep-links), stacked. */}
        {isCta && endActions && endActions.length > 0 && (
          <div className="tour-cta-actions">
            {endActions.map((action) => (
              <button
                key={action.label}
                type="button"
                className="btn btn-primary btn-full"
                onClick={() => runAction(action)}
              >
                {action.label}
              </button>
            ))}
          </div>
        )}

        <div className="tour-footer">
          {/* Progress dots */}
          <div className="tour-dots" aria-hidden="true">
            {TOUR_STEPS.map((_, i) => (
              <span
                key={i}
                className={`tour-dot${i === index ? ' tour-dot--active' : ''}`}
              />
            ))}
          </div>

          <div className="tour-actions">
            {isCta ? (
              <>
                {!isFirst && (
                  <button type="button" className="btn btn-ghost btn-sm" onClick={back}>
                    Back
                  </button>
                )}
                <button
                  type="button"
                  className="btn btn-ghost btn-sm tour-skip"
                  onClick={() => onClose(true)}
                >
                  Explore on my own
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm tour-skip"
                  onClick={() => onClose(false)}
                >
                  Skip tour
                </button>
                {!isFirst && (
                  <button type="button" className="btn btn-ghost btn-sm" onClick={back}>
                    Back
                  </button>
                )}
                <button type="button" className="btn btn-primary btn-sm" onClick={next}>
                  Next
                </button>
              </>
            )}
          </div>
        </div>

        <div className="tour-step-count" aria-live="polite">
          Step {index + 1} of {TOUR_STEPS.length}
        </div>
      </div>
    </div>
  );
}
