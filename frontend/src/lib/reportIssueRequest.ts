// Lets something other than the topbar bug icon open the report pop-up (the
// assistant's "Report a bug" button). The request is remembered until a
// ReportIssueButton takes it, so it still works when the chat asked from a
// page without a topbar and the dashboard is only just mounting.

export const REPORT_ISSUE_EVENT = 'gradusiq:report-issue';

let pending = false;

export function requestReportIssue(): void {
  pending = true;
  window.dispatchEvent(new Event(REPORT_ISSUE_EVENT));
}

/** True once per request; the first ReportIssueButton to ask gets it. */
export function takeReportIssueRequest(): boolean {
  const was = pending;
  pending = false;
  return was;
}
