import { useCallback, useEffect, useRef, useState } from 'react';
import {
  fetchJobSearchFeed,
  type JobCard,
  type JobSearchDays,
  type JobSearchFeedResult,
} from '../api/jobSearch';

interface JobSearchPanelProps {
  targetRoles: string[];
  accessToken: string | null;
}

const DAYS_OPTIONS: JobSearchDays[] = [7, 14, 30];

type Phase = 'idle' | 'loading' | 'error' | 'done';

/**
 * Combined Job Search feed: internships across the student's target roles
 * plus related families, newest first, with relevance filters -- loaded on
 * mount from the cached job_postings table (features/job_search_feed.py).
 * Never a live per-search vendor call, and no location input: the cache has
 * no location axis (is_dfw is a boolean baked in at ingest).
 *
 * This panel owns its own small fetch state rather than useAnalysisRun:
 * four independent controls (families, days, employer, load-more) each
 * trigger the same endpoint with different params, which that hook's
 * single-trigger shape does not fit cleanly.
 */
export function JobSearchPanel({ targetRoles, accessToken }: JobSearchPanelProps) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [cards, setCards] = useState<JobCard[]>([]);
  const [facets, setFacets] = useState<JobSearchFeedResult['facets']>({ families: [], employers: [] });
  const [coverage, setCoverage] = useState<JobSearchFeedResult['coverage'] | null>(null);
  const [nextCursor, setNextCursor] = useState<number | null>(null);

  // null until the first response resolves the student's own default
  // family set server-side; after that, the set of chips currently "on".
  const [activeFamilies, setActiveFamilies] = useState<string[] | null>(null);
  const [days, setDays] = useState<JobSearchDays>(30);
  const [employer, setEmployer] = useState('');

  const load = useCallback(
    async (overrides: { families?: string[]; days?: JobSearchDays; employer?: string; cursor?: number }, append: boolean) => {
      if (!accessToken) return;
      setPhase('loading');
      setErrorMessage(null);
      try {
        const result = await fetchJobSearchFeed(accessToken, {
          families: overrides.families ?? activeFamilies ?? undefined,
          days: overrides.days ?? days,
          employer: overrides.employer ?? employer,
          cursor: overrides.cursor ?? 0,
        });
        setCards((prev) => (append ? [...prev, ...result.postings] : result.postings));
        setFacets(result.facets);
        setCoverage(result.coverage);
        setNextCursor(result.next_cursor);
        if (activeFamilies === null) setActiveFamilies(result.scoped_families);
        setPhase('done');
      } catch (err) {
        setErrorMessage(err instanceof Error ? err.message : 'Request failed.');
        setPhase('error');
      }
    },
    [accessToken, activeFamilies, days, employer],
  );

  const startedRef = useRef(false);
  useEffect(() => {
    if (startedRef.current || !accessToken) return;
    startedRef.current = true;
    if (targetRoles.length === 0) {
      // Known locally already -- no point asking the server, which would
      // return the same no_target_roles coverage with an empty pool.
      setActiveFamilies([]);
      setCoverage('no_target_roles');
      setPhase('done');
      return;
    }
    void load({}, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only
  }, [accessToken]);

  const toggleFamily = (family: string) => {
    const current = activeFamilies ?? [];
    const next = current.includes(family)
      ? current.filter((f) => f !== family)
      : [...current, family];
    setActiveFamilies(next);
    void load({ families: next, cursor: 0 }, false);
  };

  const changeDays = (value: JobSearchDays) => {
    setDays(value);
    void load({ days: value, cursor: 0 }, false);
  };

  const changeEmployer = (value: string) => {
    setEmployer(value);
    void load({ employer: value, cursor: 0 }, false);
  };

  const loadMore = () => {
    if (nextCursor === null) return;
    void load({ cursor: nextCursor }, true);
  };

  return (
    <div className="job-search-feed">
      {coverage === 'no_target_roles' ? (
        <div className="real-empty">
          <h3>Add a target role to see Job Search</h3>
          <p>Job Search is built from your own target roles and related families. Set one in your Career Profile first.</p>
        </div>
      ) : (
        <>
          <div className="job-search-controls">
            <fieldset className="job-search-families" aria-label="Filter by family">
              <legend>Families</legend>
              {facets.families.map((f) => {
                const on = (activeFamilies ?? []).includes(f.family);
                return (
                  <button
                    key={f.family}
                    type="button"
                    className={`chip${on ? ' chip--on' : ''}`}
                    aria-pressed={on}
                    onClick={() => toggleFamily(f.family)}
                  >
                    {f.family} <span className="chip-count">{f.count}</span>
                  </button>
                );
              })}
            </fieldset>

            <label>
              Posted within
              <select
                value={days}
                onChange={(event) => changeDays(Number(event.target.value) as JobSearchDays)}
              >
                {DAYS_OPTIONS.map((d) => (
                  <option key={d} value={d}>
                    {d} days
                  </option>
                ))}
              </select>
            </label>

            <label>
              Employer
              <select value={employer} onChange={(event) => changeEmployer(event.target.value)}>
                <option value="">All employers</option>
                {facets.employers.map((e) => (
                  <option key={e.employer} value={e.employer}>
                    {e.employer} ({e.count})
                  </option>
                ))}
              </select>
            </label>
          </div>

          {phase === 'loading' && cards.length === 0 && (
            <div className="analysis-loading" role="status" aria-live="polite">
              <span className="spinner" aria-hidden="true" />
              <p>Checking cached postings…</p>
            </div>
          )}

          {phase === 'error' && <p className="analysis-empty">{errorMessage}</p>}

          {phase === 'done' && coverage === 'no_market_data' && (
            <div className="real-empty">
              <h3>No postings found recently</h3>
              <p>We update this data nightly from cached postings — check back soon, or try a different filter.</p>
            </div>
          )}

          {cards.length > 0 && (
            <div className="theme-list">
              {cards.map((card) => (
                <JobCardView key={card.posting_id ?? `${card.title}-${card.employer}`} card={card} />
              ))}
            </div>
          )}

          {nextCursor !== null && (
            <button type="button" className="btn btn-ghost" onClick={loadMore} disabled={phase === 'loading'}>
              {phase === 'loading' ? 'Loading…' : 'Load more'}
            </button>
          )}
        </>
      )}
    </div>
  );
}

function JobCardView({ card }: { card: JobCard }) {
  const daysAgo = daysSince(card.posted_date);
  const details = [
    card.employer,
    card.locations.join(' · '),
    daysAgo !== null ? `posted ${daysAgo} day${daysAgo === 1 ? '' : 's'} ago` : null,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <div className="theme-card">
      <div className="theme-header">
        <span className="theme-name">{card.title ?? 'Untitled posting'}</span>
        {card.family && <span className="chip chip--tag">{card.family}</span>}
      </div>
      {details && <p className="theme-summary">{details}</p>}
      {card.url && (
        <a href={card.url} target="_blank" rel="noreferrer" className="btn btn-ghost btn-sm">
          View posting
        </a>
      )}
    </div>
  );
}

function daysSince(isoDate: string | null): number | null {
  if (!isoDate) return null;
  const posted = new Date(`${isoDate}T00:00:00Z`).getTime();
  if (Number.isNaN(posted)) return null;
  const diff = Date.now() - posted;
  return Math.max(0, Math.floor(diff / (24 * 60 * 60 * 1000)));
}
