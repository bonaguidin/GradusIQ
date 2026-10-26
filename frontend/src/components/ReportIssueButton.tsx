import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { REPORT_ISSUE_EVENT, takeReportIssueRequest } from '../lib/reportIssueRequest';
import { BugIcon, ReportIssueDialog } from './ReportIssueDialog';

/**
 * The topbar bug icon, sitting just left of the tour "?" on both the real and
 * the demo dashboard, and the report pop-up it opens. Owns its own open state
 * so each dashboard only renders this one element.
 */
export function ReportIssueButton({
  accessToken = null,
  defaultName = '',
  defaultEmail = '',
  pageLabel,
}: {
  accessToken?: string | null;
  defaultName?: string;
  defaultEmail?: string;
  pageLabel: string;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // The assistant's "Report a bug" button asks through reportIssueRequest,
  // either while this is mounted (the event) or just before (the flag).
  useEffect(() => {
    function openIfAsked() {
      if (takeReportIssueRequest()) setOpen(true);
    }
    openIfAsked();
    window.addEventListener(REPORT_ISSUE_EVENT, openIfAsked);
    return () => window.removeEventListener(REPORT_ISSUE_EVENT, openIfAsked);
  }, []);

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="topbar-report"
        onClick={() => setOpen(true)}
        aria-label="Report a bug or suggest a feature"
        aria-haspopup="dialog"
        title="Report a bug or suggest a feature"
      >
        <BugIcon />
      </button>
      {/* Portaled to <body>: rendered in place, the overlay would sit between
          this button and the "?" and break the `.topbar-report + .topbar-help`
          pairing that keeps the two icons together. */}
      {open && createPortal(
        <ReportIssueDialog
          accessToken={accessToken}
          defaultName={defaultName}
          defaultEmail={defaultEmail}
          pageLabel={pageLabel}
          onClose={close}
        />,
        document.body,
      )}
    </>
  );
}
