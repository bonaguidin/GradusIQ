"""Build cached career-analysis output for the demo.

This is the demo bridge between the Python AI engine and the React dashboard.
Rather than stand up a live server (Phase 2), we run the orchestrator once per
student and write the result to ``data/demo_cache/analysis_<slug>.json``, which
the backend serves through authorized routes. This also de-risks the live demo:
nothing calls OpenRouter during the presentation.

The output directory is deliberately NOT under ``frontend/public/`` -- anything
there is served unauthenticated at a predictable URL, and these bundles contain
student grades and paraphrased professor comments.

Usage:
    # Real run (needs OPENROUTER_API_KEY and real model ids in model_config.py):
    uv run python -m GradusIQ_career.demo.build_demo_cache

    # Mock run (no API key, structurally-valid placeholder output so the
    # frontend wiring and export/cache layer can be built/tested offline):
    uv run python -m GradusIQ_career.demo.build_demo_cache --mock

    # Limit to specific students by slug:
    uv run python -m GradusIQ_career.demo.build_demo_cache --only priyaNair marcusWebb

    # Limit to specific features (e.g. to retry a timed-out feature without
    # re-running/overwriting the others' already-good cached entries):
    uv run python -m GradusIQ_career.demo.build_demo_cache --only ethanBrooks --feature GAP SHIFT
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STUDENTS_DIR = _REPO_ROOT / "data" / "students"
_OUTPUT_DIR = _REPO_ROOT / "data" / "demo_cache"


def _slug_from_filename(path: Path) -> str:
    """student_priyaNair.json -> priyaNair."""
    name = path.stem
    return name[len("student_"):] if name.startswith("student_") else name


class _MockClient:
    """Stand-in AI client that returns structurally-valid placeholder JSON.

    Inspects the outgoing prompt to decide which feature contract to satisfy,
    so orchestrator/parser/runner logic exercises end-to-end without a network
    call. Import of AIResponse is deferred so --mock works even before the
    real model ids are set.
    """

    def __init__(self) -> None:
        from GradusIQ_career.ai.types import AIResponse  # local import by design

        self._AIResponse = AIResponse

    def complete(self, *, messages: Sequence[Any], role: Any = None, **_: Any):
        blob = " ".join(
            str(m.get("content", "") if isinstance(m, Mapping) else getattr(m, "content", ""))
            for m in messages
        )
        payload = self._payload_for(blob)
        return self._AIResponse(
            text=json.dumps(payload), raw={"choices": []}, model="mock"
        )

    # Routing key. base.build_messages() appends the feature contract as JSON,
    # which carries an exact `"feature": "<NAME>"` line -- so this matches one
    # unambiguous token rather than scanning the blob for a bare feature name.
    #
    # It used to test `if "GAP" in blob.upper()` first, against the prompt,
    # contract and student context concatenated. Every prompt that happens to
    # contain the word "gap" therefore routed to the GAP payload: SHIFT has
    # said "The gap is articulation, not adoption" since v1.0, and FIT matches
    # too. --mock silently only ever exercised GAP.
    _PAYLOADS: Mapping[str, dict[str, Any]] = {
        "GAP": {
            "readiness_score": 62,
            "strengths": ["[MOCK] Strong analytical foundation from coursework"],
            "must_have_gaps": [
                {
                    "gap": "[MOCK] Industry-standard tooling",
                    "why_it_matters": "[MOCK] Carries a high O*NET importance score for this role.",
                    "how_to_close": "[MOCK] Complete one portfolio project this term.",
                }
            ],
            "nice_to_have_gaps": [
                {
                    "gap": "[MOCK] A relevant certification",
                    "why_it_helps": "[MOCK] Differentiates among otherwise similar candidates.",
                    "how_to_close": "[MOCK] Sit the exam before graduation.",
                }
            ],
            "recommended_next_steps": ["[MOCK] Complete one portfolio project this term"],
        },
        "FIT": {
            "role_matches": [
                {
                    "role": "[MOCK] Target Role",
                    "fit_level": "medium",
                    "rationale": "[MOCK] Aligns with declared major and interests.",
                    "supporting_signals": ["[MOCK] Relevant coursework"],
                    "missing_signals": ["[MOCK] Internship experience"],
                    "hiring_signal": {
                        "coverage": "unavailable",
                        "employers": [],
                        "posting_count": None,
                    },
                }
            ],
            "overall_fit_summary": "[MOCK] One realistic direction and one stretch.",
        },
        "SHIFT": {
            "role_evolution_summary": "[MOCK] Role family is shifting toward AI-augmented workflows.",
            "task_shifts": [
                {
                    "task": "[MOCK] Routine analysis",
                    "changing": "[MOCK] Increasingly automated by available tooling.",
                    "meaning": "[MOCK] Judgment about what the output means matters more.",
                }
            ],
            "durable_skills": [
                {
                    "task": "[MOCK] Stakeholder communication",
                    "reason": "[MOCK] Depends on context the tooling does not hold.",
                }
            ],
            "adjacent_paths": [
                {
                    "path": "[MOCK] Adjacent role",
                    "relevance": "[MOCK] Builds on the same coursework.",
                    "driver": "[MOCK] Growing demand for hybrid skills.",
                }
            ],
            "ai_fluency_guidance": ["[MOCK] Frame AI fluency as a productivity multiplier."],
        },
        "PROFESSOR_COMMENTS": {
            "themes": [
                {
                    "theme": "[MOCK] Consistent preparation",
                    "category": "strength",
                    "summary": "[MOCK] Feedback repeatedly notes thorough preparation.",
                    "supporting_references": [
                        {
                            "course_code": "[MOCK] BUSN 101",
                            "course_name": "[MOCK] Freshman Business Initiative",
                            "paraphrase": "[MOCK] Instructor noted strong preparation.",
                        }
                    ],
                }
            ],
            "overall_summary": "[MOCK] Broadly positive with one recurring concern.",
        },
    }

    @classmethod
    def _payload_for(cls, blob: str) -> dict[str, Any]:
        for feature, payload in cls._PAYLOADS.items():
            if f'"feature": "{feature}"' in blob:
                return payload
        return {"note": "[MOCK] unrecognized feature prompt"}


def _make_client(mock: bool):
    if mock:
        return _MockClient()
    from GradusIQ_career.ai import OpenRouterClient  # local import by design
    from GradusIQ_career.ai.openrouter_client import DEEPSEEK_R1_REASONING_TIMEOUT_SECONDS

    # Real calls run the DeepSeek R1 career/academic roles end to end, which
    # routinely take 100-200s+ -- match api.py's build_client() timeout
    # rather than the library's 30s default. Raises AIConfigError if
    # OPENROUTER_API_KEY is unset.
    return OpenRouterClient(timeout=DEEPSEEK_R1_REASONING_TIMEOUT_SECONDS)


def _load_existing_analysis(out_path: Path) -> Mapping[str, Any] | None:
    """Load a previously-cached analysis_<slug>.json, or None if unavailable.

    Returning None (missing file, unreadable, malformed JSON) causes the
    caller to fall back to writing the fresh result in full -- the same as
    today's behavior for a student's first-ever cache run.
    """
    if not out_path.exists():
        return None
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, Mapping) else None


def _merge_analysis(existing: Mapping[str, Any] | None, fresh: Mapping[str, Any]) -> dict[str, Any]:
    """Merge a fresh (possibly feature-subset) result into an existing cache file.

    Only the feature keys actually present in ``fresh["results"]`` (i.e. the
    features requested this run) replace the corresponding entries in
    ``existing["results"]``; every other feature's cached entry is carried
    over untouched. Top-level status/summary/errors are recomputed over the
    merged result set using the exact same functions run_career_analysis()
    uses for a single full run, so a merged file is indistinguishable in
    shape from one produced in one pass.

    If there's no existing file to merge into (first-ever run for this
    student), the fresh result is returned as-is -- unchanged from the
    pre-merge behavior.
    """
    if existing is None:
        return dict(fresh)

    from GradusIQ_career.features.orchestrator import (
        DEFAULT_CAREER_FEATURES,
        build_summary,
        collect_errors,
        summarize_status,
    )

    existing_results = existing.get("results", {})
    if not isinstance(existing_results, Mapping):
        existing_results = {}

    merged_results = dict(existing_results)
    merged_results.update(fresh.get("results", {}))

    # Canonical FIT/GAP/SHIFT ordering where possible, any other feature keys
    # (e.g. a future PROFESSOR_COMMENTS entry) appended after, in whatever
    # order they were encountered.
    ordered_features = [f for f in DEFAULT_CAREER_FEATURES if f in merged_results]
    ordered_features += [f for f in merged_results if f not in ordered_features]
    ordered_results = {f: merged_results[f] for f in ordered_features}

    status = summarize_status([result["status"] for result in ordered_results.values()])

    return {
        "analysis_type": fresh.get("analysis_type", "career"),
        "status": status,
        "student_id": fresh.get("student_id"),
        "features_requested": ordered_features,
        "results": ordered_results,
        "summary": build_summary(status, ordered_results),
        "errors": collect_errors(ordered_results),
    }


def build(only: Sequence[str] | None, mock: bool, feature: Sequence[str] | None) -> int:
    from GradusIQ_career.features.orchestrator import run_career_analysis

    if not _STUDENTS_DIR.exists():
        print(f"ERROR: students dir not found: {_STUDENTS_DIR}", file=sys.stderr)
        return 1

    client = _make_client(mock)
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    student_files = sorted(_STUDENTS_DIR.glob("student_*.json"))
    if only:
        wanted = set(only)
        student_files = [p for p in student_files if _slug_from_filename(p) in wanted]

    if not student_files:
        print("ERROR: no matching student files.", file=sys.stderr)
        return 1

    failures = 0
    for path in student_files:
        slug = _slug_from_filename(path)
        out_path = _OUTPUT_DIR / f"analysis_{slug}.json"
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
            fresh = run_career_analysis(profile, client, features=feature)
        except Exception as exc:  # keep going; one bad student shouldn't kill the cache
            failures += 1
            print(f"  [FAIL] {slug}: {exc}", file=sys.stderr)
            continue

        existing = _load_existing_analysis(out_path)
        result = _merge_analysis(existing, fresh)
        out_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        status = result.get("status", "?")
        print(f"  [{status:>15}] {slug} -> {out_path.relative_to(_REPO_ROOT)}")

    mode = "MOCK" if mock else "LIVE"
    print(f"\nDone ({mode}). {len(student_files) - failures}/{len(student_files)} students cached.")
    return 1 if failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build cached career-analysis JSON for the demo.")
    parser.add_argument("--mock", action="store_true",
                        help="Use placeholder output instead of calling OpenRouter.")
    parser.add_argument("--only", nargs="*", default=None,
                        help="Limit to these student slugs (e.g. priyaNair).")
    parser.add_argument("--feature", nargs="*", default=None,
                        help="Limit to these features (e.g. GAP SHIFT). Defaults to all three if omitted.")
    args = parser.parse_args(argv)
    return build(only=args.only, mock=args.mock, feature=args.feature)


if __name__ == "__main__":
    raise SystemExit(main())
