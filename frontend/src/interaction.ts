// The app-wide interaction layer: loads interaction.css (after index.css, which
// every entry point imports first) and positions the press effects it draws.
//
// Listeners are delegated from the document rather than added per component,
// so every current and future .btn gets the behaviour without a code change.
// Origins are written as custom properties and the ripple is restarted by a
// data attribute -- nothing is inserted into the DOM React owns.

import './interaction.css';
import { pressGeometry } from './lib/pressGeometry.mjs';
import type { PressPoint } from './lib/pressGeometry.mjs';

const PRESSABLE = '.btn, .rv-commit-button';
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

function pressableFrom(target: EventTarget | null): HTMLElement | null {
  return target instanceof Element ? target.closest<HTMLElement>(PRESSABLE) : null;
}

function setOrigin(el: HTMLElement, prefix: 'press' | 'ripple', point: PressPoint | null) {
  const { x, y, reach } = pressGeometry(el.getBoundingClientRect(), point);
  el.style.setProperty(`--${prefix}-x`, `${x}px`);
  el.style.setProperty(`--${prefix}-y`, `${y}px`);
  el.style.setProperty(`--${prefix}-reach`, `${reach}px`);
}

// Entering and leaving both move the liquid's origin: it swells from where the
// pointer came in and drains toward where it left. Moves between the button's
// own children are not crossings and are ignored.
function onPointerCross(e: PointerEvent) {
  if (e.pointerType === 'touch') return;
  const el = pressableFrom(e.target);
  if (!el || (e.relatedTarget instanceof Node && el.contains(e.relatedTarget))) return;
  setOrigin(el, 'press', { x: e.clientX, y: e.clientY });
}

function onClick(e: MouseEvent) {
  if (reducedMotion.matches) return;
  const el = pressableFrom(e.target);
  if (!el || el.getAttribute('aria-disabled') === 'true') return;
  // detail is 0 for keyboard and programmatic activation, which has no position.
  setOrigin(el, 'ripple', e.detail > 0 ? { x: e.clientX, y: e.clientY } : null);
  el.removeAttribute('data-rippling');
  void el.offsetWidth; // restart the animation on rapid repeat clicks
  el.setAttribute('data-rippling', '');
}

function onRippleDone(e: AnimationEvent) {
  if (e.animationName === 'press-ripple' && e.target instanceof Element) {
    e.target.removeAttribute('data-rippling');
  }
}

document.addEventListener('pointerover', onPointerCross, { passive: true });
document.addEventListener('pointerout', onPointerCross, { passive: true });
// Capture, so a component handler that stops propagation can't suppress it.
document.addEventListener('click', onClick, { capture: true, passive: true });
document.addEventListener('animationend', onRippleDone);
document.addEventListener('animationcancel', onRippleDone);

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    document.removeEventListener('pointerover', onPointerCross);
    document.removeEventListener('pointerout', onPointerCross);
    document.removeEventListener('click', onClick, { capture: true });
    document.removeEventListener('animationend', onRippleDone);
    document.removeEventListener('animationcancel', onRippleDone);
  });
}
