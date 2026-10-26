import { useEffect, useRef } from 'react';
import { useAuth } from '../auth/useAuth';
import { useChat, useChatPage } from '../chat/ChatContext';
import { ChatPanel } from './ChatPanel';

/**
 * The assistant on every signed-in page: a launcher in the corner that opens
 * the chat as a side panel (a full-screen sheet on phones).
 *
 * Not shown on Overview, where the same conversation is already on the page
 * as the inline card, and not shown to anyone signed out. The panel is not
 * modal: the page beside it stays usable, so a student can read their GPA
 * chart while asking about it. Escape or the close button puts it away and
 * returns focus to the launcher.
 */
export function AssistantDock() {
  const { profile, slug, session, studentAccount } = useAuth();
  const { panelOpen, setPanelOpen, sending } = useChat();
  const page = useChatPage();
  const launcherRef = useRef<HTMLButtonElement>(null);

  const signedIn = Boolean((slug && profile) || (session && studentAccount.status === 'ready'));
  // Demo personas have no transcript/resume/profile pages (RequireStudentAccount).
  const visible = signedIn && page !== null && page !== 'overview';
  const open = visible && panelOpen;

  useEffect(() => {
    if (!open) return undefined;
    function onKey(event: KeyboardEvent) {
      if (event.key !== 'Escape') return;
      // A dialog on top of the page (bug report, profile step) owns its own Escape.
      if (document.querySelector('[aria-modal="true"]')) return;
      setPanelOpen(false);
      requestAnimationFrame(() => launcherRef.current?.focus());
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, setPanelOpen]);

  if (!visible) return null;

  return (
    <>
      {open ? (
        <div className="assistant-dock">
          <ChatPanel
            variant="docked"
            autoFocus
            onClose={() => {
              setPanelOpen(false);
              // The launcher mounts again on this render; focus it once it has.
              requestAnimationFrame(() => launcherRef.current?.focus());
            }}
          />
        </div>
      ) : (
        <button
          ref={launcherRef}
          type="button"
          className="assistant-launcher"
          onClick={() => setPanelOpen(true)}
          aria-expanded={false}
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" />
          </svg>
          <span className="assistant-launcher-label">Ask <span translate="no">GradusIQ</span></span>
          {sending && <span className="assistant-launcher-pending" aria-label="Reply on its way" />}
        </button>
      )}
    </>
  );
}
