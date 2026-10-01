import { useCallback, useState } from 'react';
import { searchJobPostings, type JobPosting } from '../api/jobSearch';
import { useAnalysisRun } from '../hooks/useAnalysisRun';

interface JobSearchPanelProps {
  targetRoles: string[];
  accessToken: string | null;
}

/**
 * Reads cached, role-filtered postings (features/posting_provider.py via
 * /api/v2/student/me/job-search) -- never a live per-search vendor call.
 * No location input: the cache has no location axis (is_dfw is a boolean
 * baked in at ingest, not queryable by city/zip).
 */
export function JobSearchPanel({ targetRoles, accessToken }: JobSearchPanelProps) {
  const [selectedRole, setSelectedRole] = useState(targetRoles[0] ?? '');
  const { state, trigger } = useAnalysisRun(
    useCallback(() => searchJobPostings(accessToken ?? '', selectedRole), [accessToken, selectedRole]),
  );

  return (
    <>
      <div className="job-search-shell">
        <label>
          Target role
          <select
            value={selectedRole}
            disabled={targetRoles.length === 0}
            onChange={(event) => setSelectedRole(event.target.value)}
          >
            {targetRoles.length === 0 && <option value="">No target role provided</option>}
            {targetRoles.map((role) => (
              <option key={role}>{role}</option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!selectedRole || !accessToken || state.phase === 'loading'}
          onClick={trigger}
        >
          {state.phase === 'loading' ? (
            <span className="btn-loading">
              <span className="spinner-small" aria-hidden="true" />
              Searching…
            </span>
          ) : (
            'Search Jobs'
          )}
        </button>
      </div>

      {state.phase === 'loading' && (
        <div className="analysis-loading" role="status" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          <p>Checking cached postings for this role…</p>
        </div>
      )}

      {state.phase === 'transport-error' && <p className="analysis-empty">{state.message}</p>}

      {state.phase === 'done' && state.result.coverage === 'no_market_data' && (
        <div className="real-empty">
          <h3>No postings found for this role recently</h3>
          <p>We update this data nightly from cached postings — check back soon.</p>
        </div>
      )}

      {state.phase === 'done' && state.result.coverage === 'available' && (
        <div className="theme-list">
          {state.result.postings.map((posting) => (
            <JobPostingCard key={posting.posting_id ?? `${posting.title}-${posting.employer}`} posting={posting} />
          ))}
        </div>
      )}
    </>
  );
}

function JobPostingCard({ posting }: { posting: JobPosting }) {
  const details = [posting.employer, posting.location, posting.posted_date ? `Posted ${posting.posted_date}` : null]
    .filter(Boolean)
    .join(' · ');

  return (
    <div className="theme-card">
      <div className="theme-header">
        <span className="theme-name">{posting.title ?? 'Untitled posting'}</span>
      </div>
      {details && <p className="theme-summary">{details}</p>}
      {posting.url && (
        <a href={posting.url} target="_blank" rel="noreferrer" className="btn btn-ghost btn-sm">
          View posting
        </a>
      )}
    </div>
  );
}
