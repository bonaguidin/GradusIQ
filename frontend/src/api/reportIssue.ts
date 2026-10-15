import { REPORT_URL, buildReportFormData, normalizeReportResponse } from '../lib/reportIssue.mjs';
import type { ReportFields, ReportResult } from '../lib/reportIssue.mjs';

/**
 * Sends one report. `token` is the Supabase session when there is one, so the
 * backend can attach the verified account to the email; the demo dashboard
 * passes null and the report goes out unverified.
 */
export async function sendReport(
  token: string | null,
  fields: ReportFields,
  screenshots: Array<{ blob: Blob; name: string }>,
): Promise<ReportResult> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  try {
    // No Content-Type: the browser sets multipart/form-data with its boundary.
    const response = await fetch(REPORT_URL, {
      method: 'POST',
      headers,
      body: buildReportFormData(fields, screenshots),
    });
    let body: unknown = null;
    try { body = await response.json(); } catch { /* normalizer accepts null */ }
    return normalizeReportResponse(response.status, body);
  } catch {
    return normalizeReportResponse(0, null);
  }
}
