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

// Replayable animations are started by an attribute; clear it once they finish.
const REPLAYED: Record<string, string> = {
  'press-ripple': 'data-rippling',
  'tab-panel-in': 'data-tab-entering',
};

function onAnimationDone(e: AnimationEvent) {
  const attribute = REPLAYED[e.animationName];
  if (attribute && e.target instanceof Element) e.target.removeAttribute(attribute);
}

// ── tabs ──
// The underline travels between tabs, and the panel arrives from the side the
// student moved toward. Driven by aria-selected, so it follows every tablist
// without the component knowing: the observer runs after React commits the new
// selection and before the browser paints it.

const TABLIST = '[role="tablist"]';
const selectedIndex = new WeakMap<Element, number>();

function syncTablist(list: HTMLElement, selectionChanged: boolean) {
  const tabs = Array.from(list.querySelectorAll<HTMLElement>('[role="tab"]'));
  const index = tabs.findIndex((tab) => tab.getAttribute('aria-selected') === 'true');
  if (index < 0) return;
  const tab = tabs[index];
  list.style.setProperty('--tab-x', `${tab.offsetLeft}px`);
  list.style.setProperty('--tab-bottom', `${tab.offsetTop + tab.offsetHeight}px`);
  list.style.setProperty('--tab-w', `${tab.offsetWidth}px`);
  list.setAttribute('data-tab-indicator', '');

  const previous = selectedIndex.get(list);
  selectedIndex.set(list, index);
  if (!selectionChanged || previous === undefined || previous === index || reducedMotion.matches) return;
  const panel = document.getElementById(tab.getAttribute('aria-controls') ?? '');
  if (!panel) return;
  panel.style.setProperty('--tab-from', index > previous ? '1' : '-1');
  panel.removeAttribute('data-tab-entering');
  void panel.offsetWidth; // replay on rapid switching
  panel.setAttribute('data-tab-entering', '');
}

function tablistsTouchedBy(node: Node): HTMLElement[] {
  if (!(node instanceof HTMLElement)) return [];
  const lists = Array.from(node.querySelectorAll<HTMLElement>(TABLIST));
  const own = node.closest<HTMLElement>(TABLIST); // the node itself, or a tab added to an existing list
  return own ? [own, ...lists] : lists;
}

const tabObserver = new MutationObserver((records) => {
  const selected = new Set<HTMLElement>();
  const mounted = new Set<HTMLElement>();
  for (const record of records) {
    if (record.type === 'attributes') {
      const list = (record.target as Element).closest<HTMLElement>(TABLIST);
      if (list) selected.add(list);
    } else {
      record.addedNodes.forEach((node) => tablistsTouchedBy(node).forEach((list) => mounted.add(list)));
    }
  }
  mounted.forEach((list) => { if (!selected.has(list)) syncTablist(list, false); });
  selected.forEach((list) => syncTablist(list, true));
});

function resyncTablists() {
  document.querySelectorAll<HTMLElement>(TABLIST).forEach((list) => syncTablist(list, false));
}

document.addEventListener('pointerover', onPointerCross, { passive: true });
document.addEventListener('pointerout', onPointerCross, { passive: true });
// Capture, so a component handler that stops propagation can't suppress it.
document.addEventListener('click', onClick, { capture: true, passive: true });
document.addEventListener('animationend', onAnimationDone);
document.addEventListener('animationcancel', onAnimationDone);
tabObserver.observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ['aria-selected'] });
window.addEventListener('resize', resyncTablists, { passive: true });
void document.fonts?.ready.then(resyncTablists); // tab widths change when the web font lands
resyncTablists();

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    document.removeEventListener('pointerover', onPointerCross);
    document.removeEventListener('pointerout', onPointerCross);
    document.removeEventListener('click', onClick, { capture: true });
    document.removeEventListener('animationend', onAnimationDone);
    document.removeEventListener('animationcancel', onAnimationDone);
    tabObserver.disconnect();
    window.removeEventListener('resize', resyncTablists);
  });
}
