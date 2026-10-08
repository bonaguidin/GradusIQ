"""Strict structured-output contracts for AI features."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictOutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


NonEmptyString = Annotated[str, Field(min_length=1)]

_SIGNAL_TEXT_KEYS = ("signal", "text", "value", "description", "skill", "name", "detail")


def _coerce_signal_list(value: Any) -> Any:
    """Normalize a signal list's items to plain strings before type/length
    validation runs.

    Observed live: the model wrapped each supporting_signals entry in an
    object (e.g. {"signal": "..."}) instead of the bare string the schema
    (and the prompt's "short phrases") calls for, failing every item in the
    list with a contract-violation error and taking the whole FIT run down
    with it -- a formatting choice, not a content problem, so it should not
    fail the run. Pulls the first recognizable text field out of each dict
    item (falling back to its first string value), stringifies bare
    scalars, and drops anything left with nothing usable. Left for Field's
    own min_length/type checks to catch a genuinely empty or malformed
    result; this only reshapes what's already there.

    Not list input is returned unchanged -- that is a real type error for
    the field's own validator to report, not something to paper over here.
    """
    if not isinstance(value, list):
        return value
    coerced: list[str] = []
    for item in value:
        text: str | None
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            text = next(
                (item[key] for key in _SIGNAL_TEXT_KEYS if isinstance(item.get(key), str) and item[key].strip()),
                None,
            )
            if text is None:
                text = next((v for v in item.values() if isinstance(v, str) and v.strip()), None)
        elif isinstance(item, (int, float, bool)):
            text = str(item)
        else:
            text = None
        if text and text.strip():
            coerced.append(text.strip())
    return coerced


class FitHiringSignal(StrictOutputModel):
    coverage: Literal["available", "no_market_data", "unavailable"]
    employers: list[NonEmptyString] = Field(max_length=3)
    posting_count: int | None = Field(default=None, ge=0)


def _unavailable_hiring_signal() -> FitHiringSignal:
    return FitHiringSignal(coverage="unavailable", employers=[], posting_count=None)


class FitRoleMatch(StrictOutputModel):
    role: str = Field(min_length=1)
    fit_level: Literal["high", "medium", "low"]
    rationale: str = Field(min_length=1)
    # min_length=1: every role match has to name at least one concrete
    # signal, even a Developing fit (the prompt says so explicitly). Without
    # this, an empty list validated as a legal "no signals found" instead of
    # a prompt-following failure, and silently shipped a blank "Why this
    # fits" section to the student. missing_signals stays unconstrained --
    # a genuinely strong fit can have nothing missing, and forcing one would
    # make the model invent a gap that isn't real.
    supporting_signals: list[str] = Field(min_length=1)
    missing_signals: list[str]

    @field_validator("supporting_signals", "missing_signals", mode="before")
    @classmethod
    def _normalize_signals(cls, value: Any) -> Any:
        return _coerce_signal_list(value)

    # Optional at the schema boundary (older cached/demo results predate this
    # field) but always populated for live runs -- fit.py's run_canonical
    # overwrites this per role with server-derived ground truth after
    # validation, regardless of what the model returned. See
    # posting_provider.py / fit.py's _hiring_signal_by_role.
    hiring_signal: FitHiringSignal = Field(default_factory=_unavailable_hiring_signal)


class FitOutput(StrictOutputModel):
    role_matches: list[FitRoleMatch] = Field(min_length=1, max_length=5)
    overall_fit_summary: str = Field(min_length=1)


class GapStrength(StrictOutputModel):
    strength: str = Field(min_length=1)
    framing: str = Field(min_length=1)


class GapMustHave(StrictOutputModel):
    gap: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    how_to_close: str = Field(min_length=1)


class GapNiceToHave(StrictOutputModel):
    gap: str = Field(min_length=1)
    why_it_helps: str = Field(min_length=1)
    how_to_close: str = Field(min_length=1)


class GapOutput(StrictOutputModel):
    readiness_score: int = Field(ge=0, le=10, strict=True)
    # Both shapes exist in current valid demo bundles. The frontend historically
    # declared string[], while the prompt asks for a strength plus framing.
    strengths: list[NonEmptyString | GapStrength] = Field(max_length=4)
    must_have_gaps: list[GapMustHave]
    nice_to_have_gaps: list[GapNiceToHave]
    recommended_next_steps: list[NonEmptyString] = Field(max_length=5)


class ShiftTaskShift(StrictOutputModel):
    task: str = Field(min_length=1)
    changing: str = Field(min_length=1)
    meaning: str = Field(min_length=1)


class ShiftDurableSkill(StrictOutputModel):
    task: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ShiftAdjacentPath(StrictOutputModel):
    path: str = Field(min_length=1)
    relevance: str = Field(min_length=1)
    driver: str = Field(min_length=1)


class ShiftGuidance(StrictOutputModel):
    label: str = Field(min_length=1)
    text: str = Field(min_length=1)


class ShiftGuidanceSection(StrictOutputModel):
    section: str = Field(min_length=1)
    content: list[NonEmptyString] = Field(min_length=1)


class ShiftOutput(StrictOutputModel):
    role_evolution_summary: str = Field(min_length=1)
    task_shifts: list[ShiftTaskShift]
    durable_skills: list[ShiftDurableSkill]
    adjacent_paths: list[ShiftAdjacentPath]
    # Current caches contain both simple bullets and labeled guidance cards.
    ai_fluency_guidance: list[NonEmptyString | ShiftGuidance | ShiftGuidanceSection]


class ChatOutput(StrictOutputModel):
    """Validated natural-language chat completion."""

    content: NonEmptyString


def fit_output_is_valid(value: object) -> bool:
    """One semantic validation entry point shared by live and cached FIT."""
    try:
        FitOutput.model_validate(value)
    except (TypeError, ValueError):
        return False
    return True


OUTPUT_MODEL_BY_FEATURE: dict[str, type[StrictOutputModel]] = {
    "FIT": FitOutput,
    "GAP": GapOutput,
    "SHIFT": ShiftOutput,
}


def feature_output_is_valid(feature: str, value: object) -> bool:
    """Shared semantic validation for live and cached typed features."""
    model = OUTPUT_MODEL_BY_FEATURE.get(feature)
    if model is None:
        return False
    try:
        model.model_validate(value)
    except (TypeError, ValueError):
        return False
    return True
