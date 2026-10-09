export interface JobCard {
  posting_id: string | null;
  title: string | null;
  employer: string | null;
  locations: string[];
  posted_date: string | null;
  url: string | null;
  family: string | null;
  source: string | null;
}

export interface FamilyFacet {
  family: string;
  count: number;
}

export interface EmployerFacet {
  employer: string;
  count: number;
}

export type JobSearchDays = 7 | 14 | 30;

export interface JobSearchFeedResult {
  coverage: 'available' | 'no_market_data' | 'no_target_roles';
  postings: JobCard[];
  facets: { families: FamilyFacet[]; employers: EmployerFacet[] };
  total: number;
  next_cursor: number | null;
  scoped_families: string[];
}

export interface JobSearchFeedParams {
  families?: string[];
  days?: JobSearchDays;
  employer?: string;
  cursor?: number;
}

/**
 * The combined Job Search feed -- internships across the caller's own
 * target roles plus related families, newest first. Reads only the
 * cached job_postings table (features/job_search_feed.py) -- never a live
 * per-request vendor call. Every param is sent explicitly, even empty, so
 * the request always matches vercel.json's all-four-params rewrite rather
 * than falling through to a different rule.
 */
export async function fetchJobSearchFeed(
  accessToken: string,
  params: JobSearchFeedParams = {},
): Promise<JobSearchFeedResult> {
  const qs = new URLSearchParams();
  qs.set('families', (params.families ?? []).join(','));
  qs.set('days', String(params.days ?? 30));
  qs.set('employer', params.employer ?? '');
  qs.set('cursor', String(params.cursor ?? 0));

  const response = await fetch(`/api/v2/student/me/job-search?${qs.toString()}`, {
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? 'Job postings could not be loaded.');
  }
  return response.json() as Promise<JobSearchFeedResult>;
}
