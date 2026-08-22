import { useState } from 'react';
import type { RequirementGroupResult, RequirementGroupStatus } from '../api/requirementSatisfaction';
import { TechnicalElectiveCandidates } from './TechnicalElectiveCandidates';

const STATUS_LABEL: Record<RequirementGroupStatus, string> = {
  SATISFIED: 'Satisfied',
  IN_PROGRESS: 'In progress',
  NOT_STARTED: 'Not started',
  MANUAL_REVIEW: 'Adviser review needed',
};

const STATUS_MODIFIER: Record<RequirementGroupStatus, string> = {
  SATISFIED: 'satisfied',
  IN_PROGRESS: 'in-progress',
  NOT_STARTED: 'not-started',
  MANUAL_REVIEW: 'manual-review',
};

function RequirementStatusBadge({ status }: { status: RequirementGroupStatus }) {
  return (
    <span className={`course-discovery-status-badge course-discovery-status-badge--${STATUS_MODIFIER[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  );
}

// Self-referential: a RequirementGroupResult's children are the same shape,
// to whatever depth the program's requirement tree actually has. No
// accordion library -- one accessible collapsible <li> per node. Details are
// closed initially so the top-level audit remains scannable.
export function RequirementGroupNode({ group }: { group: RequirementGroupResult }) {
  const [expanded, setExpanded] = useState(false);
  const hasChildren = group.children.length > 0;

  return (
    <li className="requirement-group">
      <div className="requirement-group-header">
        {hasChildren ? (
          <button
            type="button"
            className="requirement-group-toggle"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            <span className="requirement-group-toggle-icon" aria-hidden="true">{expanded ? '▾' : '▸'}</span>
            {group.name}
          </button>
        ) : (
          <span className="requirement-group-name">{group.name}</span>
        )}
        <RequirementStatusBadge status={group.status} />
      </div>

      {group.detail && <p className="requirement-group-detail">{group.detail}</p>}

      {group.matched_course_codes.length > 0 && (
        <p className="requirement-group-matched">
          Matched: {group.matched_course_codes.join(', ')}
        </p>
      )}

      {group.status === 'MANUAL_REVIEW' && (
        <p className="requirement-group-adviser-note">
          Course options for this requirement are not automatically selected yet.
        </p>
      )}

      {group.coursedog_rule_id === 'AjzAZTn4' && (
        <TechnicalElectiveCandidates requirementGroupId={group.id} />
      )}

      {hasChildren && expanded && (
        <ul className="requirement-group-children">
          {group.children.map((child) => (
            <RequirementGroupNode key={child.id} group={child} />
          ))}
        </ul>
      )}
    </li>
  );
}
