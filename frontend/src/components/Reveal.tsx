import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';

// --t-move in interaction.css, plus a frame of slack.
const SETTLE_MS = 240;

interface RevealProps {
  open: boolean;
  children: ReactNode;
}

/**
 * Grows content open and closed instead of cutting between the two states.
 *
 * Everything inside behaves exactly as it did under `{open && children}`:
 * children mount when it opens and unmount once the close has finished, so
 * nothing renders or fetches while collapsed. While closing, the content is
 * inert so focus can't land in something that is on its way out.
 */
export function Reveal({ open, children }: RevealProps) {
  const [present, setPresent] = useState(open);
  const [settled, setSettled] = useState(open);
  if (open && !present) setPresent(true);
  if (!open && settled) setSettled(false);

  useEffect(() => {
    const pending = open ? !settled : present;
    if (!pending) return undefined;
    const wait = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : SETTLE_MS;
    const timer = window.setTimeout(() => (open ? setSettled(true) : setPresent(false)), wait);
    return () => window.clearTimeout(timer);
  }, [open, settled, present]);

  return (
    <div className="reveal" data-open={open ? '' : undefined} data-settled={open && settled ? '' : undefined}>
      <div className="reveal-inner" inert={!open}>
        {present ? children : null}
      </div>
    </div>
  );
}
