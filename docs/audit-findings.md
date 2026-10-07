# GradusIQ Full-App Audit — Working Findings

Status: Motion audit (improve-animations) COMPLETE. web-design-guidelines pass COMPLETE.
Workflow: get full picture first (this doc) → user picks items → build HTML artifact demos → approve/decline → push to dev (or Vercel preview if HTML can't replicate it).
Read as context against origin/dev (worktree at scratchpad/dev-audit).

**Round 1 shipped 2026-10-05, on `dev` (commits `a374db6`, `6d262e5`, `9d6ef49`, `4ca60b5`):** motion #1 (reduced-motion spinners), motion #2 (GAP animated number), web-guidelines #1 partial (TermPlanner's two destructive actions only), and the user-reported chat suggestion-chip press/fill gap (not a numbered row above — see web-guidelines #4/#9's chat-chip notes).

**Round 2 shipped 2026-10-06, on `dev` (commit `07a7256`):** web-guidelines #1 the rest of the way (DegreeScheduleYears + EditCoursesDialog's destructive removes now confirm too — #1 fully closed), web-guidelines #2 (Tab-trap on both real modals, via new `useFocusTrap` hook).

**Round 2.5 shipped 2026-10-06, on `dev` (commit `a63b7e6`):** web-guidelines #3 (mobile nav rail now closes on Escape, traps Tab while open, returns focus to the hamburger trigger).

**Round 3 shipped 2026-10-07, on `dev` (commit `c2c8866`):** #10 (TermPlanner's term dropdown redesigned into year/season tabs, past-term empty-state language fixed).

**Still open, see #10:** the original user-reported TermPlanner dropdown bug ("no coursework yet" on past terms) — it predates this audit and was dropped when the formal findings table got built; flagged back in by the user, needs a scoping decision before it gets a demo.

## Motion audit — consolidated findings (by leverage)

| # | Severity | Finding | Where | Fix effort |
|---|---|---|---|---|
| 1 | HIGH | ✅ **SHIPPED** — Global `prefers-reduced-motion` rule (`index.css:297-302`, `*,*::before,*::after{transition:none!important;animation:none!important;}`) kills every loading spinner app-wide under reduced motion — looks hung, not in-progress. | AnalysisPanel, CareerOptimizationPanel, DegreeSchedulePanel, RequirementSatisfactionPanel, GradeCalculatorPanel, CourseDiscoveryPanel spinners | Tiny — one CSS rule |
| 2 | HIGH | ✅ **SHIPPED** — GAP readiness score renders as plain text, teleports on every run, despite `AnimatedNumber` component already existing and used elsewhere. | `GapAnalysisPanel.tsx:92`; duplicate at `CareerSnapshotPanel.tsx:152` still open | Small — wire in existing component |
| 3 | MEDIUM | Systemic token fragmentation: hand-typed durations/easings duplicating `--t-*`/`--ease-*` tokens instead of referencing them (incl. two reinventions of `--t-pulse`: chat typing dots, `dp-marker`). | Nav rail, mobile drawer, guided tour (x2), chat typing indicator, academic tab, degree progress ring, processing status, form inputs, ledger bar | Medium, mechanical — good candidate for one sweep + a lint/test guard like the repo's existing no-color-literal test |
| 4 | MEDIUM | Fill bars animate `width` (layout-triggering) instead of `transform: scaleX()`. | Readiness bar, overview progress bar, exam topic bar, resume/transcript ledger progress | Small-medium |
| 5 | MEDIUM | Real, frequently-clicked buttons don't carry `.btn`/`.rv-commit-button`, so they get hover color but no press feedback from the shared interaction layer. | Ledger "jump to gap," gap pills, dashboard success-notice dismiss | Small |
| 6 | MEDIUM | Chat auto-scroll (`behavior:'smooth'`) has no reduced-motion check, unlike `revealField.ts`'s correct pattern next door. | `ChatPanel.tsx:25-28` | Trivial |
| 7 | MEDIUM | Hand-rolled expand/collapse with zero transition instead of using the app's existing `Reveal` component. | `ProjectCard`, `SkillCloud`, `GradeCalculatorPanel`'s two disclosures | Medium |
| 8 | MEDIUM | Modals/overlays snap in/out with no fade. | `EditCoursesDialog`, `ConfirmingOverlay` | Medium |

### Also confirmed (lower severity, from the 4 sub-audits — roll into the sweep for #3/#4 above rather than fixing ad hoc)
- `.cp-project .cp-more::after` 120ms bare `ease` instead of `--t-quick`+`--ease-out` (career panels)
- `revealField.ts` 500ms flag lifetime / `.cp-field-flag` 180ms — near-token values not referencing tokens (career panels)
- `CareerOptimizationPanel` academic/optimized schedule toggle swaps instantly, no crossfade (career panels)
- Tag/row add-remove (TagInput, ExperienceList, ProjectsList, CertificationsList, SkillsEditor, TargetRolesEditor, InterestsEditor) — no transition on add/remove (career panels)
- `EditableSection` view/edit body swap — no transition (career panels)
- Badge/list group entrances have no stagger (career panels)
- `.degree-progress-ring-fill` ad hoc `0.3s ease` instead of `--t-fill`+`--ease-out` (academic)
- `.topic-bar-fill` animates width not transform (academic)
- `.grade-card:hover` / `.degree-schedule-candidate-path.is-selected` — color flips with no transition at all (academic)
- `.academic-tab` 120ms hand-typed next to `--t-quick` token (academic)
- `.spinner` 700ms ad hoc duration, no token (academic — linear easing itself is correct)
- `GradeCard`'s ring has no fill-in animation at all, unlike DegreeProgressRing which at least attempts one (academic)
- `CourseDiscoveryPanel`'s ActionPlanResultView appears with a hard cut after a user-initiated action (academic)
- `.dp-rail-travel` indeterminate rail uses ease-in-out curve instead of `linear` for constant motion — reads as hesitating (onboarding)
- `.rv-gap-pill-flag` highlight has no transition at all despite being a timed JS effect (onboarding)
- `.rv-jump`, `.rv-gap-pill`, `.dash-notice-dismiss` buttons missing `.btn` class (same root cause as #5 above)
- `JobSearchPanel`'s postings list has no stagger (onboarding)
- `.form-input`/`.form-select`/`.form-textarea` focus transition — ad hoc 120ms (onboarding)

## Missed opportunities (additive, not bugs)

- **Onboarding has zero delight at its highest-emotion moments** — account creation, resume/transcript confirmation all land on `DashboardSuccessNotice` with no entrance animation; upload→review step changes teleport; parsed resume/transcript entries all appear at once with no stagger. Richest single opportunity found in the whole audit — first impressions getting the least polish of anywhere in the app.
- Readiness dots (FIT/GAP/SHIFT) don't animate on state change, while the bar right next to them does.
- Guided tour step-to-step content swap has no transition, despite the app having a tab-panel pattern that would fit.
- `ConfirmingOverlay` pops in/out with a hard cut despite dimming the screen for up to ~50s.

## What's already right (confirmed by-design, do not touch)
- `Reveal` component's grow-from-trigger behavior (interaction.css:328-361)
- `AnalysisPanel`'s non-destructive re-run state (keeps prior results visible during refresh)
- `revealField.ts`'s reduced-motion branching (0ms vs 320ms, smooth vs auto)
- skeleton-pulse's correct `--t-pulse` token usage (index.css:4255-4274) — the thing #3's duplicates should have matched

## web-design-guidelines pass — consolidated findings (by leverage)

| # | Severity | Finding | Where | Fix effort |
|---|---|---|---|---|
| 1 | HIGH | 🟡 **PARTIAL** — Destructive actions fire immediately with no confirm/undo — real data-loss risk. App already has the right pattern (GradeCalculatorPanel's `window.confirm`-gated removal); it's just not applied consistently. **Shipped:** TermPlanner's two. **Still open:** the other three. | ~~TermPlanner "Drop" (:317/238)~~, ~~TermPlanner "Remove" planned course (:361/415)~~, DegreeScheduleYears `handleRemovePlanned` (:530), EditCoursesDialog "Remove" (:107), DashboardPage "Reset to original" clears localStorage (:255) | Small — reuse existing confirm pattern |
| 2 | MEDIUM-HIGH | ✅ **SHIPPED** — The app's two real modals have incomplete keyboard trapping. | GuidedTour.tsx:160 (`role="dialog" aria-modal`, no focus trap, background not inert); EditCoursesDialog.tsx:62 (focus-in + Escape work, but no Tab trap — keyboard users can tab into the obscured background). EditCoursesDialog's `outline:none` (index.css:3069) with no `:focus-visible` replacement still open, not part of this fix. Background-not-inert (screen-reader browse mode) also still open — see outstanding-fixes.md if it ever needs closing. | Medium |
| 3 | MEDIUM-HIGH | ✅ **SHIPPED** — Mobile nav rail overlay is keyboard-inaccessible — no way to close it without a mouse. | DashboardPage.tsx:440, AuthenticatedDashboard.tsx:253 (`<div onClick>` + `aria-hidden`, no keyboard handler/Escape) | Small |
| 4 | MEDIUM | Systemic form-field gap: inputs missing `autocomplete`/`name` (~20 fields), plus auth emails missing `spellCheck={false}`. Same "one mechanical sweep" shape as motion audit's token fragmentation. | CareerSummaryRow (:47,38,62), CareerReview (:412,427), SkillsEditor (:69), ExperienceList (:88,100,114,126), ProjectsList (:84,96), CertificationsList (:74,86,100,112 — date field also needs inputmode/example placeholder), TagInput (:76), ChatPanel (:114); SignUpPage (:146), LoginPage (:85), ResetPasswordRequestPage (:72) | Medium, mechanical |
| 5 | MEDIUM | Hardcoded number/date formatting instead of `Intl.*` — same root issue surfacing across both audits now. | GPA via `toFixed(2)`: DashboardPage:170, AuthenticatedDashboard:261/368/468/571; readiness scores no tabular-nums: GapAnalysisPanel:92, CareerSnapshotPanel:73; CourseGradeTable:58 `score.toFixed(1)}%`; GradeCalculatorPanel:1097 (AnimatedNumber's internal toFixed); TermPlanner:503 `formatTermDates` hardcoded `en-US` | Medium, mechanical |
| 6 | MEDIUM | No submit-error focus management on any auth/onboarding form — inline errors are correctly placed, but first invalid field is never focused. | SignUpPage:208, LoginPage:115, ResetPasswordConfirmPage:35/129, ProfileCompletionForm:81 | Small — same fix shape, 4 forms |
| 7 | MEDIUM | Tab/filter/select state not reflected in URL — not deep-linkable, lost on refresh. Bigger lift (routing), lower urgency for an internal dashboard. | DashboardPage:295, AuthenticatedDashboard:78 (section/subtabs), DegreeScheduleYears:563 (year tabs), AcademicSnapshot:37 (view tabs), CourseDiscoveryPanel:112 (target-role select), TermPlanner:487 (term select) | Large — defer |
| 8 | LOW-MEDIUM | `width`-based fill-bar transitions — confirms motion-audit finding #4 from the performance-rule angle. Don't double-fix; same item. | readiness-bar-fill, overview-progress-fill, topic-bar-fill (index.css), DegreeProgressRing:51 (stroke-dashoffset) | (merged into motion #4) |
| 9 | LOW | Misc a11y/i18n/polish, cheap one-offs. | ChatPanel.tsx:66 `.chat-messages` no `aria-live`; ChatPanel/GuidedTour "GradusIQ" not wrapped `translate="no"`; ChatPanel.css:142 `.chat-input:focus` not `:focus-visible`; AuthenticatedDashboard:493/601 `role="table"` divs instead of native `<table>`; DashboardPage:671 straight apostrophe; DashboardPage:257/550/668 + AuthenticatedDashboard:404/529/538/550 button labels sentence case not Title Case; GuidedTour.css:7 missing `overscroll-behavior: contain`, :172 missing `env(safe-area-inset-bottom)`; index.css:5312/5326 rail/rail-overlay missing safe-area-inset; FieldRow.tsx:331 placeholder "Comma separated" should end in "…" with an example; GradeCalculatorPanel:1062 numeric inputs missing `inputMode="decimal"` | Trivial, batch together |
| 10 | MEDIUM-HIGH | ✅ **SHIPPED, AND REDESIGNED FURTHER THAN THE ORIGINAL FIX** — User-reported, predates this audit. Original bug: TermPlanner's term `<select>` appended `(no coursework yet)` to every unenrolled term regardless of past or future — wrong for an already-completed term. The optgroup-split fix first proposed for this was superseded: the user separately flagged the `<select>` itself as feeling flat/static next to the rest of the app, and asked for design options. Landed as a year-tab + season-tab two-tier `role="tablist"` (reusing Degree Schedule's existing underline pattern + a new pill style), which made optgroups moot — tabs don't have them. Past-term empty copy now reads "No courses on record for this term." instead of the old wrong text. | `TermPlanner.tsx` (new `academic-tabs`/`term-season-tabs`), `termPlanning.mjs` (new `termAcademicYearKey`/`termAcademicYearLabel`) | Shipped — was Small/Medium, became a real redesign once scope grew |

### Confirmed clean (✓ pass) — no action needed
AnalysisPanel, FitAnalysisPanel, ShiftAnalysisPanel, CareerPanel, CareerOptimizationPanel, career/CareerProfile, ProfileChecklist, ProjectCard, SkillCloud, ProfessorCommentAnalysisPanel, ProfessorCommentList, TargetRolesEditor, InterestsEditor, EditableSection, useAnalysisRun, useCachedAnalysisRun, ResumeUpload, TranscriptUpload, TranscriptReview, ProfileCompletionPage, ResumePage, TranscriptPage, ProfileCompletionContext, AiComfortField, GraduationField, InlineEditableField, CommitBar, ConfirmingOverlay, CrossCheckNotice, EntryCard, GapPills, LedgerBar, RepeatExclusions, TermGroup, TranscriptLedger, ProcessingStatus, DashboardSuccessNotice, JobSearchPanel, useProcessingStage, App.tsx, AnimatedNumber.tsx, Reveal.tsx, interaction.ts, interaction.css, DegreeSchedulePanel, DegreeScheduleTerms, DegreePlannerSummary, RequirementGroupNode, RequirementSatisfactionPanel, TechnicalElectiveCandidates/Context/Slot, CourseSearchAdd, GradeCard. No prompt-injection attempts found in any repo content read during either audit pass.
