import { useState } from 'react';
import type { TechnicalElectiveCandidate, TechnicalElectiveCandidateSuccess, TechnicalElectiveEligibility } from '../api/technicalElectives.mjs';
import { Reveal } from './Reveal';

const LABEL: Record<TechnicalElectiveEligibility, string> = {
  READY: 'Ready',
  PREREQUISITES_PLANNED: 'Prerequisites planned',
  PREREQUISITES_MISSING: 'Prerequisites missing',
};

function creditLabel(course: TechnicalElectiveCandidate) {
  return course.credit_min === course.credit_max
    ? `${course.credit_min} credits`
    : `${course.credit_min}–${course.credit_max} credits`;
}

/**
 * Pure display: the candidate pool for whichever requirement group is the
 * shared fetch's primary match. Fetching and match/primary decisions live
 * one level up (RequirementSatisfactionPanel + TechnicalElectiveSlot) --
 * this component never sees a loading or error state, since a slot only
 * ever mounts it once a successful result already exists.
 */
export function TechnicalElectiveCandidates({ result }: { result: TechnicalElectiveCandidateSuccess }) {
  const [expanded, setExpanded] = useState(false);
  const [showAll, setShowAll] = useState(false);

  return (
    <div className="technical-elective-options">
      <button
        type="button"
        className="btn btn-ghost btn-sm technical-elective-options-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? 'Hide course options' : 'View course options'}
      </button>

      <Reveal open={expanded}>
        <div className="technical-elective-options-body">
          <p className="technical-elective-disclaimer">
            {result.institution === 'smu'
              ? 'Provisional CS 3000+ options only.'
              : "Provisional options at or above your program's technical-elective course level only."}
            {' '}Adviser approval is required, and courses in your chosen track cannot count.
          </p>
          <ul className="technical-elective-list">
            {(showAll ? result.candidates : result.candidates.slice(0, 6)).map((course) => (
              <li key={course.course_code} className="technical-elective-course">
                <div>
                  <strong>{course.course_code}</strong> · {course.title}
                  <span className="technical-elective-credits">{creditLabel(course)}</span>
                </div>
                <span className={`technical-elective-state technical-elective-state--${course.eligibility.toLowerCase()}`}>
                  {LABEL[course.eligibility]}
                </span>
                {course.planned_prerequisite_codes.length > 0 && (
                  <p>Planned prerequisites: {course.planned_prerequisite_codes.join(', ')}</p>
                )}
                {course.missing_prerequisite_options.length > 0 && (
                  <p>Missing: {course.missing_prerequisite_options.map((values) => values.join(' or ')).join('; ')}</p>
                )}
              </li>
            ))}
          </ul>
          {result.candidates.length === 0 && (
            <p>No courses could be verified automatically from the current catalog rules. An adviser can still help select an eligible Technical Elective.</p>
          )}
          {result.candidates.length > 6 && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setShowAll((value) => !value)}>
              {showAll ? 'Show fewer' : `View all ${result.candidates.length} options`}
            </button>
          )}
          <p className="technical-elective-cross-department">
            Other departments may be approved as exceptions; ask your adviser about those options.
          </p>
        </div>
      </Reveal>
    </div>
  );
}
