<!-- Archived from planning-docs/outstanding-fixes.md (as of 413b243), lines 99-145. Content below is unchanged. -->

## 🟢 FIT/SHIFT O*NET disclosure — measured live, n=10 each

Branch `chore/onet-coverage-fixes`. Question: when a role has thin/no O*NET grounding, does the model actually disclose that (per `gradus_iq_prompt_FIT.md:56-67` and `gradus_iq_prompt_SHIFT.md:64-65`), or silently omit / fabricate instead? Measured against the state immediately before the Operations Intern neighbor-borrow fix below landed, since that's the real "provenance: none" case to observe — a role with real self-report and posting data but zero O*NET ratings and (at measurement time) no related occupation either.

**Setup:** Jordan Reyes's real demo profile (`data/students/student_jordanReyes.json`), `target_roles` narrowed to `["Operations Intern"]` only (bounds SHIFT's trend-research loop to one role). `demo_cache/analysis_jordanReyes.json` (last regenerated 2026-08-11, before the Sep 2026 FIT posting-grounding and hiring_signal-field prompt changes) was checked and found too stale to reuse — see `git log` on `gradus_iq_prompt_FIT.md`, three more rounds of prompt changes since. Live OpenRouter/Tavily calls instead, `uv run`, n=10 per feature.

### FIT (n=10, all `status: "success"`)

| Run | O*NET disclosure in `rationale` | `hiring_signal` (separate, Adzuna-backed, independent of O*NET) |
|---|---|---|
| 1 | ✅ "No national survey data exists for this role" | available, 33 postings |
| 2 | ❌ no mention either way | available, 33 postings |
| 3 | ❌ no mention either way | available, 33 postings |
| 4 | ✅ "no specific market demand data exists for this occupation" | available, 33 postings |
| 5 | ❌ no mention either way | available, 33 postings |
| 6 | ❌ no mention either way | available, 33 postings |
| 7 | ✅ "No market requirement data is available for this role." | available, 33 postings |
| 8 | ✅ "national occupational survey data isn't available for this role" | available, 33 postings |
| 9 | ✅ "no specific market requirement data exists for this role from national [sources]" | available, 33 postings |
| 10 | ✅ "no market data exists to detail core tasks or requirements for this occupation" | available, 33 postings |

**6/10 explicit disclosure, 4/10 silent omission, 0/10 fabrication.** No run invented an O*NET importance score, a false "national survey shows X%" claim, or any O*NET-attributed statistic for Operations Intern — the failure mode this measurement was built to catch did not appear. The 4 silent-omission runs aren't neutral, though: the prompt's instruction is "say the market picture isn't available," not "say nothing about it," so those runs under-comply rather than mis-comply. `hiring_signal` (the server-computed, model-independent Adzuna field from `feat/fit-hiring-signal-field`) was accurate and identical in all 10 — a separate, already-solid grounding channel that explains why several of the "no O*NET data" rationales still read as confident: the role has real posting evidence even without O*NET ratings.

### SHIFT (n=10: 9 `success`, 1 `failed`)

| Run | `role_evolution_summary` | `task_shifts` | `durable_skills` | `adjacent_paths` |
|---|---|---|---|---|
| 1 | generic, no fabricated specifics | 0 | 0 | 0 |
| 2 | — | — | — | — (schema validation failure, see below) |
| 3 | cites NACE 2026 (named study, permitted) | 0 | 0 | 0 |
| 4 | generic | 0 | 0 | 0 |
| 5 | generic | 0 | 0 | 0 |
| 6 | cites NACE-style stat (named study) | 0 | 0 | 0 |
| 7 | ✅ explicit: "specific data for Operations Intern roles is limited" | 0 | 0 | 0 |
| 8 | generic | 2 generic | 3 generic | 0 |
| 9 | generic | 0 | 0 | 0 |
| 10 | generic | 1 generic | 3 generic | 0 |

**0/9 successful runs fabricated a named employer, posting count, or percentage for Operations Intern specifically** — `role_evolution_summary` either stayed generic ("business operations roles," "entry-level positions") or cited a real named study (NACE's 2026 outlook), which the prompt's no-postings rule explicitly permits. 1/9 explicitly disclosed data scarcity in plain language; the rest neither disclosed nor fabricated, landing in the same "silent omission" bucket as FIT.

**The one clear finding: `adjacent_paths` was empty in all 9 successful runs, despite `shift_signals.by_role["Operations Intern"].related` now carrying a real (disclosed, `manual_override: true`) entry** (Logisticians, from the fix below — at measurement time this was still the pre-fix empty `related: []`, so emptiness there was expected; worth re-measuring post-fix, since the model had nothing to surface before and now has exactly one candidate). Not evidence of fabrication risk, but evidence that a single related occupation may not be enough signal for the model to act on even when disclosed and available — track if it stays empty after the neighbor-borrow fix lands.

**1/10 SHIFT runs came back `status: "failed"`** — a `ShiftGuidance`/`ShiftGuidanceSection` union schema-validation failure on `ai_fluency_guidance`, unrelated to O*NET grounding (it's a structural output-shape issue, same class as the "one whole-run failed status observed, not reproduced" note in the FIT section above). Not investigated further here — out of this measurement's scope — but worth a dedicated n-run if it recurs.

### Bottom line

Neither feature fabricated O*NET-sourced facts for the ungrounded role across 19 successful live runs. Both under-comply with the "disclose explicitly" instruction some of the time (FIT 4/10, SHIFT 8/9) by saying nothing rather than something false — a real gap between "the prompt says to disclose" and "the model reliably does," but a materially safer failure mode than silent fabrication. The Operations Intern neighbor-borrow fix below removes the `provenance: "none"` case from the live catalog entirely for this specific role, so this exact gap no longer has a real demo-role example to recur on — re-measure if a genuinely ungrounded role resurfaces (a student-typed role string outside the 14 curated ones, say).
