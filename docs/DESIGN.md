# GradusIQ Design Standards

The rules every new page, tab, panel and dialog follows so the app keeps
one look. They describe what the code does today (after the visual
elevation round, PRs #130 to #134), not an aspiration. When this doc and
the code disagree, the code wins and this doc gets fixed in the same PR.

Read this before building UI. Use the [checklist](#checklist-for-a-new-page-or-feature)
at the end before opening the PR.

---

## 1. Principles

1. **One surface.** Content sits on white elevated cards on a light grey
   page. There is one card style. Do not invent a second.
2. **Calm, institutional, achromatic.** The base palette has no hue. Color
   comes from three places only: the student's institution (the accent),
   meaning (ready / error), and gold for informational labels.
3. **Type carries hierarchy, not boxes.** A serif headline, small-caps
   labels and mono figures do the work. Don't add borders, dividers or
   nested boxes to separate things a heading already separates.
4. **Big moments feel big, routine stays quiet.** The full confirm
   animation is reserved. Most buttons just press.
5. **Never a blank or a dead end.** Every loading state shows the shape of
   what's coming; every empty state says what's missing and offers one way
   to fill it.
6. **Theming and reduced motion are not optional.** Everything uses tokens
   so institution colors flow through, and everything still works with
   motion turned off.

---

## 2. Where the styles live

| File | Owns |
| --- | --- |
| `frontend/src/index.css` | Tokens (`:root`), every component's appearance. |
| `frontend/src/interaction.css` | Behaviour only: timing tokens, press/ripple/liquid fill, tab underline, Reveal, counting figures. No color literals (a test enforces this). |
| `frontend/src/interaction.ts` | Delegated listeners that drive the press effects. Any `.btn` gets them automatically. |
| `components/GuidedTour.css`, `components/ChatPanel.css` | The only component-scoped stylesheets. |

`index.css` is ordered on purpose. The **SURFACE SYSTEM**, **OVERVIEW
SHOWPIECE**, **ACADEMIC + JOB SEARCH** and **SIGN-IN + MOBILE** blocks sit
at the end of the file because they restyle classes defined above them and
win by source order, not specificity.

Rules for new CSS:

- Add a new feature's styles as its own banner-commented block
  (`/* ─── FEATURE NAME ─── */`). If it restyles existing classes, put it
  at the end of the file; otherwise near related sections.
- Win by source order, not by `!important` or stacking selectors.
  `!important` belongs to the reduced-motion rules; the few other uses are
  legacy (see Known gaps). Don't add more.
- Write a short comment saying *why* for any non-obvious rule. The
  existing file is the model.
- Every entry point (the app and each `*-preview.tsx` harness) imports
  `./index.css` and then `./interaction.ts`, in that order. A new preview
  harness must do the same (`interactionLayer.test.mjs` checks it).

---

## 3. Tokens

Use tokens. Never write a raw hex, `rgb()`, px font size or duration in a
component rule when a token exists. If you need a new value, add a token
to `:root` with a comment explaining its role.

### Color

| Token | Use |
| --- | --- |
| `--paper` (#ECECEC) | Page background, and the inset "well" inside a card. |
| `--surface-elevated` (#FFFFFF) | Cards. The house surface. |
| `--surface` (#F7F7F7) | Inputs, selects, secondary buttons, chips. |
| `--line` | Hairline borders on inputs, wells and chips. |
| `--ink` | Body text. |
| `--muted` | Secondary text, labels, captions. |
| `--accent` / `--accent-hover` / `--accent-tint` | Primary actions, links, focus rings, active states. **Institution-themed.** |
| `--accent-text` | Accent-colored text on paper. Under a theme it's a darker shade of the brand color, for contrast. |
| `--on-accent` | Text and icons on an accent fill. |
| `--ready`, `--ready-tint`, `--ready-border` | Something is complete or good. |
| `--error`, `--error-tint`, `--error-tint-border` | Something failed or is wrong. |
| `--pending` | Neutral "not yet". Achromatic on purpose. |
| `--gold`, `--gold-text`, `--gold-tint`, `--gold-line`, `--gold-fill-border` | Informational accents: the card-title tick, stat tiles and chips in Career, "partial" status. **Never themed.** |
| `--neutral-*` | Sign-in/sign-up only. Fixed values the institution theme can't reach. |

Rules:

- **Don't add a new hue.** Green and red mean ready and error; gold is
  informational. A fourth color needs a decision from Noah first.
- **Don't use gold for actions.** Gold is a label color. Buttons and links
  use the accent, so they carry the institution's brand.
- **Don't let rail UI depend on `--accent`.** Under a theme the accent and
  the rail come from the same brand color. Rail elements use the
  `--rail-*` tokens.
- Alpha variants derive from the `*-rgb` triplets, e.g.
  `rgb(var(--ink-rgb) / 0.08)`. That's what lets `institutionTheme.ts`
  recolor a whole family by overriding one triplet.

### Typography

Three families, each with one job:

| Token | Family | Use |
| --- | --- | --- |
| `--font-display` | Newsreader (serif) | Page titles, hero name, display numbers. Usually weight 300 to 400. |
| `--font-ui` | Inter | Everything else: body, labels, buttons. |
| `--font-data` | IBM Plex Mono | Grades, scores, codes, figures in tables. |

Sizes come from the scale only: `--text-xs` (11) `--text-sm` (12)
`--text-base` (14, body) `--text-md` (16) `--text-lg` (18) `--text-xl`
(22) `--text-2xl` (32) `--text-3xl` (40).

- **Labels** (form labels, card section labels, legends): `--text-xs`,
  weight 600, uppercase, `letter-spacing: 0.07em` to `0.08em`, `--muted`.
- **Figures** that line up in columns use `font-variant-numeric:
  tabular-nums` and are right-aligned.
- Placeholder and empty-state copy is upright, never italic (tested).

### Spacing, radius, layout

- Spacing: `--sp-1` (4) through `--sp-12` (48). No other gaps or paddings.
- Radius has three steps: `--radius-sm` (4) for badges and tags,
  `--radius` (6) for controls (buttons, inputs, selects), `--radius-card`
  (8) for cards. `--radius-chip` (6) for chips and inset wells. Circles
  use `50%`, pills `999px`.
- Shadow: cards use `--shadow-card`. That's the only elevation. A card
  inside a card does not get a second shadow (see Surfaces).
- Stage: content column max `--stage-max` (960px), padded `--stage-pad`.

### Motion

Timing tokens live in `interaction.css`:

| Token | Duration | For |
| --- | --- | --- |
| `--t-press` | 90ms | Scale under the pointer. |
| `--t-quick` | 160ms | Hover color, borders. |
| `--t-move` | 220ms | Anything that moves or resizes. |
| `--t-settle` | 320ms | The spring back after a press. |
| `--t-fill` | 520ms | Liquid hover fill, ripple. |
| `--t-data` | 600ms | Figures counting, meters and rings filling. |
| `--t-pulse` | 1600ms | One breath of a skeleton. |
| `--t-spin` | 700ms | One turn of a spinner. |

Easing is `--ease-out` for nearly everything, `--ease-spring` only for the
press release. No other durations or curves.

---

## 4. Surfaces

### The card

Anything that groups content on a page is a card: white, no border,
`--radius-card`, `--shadow-card`, padding `var(--sp-5) var(--sp-6)`
(`var(--sp-4) var(--sp-5)` under 640px).

Use the shared `.card` class. Don't restate the card properties on a new
class unless you have to (and if you do, add the selector to the card rule
in the SURFACE SYSTEM block instead of copying the declarations).

Cards sit `--sp-5` apart.

### Card inside a card

Never stack two shadows. An inner item becomes a quiet **inset well**:
`--paper` background, 1px `--line` border, `--radius-chip`, no shadow.

### Card titles

A small label with a short gold tick under it (2px, `--tick-length` wide,
`--gold`). Not a full-width hairline. Existing classes that do this:
`.overview-block-title`, `.term-courses-heading`, and inside Career
`.editable-section-title` / `.cp-section-title`. Reuse one of them.

### Page titles

Each tab or sub-tab opens with one `h2` page title in the serif, at
`--text-2xl`, weight 400, no rule under it, `--sp-6` below
(`.academic-section-heading`, `.career-section-heading`). The topbar
already names the section, so the page title names the specific page.

### Stat tiles

Headline numbers sit in tiles on the card surface (`.overview-stat`): a
figure, its label right under it. A word in a number slot (a status, not a
figure) goes in a status pill with a dot (`.overview-stat-status--ready /
--partial / --minimal`).

### Exceptions (deliberate)

- **Transcript and resume review** keep their editorial, document-like
  style (`.transcript-paper` with an accent top rule, sticky commit bar).
  They're a reading-and-confirming flow, not a dashboard page.
- **Career Profile's** Details, Career Direction, Skills and Experience
  are borderless rows inside their card ("hierarchy from type, not boxes").
- **Sign-in and sign-up** use the dark neutral shell (`.login-bg` /
  `.login-card`) with the white card, and stay on `--neutral-*` tokens
  because no institution is known yet.
- **The demo dashboard** (`pages/DashboardPage.tsx`) is a separate page
  from the real one (`pages/AuthenticatedDashboard.tsx`) that shares the
  Overview classes. A visual change to Overview must be checked on both.

---

## 5. Buttons

Every button is a `<button>` (or `<Link>`) with `.btn` plus one variant.
Press, ripple and hover fill come for free from `interaction.ts`.

| Variant | When |
| --- | --- |
| `.btn-primary` | The one main action in a card or dialog. At most one per card. |
| `.btn-ghost` | Secondary actions: Cancel, Edit, "View all". |
| `.btn-secondary` | A neutral alternative that needs more presence than ghost. |
| `.btn-danger-ghost` | Remove, delete, disconnect. |
| `.btn-add` | Dashed "add another" under a list. |

Modifiers: `.btn-sm` inside cards and rows, `.btn-full` for a full-width
form submit. Disabled buttons drop to 50% opacity; don't hide them.

Pair order: secondary first, primary last (Cancel, then Save).

### The confirm animation (`ConfirmButton`)

`components/ConfirmButton.tsx` with `useConfirmStatus()` gives a button a
spinner, then a check with a slam and ring on success, or a cross and a
shake on failure.

**It is only for big, record-changing moments.** Today that is exactly:
confirming a transcript or resume review, uploading a transcript or
resume, connecting Canvas, saving the profile-completion step, and
creating an account. It is **not** for routine saves, edits inside a
card, filters, or navigation. On every button it would stop meaning
anything.

Adding a new spot needs Noah's OK, and the file goes into `BIG_MOMENTS`
in `frontend/tests/confirmButton.test.mjs`. Never copy the
`confirm-anim-*` markup or classes by hand; the test fails if you do.

When the success leads somewhere (navigation, swapping the view), `await
succeed()` first so the check is seen.

One big moment isn't a button: finishing a degree requirement. There is
nothing to press, so it doesn't use `ConfirmButton` and isn't in
`BIG_MOMENTS`. Instead the Overview's degree ring reuses the animation's
slam (`confirm-anim-slam`) and throws a gold ring and sparks, with a gold
line under the stat tiles ("Core Math done. 3 of 8 requirements
complete."). It plays once per requirement, ever, and a browser that has
never seen the student's requirements records them silently instead of
celebrating years of old work (`lib/requirementCelebration.mjs`,
`components/RequirementCelebration.tsx`).

Routine saves use a plain `.btn-primary .btn-sm` whose label changes to
"Saving…" with `aria-busy` (see `EditableSection.tsx`).

---

## 6. Forms

- Fields use `.form-group` > `.form-label` + `.form-input` /
  `.form-select` / `.form-textarea`. Two fields side by side: `.form-row`.
- Labels are the uppercase small-caps style, above the field.
- Inputs sit on `--surface` with a `--line` border. Focus is an accent
  border plus a 2px `--accent-tint` ring. Don't remove the focus style.
- Never ship an unstyled browser `<select>`. Use `.form-select`.
- Errors: say what's wrong and how to fix it, next to the field or in an
  `.analysis-failed`-style box (error tint, error text). A submit error
  gets focus and is announced (`hooks/useErrorFocus.ts`, with
  `role="alert"` and `tabIndex={-1}` on the message).

---

## 7. States: loading, empty, error

Every view that fetches must design all three.

**Loading.** Show the shape, not a spinner on a blank page.
- Lists: `<SkeletonRows label="Loading …" />` (`components/Skeleton.tsx`),
  or `variant="cards"` for a list of cards.
- Analysis panels: `.analysis-loading` with a `.spinner` child; the CSS
  draws it as skeleton bars (tested).
- Skeletons breathe on `--t-pulse`. They never sweep or shimmer.
- A spinner alone is only for inline, in-button or very short waits.
- Long document processing uses `ProcessingStatus` with named stages.

**Empty, inside a card.** `<EmptyState icon="…" action={…}>` from
`components/EmptyState.tsx`: an icon, one line saying what's missing, at
most one action that fills it. Add an icon to `ICON_PATHS` if none fits.

**Empty, whole page** (no transcript, no resume yet). `.real-empty`: a
centered welcome card with the sparkle mark, an `h3`, one line of `p`,
and one primary button. It should read as a starting point, not an error.

**Error.** `.analysis-failed`: the reason first, in plain words; a retry
line under it, subordinate. Don't show raw error codes or stack text.

---

## 8. Motion

- Sections fade and rise in on switch (`.stage-section`); tabs move one
  underline and slide the panel from the side the student moved toward.
  New tabs get this by using `.academic-tabs` / `.academic-tab`.
- Expanding content uses `<Reveal open={…}>`, not `{open && …}`.
- Numbers that change use `<AnimatedNumber>`. `countIn` (count up from
  zero on first render) is only for a page's few headline figures.
- A staggered entrance is a showpiece treatment (Overview). Don't add one
  to every page.
- **Reduced motion**: the global rule in `index.css` turns off all
  animations and transitions. Design so nothing depends on an animation
  finishing to be visible: animate *from* a hidden state (`backwards`
  fill), never *to* a visible one.

---

## 9. Theming

- Institution colors are applied at runtime by
  `lib/institutionTheme.ts`, which overrides the `--accent-rgb`,
  `--institution-accent-rgb` and rail triplets. Anything built on tokens
  is themed for free. A hardcoded color is not.
- Check new UI under at least the neutral theme and one brand theme
  (TAMU maroon or SMU blue). Text on an accent fill must stay readable.
- Sign-in/sign-up must not use themeable tokens.
- **Dark mode is out of scope.** Don't add `prefers-color-scheme` rules
  piecemeal; it would need its own round.

---

## 10. Layout and responsive

- Desktop: rail on the left (`--rail-w`), content in the stage.
- **640px is the phone breakpoint.** Use `@media (max-width: 640px)` for
  phone adjustments. The rail becomes a drawer at 768px; sign-in shows its
  pitch from 900px. Don't introduce a new breakpoint value without a
  reason (there are a few one-offs already, see Known gaps).
- At phone width: cards keep their look with less padding, multi-column
  grids drop to one column (stat tiles go two across), header rows wrap
  rather than squeezing a button's label.
- Check every new page at 390px wide. No horizontal page scroll.

---

## 11. Accessibility

- Visible focus on everything interactive (`:focus-visible` accent
  outline is global; don't override it to `none`).
- Dialogs: `role="dialog"`, `aria-modal="true"`, a labelled title, focus
  moved in on open and returned on close, `useFocusTrap`, Escape closes.
  Copy `EditCoursesDialog.tsx`.
- Icon-only buttons get an `aria-label` (and a `title` for hover).
- Loading regions announce themselves (`role="status"` plus an `.sr-only`
  label, as `SkeletonRows` does). Busy buttons set `aria-busy`.
- Decorative SVGs get `aria-hidden="true"`.
- Body text on its surface meets 4.5:1. Don't put `--muted` text on
  `--paper` inside a tinted fill without checking.

---

## 12. Copy

- The product is **GradusIQ**, one word. Never "Gradus IQ" or the old
  "CampusIQ" in UI (a test checks for CampusIQ).
- Speak to the student as "you". Plain words, short sentences.
- Page titles are feature names in Title Case ("Course Discovery", "Job
  Search"). Card titles, buttons and messages use sentence case ("Plan
  this term", "Upload resume"), unless they name a feature.
- Buttons say what happens: a verb and an object ("Upload transcript"),
  not "Submit" or "OK".
- In-flight labels end in an ellipsis character (`Saving…`, not `...`).
- Empty states say what's missing and what to do, in one line.

---

## 13. Adding a page or tab

Beyond the visuals:

- **Nav**: add the tab to the relevant list in
  `pages/AuthenticatedDashboard.tsx` (`NAV_ITEMS`, `ACADEMIC_SUB_TABS`,
  `CAREER_SUB_TABS`) and its `*_VALUES` list.
- **URL state**: tabs and filters live in the query string. Follow
  [url-state-guide.md](url-state-guide.md).
- **Tour**: if the page is a main destination, consider whether the
  guided tour (`components/GuidedTour.tsx`) should mention it.
- **Demo dashboard**: if the page appears on Overview, check
  `pages/DashboardPage.tsx` too.

### Checking your work

Run the frontend (`cd frontend && npm run dev`) and open
`/authenticated-dashboard-preview.html` for a signed-in dashboard with
mock data, or the other `*-preview.html` pages for sign-up, transcript and
review flows. The preview pages don't load Google Fonts; inject the fonts
stylesheet from `index.html` before taking screenshots, or the type will
be wrong. `npm test` runs the design guard tests along with the rest.

---

## Checklist for a new page or feature

- [ ] Content sits on `.card` (white, shadow); nested items are inset wells.
- [ ] One serif `h2` page title; card titles use the gold-tick label.
- [ ] Only tokens for color, size, spacing, radius, duration. No new hue.
- [ ] At most one `.btn-primary` per card; other actions ghost.
- [ ] No `ConfirmButton` unless it's a record-changing moment Noah agreed to.
- [ ] Loading shows skeletons; empty uses `EmptyState` or `.real-empty`; errors say why and offer a retry.
- [ ] Works with reduced motion; nothing waits on an animation to appear.
- [ ] Looks right at 390px and on a branded theme.
- [ ] Keyboard reachable, visible focus, dialogs trap focus and close on Escape.
- [ ] Copy is GradusIQ, sentence case, verb-first buttons.
- [ ] Overview changes checked on the demo dashboard too.
- [ ] `npm test` passes.

---

## Known gaps

Places the code doesn't fully follow these rules yet. Fix them when you're
in the area; don't copy them.

- **Breakpoints.** Besides 640, 768 and 900, there are one-off queries
  at 480, 560, 720, 760 and 880px.
- **Career tab duplicates.** The `CAREER TAB — VISUAL REDESIGN` block
  restates the card style scoped to `.career-subtab-panel` from before the
  card became app-wide. It's redundant with the SURFACE SYSTEM block.
- **Title casing** is mixed in card titles ("Feature Readiness" vs
  "Academic readiness").
- **The section entrance** (`.stage-section`) uses a raw `0.22s ease`
  instead of `--t-move` / `--ease-out`.
- **Button transitions** in `index.css` (`.btn`) use raw `0.12s`;
  `interaction.css` overrides them, so it's harmless but misleading.
- **`!important`** outside the reduced-motion rules: four legacy uses in
  the Degree Schedule styles. One of them sets `color: var(--text)`, a
  token that doesn't exist, so that rule does nothing.
- The ConfirmButton CSS comment says the app has no success color; it has
  `--ready`. The decision stands (success is shown by motion, not color),
  but the reason in that comment is out of date.

---

## Decision log

| Date | Decision | By |
| --- | --- | --- |
| 2026-10-13 | The full confirm animation is only for big, record-changing moments. | Noah |
| 2026-10-13 | White elevated cards are the house surface style. | Noah |
| 2026-10-13 | Dark mode is out of scope for now. | Noah |
| 2026-10-14 | The demo dashboard stays a separate page that shares the Overview look. | Noah |
| 2026-10-15 | GPA history: the full term-by-term chart lives on the GPA Calculator, and Overview only gets a small sparkline. Term GPA is drawn as points, not bars, so the axis can start near the lowest GPA. | Noah |
| 2026-10-16 | Finishing a degree requirement is a big moment. It gets the confirm animation's slam and ring (plus gold sparks) on the Overview ring, once per requirement, never replayed. | Noah |

Add a row when a design decision is made, so the next person doesn't
relitigate it.
