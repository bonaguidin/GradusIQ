import { useEffect } from 'react';
import type { RefObject } from 'react';

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Traps Tab/Shift+Tab inside `containerRef` while `active` is true -- the
 * one piece GuidedTour and EditCoursesDialog's dialog pattern (focus moved
 * in on open, Escape to close, both already correct) was missing. Without
 * this, Tab walks focus straight past the dialog's own last button into
 * whatever sits after it in the page.
 *
 * `active` defaults to true for a component that is only ever mounted
 * while open (GuidedTour, EditCoursesDialog -- conditionally rendered by
 * their parent, so "mounted" already means "open"). Pass it explicitly for
 * an always-mounted element that merely toggles into an overlay at some
 * breakpoint (the mobile nav rail, always in the DOM, only acting as a
 * modal drawer under 768px when open) -- trapping it unconditionally would
 * strand keyboard focus inside the rail even on desktop, where it is just
 * an ordinary sidebar.
 *
 * Deliberately scoped to keyboard Tab order, not full modality -- it does
 * not mark the rest of the page `inert`/`aria-hidden`, so a screen reader's
 * browse mode (not Tab) can still reach background content. These
 * components render inline rather than through a portal, so doing that
 * would mean reaching outside this component to the rest of the page; out
 * of scope here, tracked separately in outstanding-fixes.md if it's ever
 * needed.
 */
export function useFocusTrap(containerRef: RefObject<HTMLElement | null>, active: boolean = true): void {
  useEffect(() => {
    if (!active) return undefined;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Tab') return;
      const container = containerRef.current;
      if (!container) return;
      const focusable = Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey) {
        if (document.activeElement === first) {
          event.preventDefault();
          last.focus();
        }
      } else if (document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [containerRef, active]);
}
