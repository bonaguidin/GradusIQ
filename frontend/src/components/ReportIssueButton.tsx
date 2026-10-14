import { useRef, useState } from 'react';
import { createPortal } from 'react-dom';
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
