# URL State — How Deep-Linking Works Here

Tabs, sub-tabs, and a couple of filters used to live in plain `useState`.
That meant refreshing the page always bounced you back to Overview, and
there was no way to send someone a link straight to, say, Career
Intelligence — the URL never changed no matter what you clicked.

As of this round, the dashboard's nav state (top-level section, Academic
sub-tab, Career sub-tab), Term Planner's selected term, and Degree
Schedule's selected year all live in the URL's query string instead. This
doc covers how that works and exactly what to do when you add a new
page, tab, or filter that should behave the same way.

## The two hooks

Both live in `frontend/src/hooks/`.

### `useUrlParams()`

The shared primitive. Returns `{ getParam, setParams }`:

- `getParam(key, defaultValue, allowedValues)` reads one param, falling
  back to `defaultValue` if it's missing or holds a value outside
  `allowedValues` — a stale link, a typo, an old bookmark never breaks
  the page.
- `setParams({ key: value, other: null, ... })` writes **one or more**
  params at once, atomically. Pass `null` for a key to remove it from the
  URL entirely.

Use this directly whenever a single user action needs to change more
than one param together — e.g. switching the top-level dashboard section
*and* resetting that section's sub-tab to its default.

### `useSearchParamState(key, defaultValue, allowedValues)`

A single-key convenience wrapper around `useUrlParams()`, shaped like
`useState`: returns `[value, setValue]`. Use this for the common case —
a filter, a single set of tabs — where a page only ever changes one key
per interaction. This is what Term Planner and Degree Schedule's year
tabs use.

### The one rule that actually matters

**Never call two independent `useSearchParamState` setters (or two
separate `useUrlParams()` instances) from the same event handler.**

`react-router-dom`'s `useSearchParams()` snapshots the current URL once
per render. If you call its setter twice before React re-renders, the
second call builds its new URL from the *same stale snapshot* the first
call used — it silently overwrites the first change instead of merging
with it. This bit the dashboard shell's `navigateTo` function during
this work (it used to call `setActiveSection` and `setAcademicSubTab`
back to back) and is why `useUrlParams`/`setParams` exists as a batched
alternative. If a handler needs to touch more than one param, reach for
`useUrlParams()` and make one `setParams` call with everything that
changes.

## Conventions

- **History: always `replace`, never `push`.** A tab or filter is not a
  separate page. If every tab click pushed a new history entry, Back
  would replay your last ten tab clicks instead of taking you to the
  previous page. Both hooks already do this — you don't need to think
  about it.
- **Omit the default from the URL.** When a value equals its own
  default, the param is removed rather than written. A page in its
  default state has a clean URL (`/dashboard`, not
  `/dashboard?section=overview&academic=overview`). This is automatic in
  `useSearchParamState`; if you're using `useUrlParams` directly, pass
  `null` yourself when a value is the default.
- **Unknown values fall back, never crash.** Always pass a real
  `allowedValues` list — not an escape hatch, the actual mechanism that
  makes a stale/garbage link safe.
- **`allowedValues` can be computed dynamically.** It doesn't have to be
  a static literal array. Term Planner's valid term keys come from
  fetched data and are recomputed every render — the hooks have no
  internal state of their own, so a value that's invalid this render and
  valid next render (once data loads) just resolves correctly on its
  own, no extra wiring needed.

## Current params

| Param | Values | Owner | Default |
|---|---|---|---|
| `section` | `overview` \| `academic` \| `career` | `AuthenticatedDashboard.tsx` / `DashboardPage.tsx` (demo) | `overview` |
| `academic` | `overview` \| `gpa-calculator` \| `grade-calculator` \| `course-discovery`* | same | `overview` |
| `career` | `overview` \| `intelligence` \| `job-search` \| `profile` | same | `overview` |
| `term` | a term key, e.g. `2026-Fall` | `TermPlanner.tsx` | the smart pick from `pickDefaultTermKey` |
| `year` | an academic year's starting calendar year, e.g. `2026` | `DegreeScheduleYears.tsx` | the in-progress year, else the earliest |

\* The demo dashboard's `AcademicSubTab` union is missing `grade-calculator` — an
existing difference between the real and demo nav, not something this
round introduced.

Each page owns its own param namespace independently — there's no
central registry. When you add one, just pick a name not already in this
table and update it here.

## Adding this to a new page, tab, or filter

1. **Decide: one key, or several that change together?** Most cases
   (a filter, an isolated set of tabs) are one key — use
   `useSearchParamState`. If clicking something resets more than one
   piece of state at once (like the dashboard's top-level nav), use
   `useUrlParams()` directly and make a single `setParams` call.
2. **Pick a short param name** that isn't already in the table above,
   and add your row once it's in.
3. **List every valid value** for `allowedValues` — pull it from
   whatever array/union already enumerates the tabs if one exists
   (e.g. `NAV_ITEMS`), or compute it from loaded data the same way
   `TermPlanner` does for term keys.
4. **Swap the `useState` for the hook.** The return shape is
   intentionally `useState`-compatible — this is usually a very small
   diff, not a rewrite. Replace any direct `setXxx` calls your old code
   made in more than one place per handler if those need to become
   `setParams({...})` calls (see the rule above).
5. **Verify it for real**, not just in your head:
   - Click through, then check `page.url()` has the param you expect.
   - `page.reload()` (or a fresh `page.goto` with the param already in
     the URL) and confirm the right thing renders — this is the actual
     point of the whole exercise.
   - Load with a garbage/unknown value for your param and confirm it
     falls back cleanly instead of crashing or rendering blank.
   - If your component is only reachable through a Playwright preview
     harness that uses `MemoryRouter` or `HashRouter`, that's fine —
     `useSearchParams()` works the same way under either, just make sure
     it isn't a `MemoryRouter` with no real address bar if you need
     `page.url()` itself to reflect the change (see
     `authenticatedDashboardPreview.tsx`'s comment on why it uses
     `BrowserRouter` for exactly this reason).

## Known gaps

Not every tab/filter got this treatment yet — scoped out of this round on
purpose, not forgotten:

- **Job Search's role filter** (`JobSearchPanel.tsx`) and **Career
  Optimization's academic/optimized view toggle**
  (`CareerOptimizationPanel.tsx`) are both still plain `useState`. Lower
  traffic, simpler state — good candidates for the next pass using the
  exact recipe above.
- **Degree Schedule's year tabs have no end-to-end browser test of their
  own yet** (`DegreeScheduleYears.tsx`'s existing tests are source-level/
  mocked, not Playwright-driven). The URL wiring itself is verified by
  TypeScript and the existing test suite, but there's no
  click-then-reload assertion the way there is for the dashboard shell
  and Term Planner — worth adding alongside whatever harness eventually
  exercises that component end to end.
- `CareerSnapshotPanel.tsx`'s `onViewFull` callback (meant to deep-link
  straight to a specific GAP/FIT/SHIFT card) has no current caller — if
  it gets wired up, that's the natural hook point for a fourth
  Career-Intelligence-related param.
