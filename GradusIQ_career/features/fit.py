"""FIT career feature runner."""

import json
from typing import Any, Mapping

from pydantic import ValidationError

from GradusIQ_career.ai.context import AgentContext, GroundingMetadata
from GradusIQ_career.ai.contracts import FitOutput
from GradusIQ_career.ai.runtime import AIRuntime
from GradusIQ_career.student_intelligence_profile import StudentIntelligenceProfile

from .base import CareerFeatureRunner, FeatureResult, load_prompt_template
from .market_data import get_market_requirements, get_shift_signals, is_role_supported
from .posting_provider import DEFAULT_LIMIT_PER_ROLE, get_role_posting_grounding

from GradusIQ_career.supabase_client import build_service_client

# Sentinel value used in the data for "not switching majors" (Decision (b) —
# it stays in the data as-is; FIT resolves around it here in feature logic).
_NO_INTENDED_MAJOR = "N/A"


def _resolve_major(student: Mapping[str, Any]) -> tuple[str, str]:
    """Resolve the major FIT should reason about without mutating stored data.

    Returns (effective_major, major_status). Use major_intended when it is a
    real major; fall back to major_current when major_intended is "N/A", empty,
    or missing. major_status is "declare" when there is no current major to
    switch FROM (an intended major here is a first-time declaration, never a
    switch, regardless of any switching-major checkbox state upstream);
    "switching" when a distinct intended major is declared against a real
    current major; else "staying"."""
    current = (student.get("major_current") or student.get("major") or "").strip()
    intended = (student.get("major_intended") or "").strip()
    has_intended = bool(intended) and intended.upper() != _NO_INTENDED_MAJOR

    if not current:
        return (intended, "declare") if has_intended else (current, "staying")

    if has_intended and intended != current:
        return intended, "switching"
    return current, "staying"


class FitRunner(CareerFeatureRunner):
    feature = "FIT"
    prompt_filename = "gradus_iq_prompt_FIT.md"
    prompt_name = "fit"
    prompt_version = "1.0"
    required_paths = (
        "student.major_intended",
        "career.target_roles",
        "career.interests",
        "career.skills_self_reported",
    )
    output_contract: Mapping[str, Any] = {
        "role_matches": [
            {
                "role": "string",
                "fit_level": "high|medium|low",
                "rationale": "string",
                "supporting_signals": [],
                "missing_signals": [],
            }
        ],
        "overall_fit_summary": "string",
    }

    def __init__(
        self,
        *args,
        runtime_factory=AIRuntime,
        posting_client_factory=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.runtime_factory = runtime_factory
        # None, not a bound default, so a module-level monkeypatch of
        # build_service_client (see tests/conftest.py) still takes effect --
        # the lookup below happens per call, not once at class-definition time.
        self.posting_client_factory = posting_client_factory
        self.last_trace: dict[str, Any] | None = None

    def additional_missing_fields(self, student_profile: Mapping[str, Any]) -> list[str]:
        """FIT has no research-agent fallback (see build_student_context's
        "Deliberately no research agent" note) -- an unmatched target role
        goes straight into the prompt as an ungrounded block, and FIT still
        produces a confident-looking fit judgement from pure model recall.
        Gated here rather than left to silently degrade: required_paths
        already guarantees career.target_roles is non-empty by the time this
        runs, so an empty result means every listed role is unsupported, not
        that none were chosen (that's the required_paths gate's job).
        """
        target_roles = student_profile.get("career", {}).get("target_roles") or []
        if target_roles and not any(is_role_supported(role) for role in target_roles):
            return ["career.target_roles"]
        return []

    def validate_data(self, data, student_profile):
        """Use the same semantic contract as authenticated and cached FIT."""
        try:
            FitOutput.model_validate(data)
        except ValidationError as exc:
            return [
                "FIT output contract violation at "
                + ".".join(str(part) for part in error["loc"])
                for error in exc.errors(include_url=False)
            ]
        return []

    def run_canonical(
        self,
        canonical_profile: StudentIntelligenceProfile,
        legacy_profile: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Run authenticated FIT from canonical input through ``AIRuntime``.

        ``legacy_profile`` is an in-memory compatibility projection used only
        by the established FIT prompt builder. The AgentContext itself remains
        canonical and retains confirmation/provenance boundaries.
        """
        missing = self._missing_result(legacy_profile)
        if missing is not None:
            return missing

        try:
            prompt_template = load_prompt_template(self.prompt_path)
            fit_context = self.build_student_context(legacy_profile)
        except (OSError, ValueError) as exc:
            return FeatureResult(
                feature=self.feature,
                status="failed",
                summary="FIT analysis failed.",
                data={},
                errors=[str(exc)],
            ).to_dict()

        context = AgentContext(
            feature=self.feature,
            canonical_profile=canonical_profile,
            model_role=self.role,
            prompt_name=self.prompt_name,
            prompt_version=self.prompt_version,
            grounding=GroundingMetadata(
                source_types=("student_confirmed", "onet_static"),
                trust_level="trusted_reference",
                attributes={"tool_loop": False},
            ),
        )
        messages = self._messages_for_context(prompt_template, fit_context)
        result = self.runtime_factory(self.client).invoke(
            context=context,
            messages=messages,
            output_model=FitOutput,
        )
        self.last_trace = result.trace.to_dict()
        if result.output is None:
            return FeatureResult(
                feature=self.feature,
                status="failed",
                summary="FIT analysis failed.",
                data={},
                errors=result.errors,
            ).to_dict()
        data = result.output.model_dump(mode="json")
        return FeatureResult(
            feature=self.feature,
            status="success",
            summary=result.summary or self.default_summary(data),
            data=data,
            errors=[],
        ).to_dict()

    def _missing_result(self, profile: Mapping[str, Any]) -> dict[str, Any] | None:
        # Reuse the established gate without making a provider call. A tiny
        # sentinel client makes this branch explicit and keeps the skip shape
        # authored by CareerFeatureRunner in one place.
        from .base import find_missing_fields

        missing = find_missing_fields(
            profile, self.required_paths
        ) or self.additional_missing_fields(profile)
        if not missing:
            return None
        return super().run(profile)

    def _messages_for_context(
        self, prompt_template: str, student_context: Mapping[str, Any]
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "You are Gradus IQ. Return valid JSON only. Do not wrap the response "
                    "in Markdown. Follow the requested output contract exactly."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{prompt_template}\n\n"
                    "Return JSON only using this feature result contract:\n"
                    f"{json.dumps(self.feature_contract(), indent=2)}\n\n"
                    "Relevant student profile context:\n"
                    f"{json.dumps(student_context, indent=2, sort_keys=True)}"
                ),
            },
        ]

    def build_student_context(self, student_profile):
        student = student_profile.get("student", {})
        career = student_profile.get("career", {})
        effective_major, major_status = _resolve_major(student)
        target_roles = career.get("target_roles", [])
        # FIT had no market data at all, so every fit judgement was the model's
        # own recall presented as analysis -- and its prompt asked for a "DFW
        # market signal" it was never given, so it invented employers.
        #
        # It reuses GAP's and SHIFT's providers rather than growing its own:
        # requirements + provenance answer "what does this role demand", and
        # core_tasks answer "what does this job actually involve day to day",
        # which is what matching interests to roles needs.
        #
        # Deliberately no research agent. Matching a student to roles doesn't
        # justify a tool loop, and an unrated occupation still has tasks and
        # tooling to match against -- so FIT stays a single fast call.
        #
        # role_postings is a separate context key, not folded into
        # market_requirements: O*NET requirements are static, national, and
        # always present; postings are live, role-scoped, and may be absent
        # (no_market_data) or entirely unfetchable (status: "unavailable").
        # Collapsing those into one block would erase that distinction from
        # the prompt.
        market = get_market_requirements(target_roles)
        signals = self._role_context_for(target_roles)
        postings = self._get_role_postings(target_roles)
        return {
            "market_requirements": market,
            "role_context": signals,
            "role_postings": postings,
            "effective_major": effective_major,
            "major_status": major_status,
            "major_current": student.get("major_current") or student.get("major"),
            "major_intended": student.get("major_intended") or student.get("major"),
            "classification": student.get("classification"),
            "target_roles": career.get("target_roles", []),
            "interests": career.get("interests", []),
            "career_goals": career.get("career_goals", ""),
            "geographic_preference": career.get("geographic_preference", ""),
            "skills_self_reported": career.get("skills_self_reported", {}),
            "work_experience": career.get("work_experience", []),
            "projects": career.get("projects", []),
        }

    def _role_context_for(self, target_roles: list[str]) -> dict[str, Any]:
        """FIT's copy of get_shift_signals, stripped of fields it doesn't earn.

        ``hot_software`` is byte-for-byte identical to
        ``market_requirements.by_role[role].hot_software`` -- the prompt
        already instructs on market_requirements for "what this occupation
        demands", so carrying it twice is pure duplication. ``related`` is
        real O*NET data, but FIT's output contract has no bullet that uses it
        (SHIFT's does, via shift_signals.related -- adjacent-role surfacing in
        FIT is a real feature, just not one scoped yet). Stripped here, on
        FIT's own freshly-built dict, so SHIFT's separate get_shift_signals
        call is untouched.
        """
        signals = get_shift_signals(target_roles)
        for entry in signals.get("by_role", {}).values():
            if isinstance(entry, dict):
                entry.pop("hot_software", None)
                entry.pop("related", None)
        return signals

    def _get_role_postings(self, target_roles: list[str]) -> dict[str, Any]:
        """Fetch live posting grounding, degrading to an explicit marker on failure.

        A Supabase outage or config error must not fail FIT, and it must not
        look like ``coverage: "no_market_data"`` -- that means "queried, found
        nothing"; this means "never queried". The prompt has to be able to
        tell the two apart.
        """
        try:
            factory = self.posting_client_factory or build_service_client
            client = factory()
            return get_role_posting_grounding(
                client, target_roles, limit_per_role=DEFAULT_LIMIT_PER_ROLE
            )
        except Exception as exc:  # noqa: BLE001 -- external dependency boundary
            return {"status": "unavailable", "reason": str(exc)}

    def default_summary(self, data):
        return data.get("overall_fit_summary", "FIT analysis completed.")
