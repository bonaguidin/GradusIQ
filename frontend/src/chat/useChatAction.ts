import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { CHAT_ACTIONS } from '../lib/chatActions.mjs';
import { requestReportIssue } from '../lib/reportIssueRequest';
import { useChat, useChatPage, useDashboardLocation } from './ChatContext';

const PHONE = '(max-width: 640px)';

function isPhone(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia(PHONE).matches;
}

// The destination renders after navigation, so look for it for about a second.
function scrollWhenThere(selector: string, framesLeft = 60): void {
  const el = document.querySelector(selector);
  if (el) {
    const smooth = !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    el.scrollIntoView({ block: 'start', behavior: smooth ? 'smooth' : 'auto' });
    return;
  }
  if (framesLeft > 0) requestAnimationFrame(() => scrollWhenThere(selector, framesLeft - 1));
}

/**
 * Runs an assistant action button: go to its page and keep the chat open
 * beside it (on a phone the chat would cover the page, so it closes there).
 */
export function useChatAction(): (id: string) => void {
  const navigate = useNavigate();
  const { setPanelOpen } = useChat();
  const page = useChatPage();
  const dashboard = useDashboardLocation();

  return useCallback(
    (id: string) => {
      const action = CHAT_ACTIONS[id];
      if (!action) return;
      const onDashboard = page !== null && !['transcript', 'resume', 'profile-complete'].includes(page);

      if (action.dialog === 'report-issue') {
        requestReportIssue();
        // Only the dashboard has the report pop-up; it opens once there.
        if (!onDashboard) navigate(dashboard.path);
        return;
      }

      let href = action.to ?? dashboard.path;
      if (action.dashboard) {
        const params = new URLSearchParams(action.dashboard);
        const current = new URLSearchParams(window.location.search);
        for (const key of dashboard.keepParams) {
          const value = current.get(key);
          if (value !== null) params.set(key, value);
        }
        href = `${dashboard.path}?${params.toString()}`;
      }
      navigate(href);
      setPanelOpen(!isPhone());
      if (action.scrollTo) scrollWhenThere(action.scrollTo);
    },
    [navigate, setPanelOpen, page, dashboard],
  );
}
