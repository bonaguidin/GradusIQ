export interface JobPosting {
  posting_id: string | null;
  cluster_id: string | null;
  employer: string | null;
  title: string | null;
  location: string | null;
  url: string | null;
  posted_date: string | null;
  fetched_at: string | null;
  source: string | null;
}

export interface JobSearchResult {
  role: string;
  coverage: 'available' | 'no_market_data';
  postings: JobPosting[];
}

/**
 * Cached, role-filtered postings for one of the caller's own target roles.
 * Reads the nightly Adzuna-backed cache -- never triggers a live vendor
 * call, since the quota is already fully allocated to the scheduled fetch.
 * There is no location parameter: the cache has no location axis.
 */
export async function searchJobPostings(accessToken: string, role: string): Promise<JobSearchResult> {
  const response = await fetch(`/api/v2/student/me/job-search?role=${encodeURIComponent(role)}`, {
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? 'Job postings could not be loaded.');
  }
  return response.json() as Promise<JobSearchResult>;
}
