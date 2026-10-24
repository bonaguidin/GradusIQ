"""Tell whether a saved GAP/FIT/SHIFT result still matches the student's profile.

student_analysis_cache is keyed on the target-role set, and a skills edit
deletes GAP/FIT, but nothing else invalidates it: a new transcript, a
confirmed resume or a changed major left the old result on screen as if it
were current. Re-running on every edit would be the wrong fix -- GAP takes
100-200 s and costs a model call -- so instead each saved result carries a
fingerprint of the student inputs it was computed from, and a read compares it
with the inputs as they are now. A mismatch is reported as `profile_changed`;
the student decides whether to re-run.

The fields per feature mirror what each runner's build_student_context reads
from the profile (features/gap.py, fit.py, shift.py). Their market and
role-research grounding is deliberately not fingerprinted: it changes on its
own schedule, not because the student edited anything.
"""

import hashlib
import json
from typing import Any, Mapping


FINGERPRINT_KEY = "input_fingerprint"

_STUDENT_FIELDS = {
    "GAP": ("major_current", "major_intended", "classification", "expected_graduation"),
    "FIT": ("major_current", "major_intended", "classification"),
    "SHIFT": ("major_current", "major_intended", "classification"),
}

_CAREER_FIELDS = {
    "GAP": ("target_roles", "skills_self_reported", "certifications", "work_experience", "projects"),
    "FIT": (
        "target_roles", "interests", "career_goals", "geographic_preference",
        "skills_self_reported", "work_experience", "projects",
    ),
    "SHIFT": ("target_roles", "interests", "skills_self_reported", "career_goals", "ai_anxiety_level"),
}

# Only GAP reads courses. Row ids change when a transcript is re-imported even
# if nothing a student would call a change did, so only the facts are kept.
_COURSE_FIELDS = ("course_code", "title", "credit_hours", "letter_grade", "status", "credit_type")


def input_fingerprint(feature: str, profile: Mapping[str, Any]) -> str | None:
    """sha256 of the inputs `feature` reads from a legacy-shaped profile."""
    feature = feature.upper()
    if feature not in _STUDENT_FIELDS:
        return None
    student = profile.get("student") or {}
    career = profile.get("career") or {}
    inputs: dict[str, Any] = {
        "student": {key: student.get(key) for key in _STUDENT_FIELDS[feature]},
        "career": {key: career.get(key) for key in _CAREER_FIELDS[feature]},
    }
    if feature == "GAP":
        courses = [
            {key: course.get(key) for key in _COURSE_FIELDS}
            for course in profile.get("courses") or []
        ]
        inputs["courses"] = sorted(courses, key=lambda c: json.dumps(c, sort_keys=True, default=str))
    encoded = json.dumps(inputs, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stamp(result: Mapping[str, Any], feature: str, profile: Mapping[str, Any]) -> dict:
    """A copy of `result` carrying the fingerprint of the inputs it was run on."""
    return {**result, FINGERPRINT_KEY: input_fingerprint(feature, profile)}


def profile_changed(result: Mapping[str, Any], feature: str, profile: Mapping[str, Any]) -> bool | None:
    """True/False against the current profile; None for a result saved before
    fingerprints existed, where there is nothing to compare."""
    stored = result.get(FINGERPRINT_KEY)
    if not stored:
        return None
    return stored != input_fingerprint(feature, profile)


def for_client(result: Mapping[str, Any], feature: str, profile: Mapping[str, Any]) -> dict:
    """The saved result as the API returns it: fingerprint swapped for the verdict."""
    changed = profile_changed(result, feature, profile)
    served = {key: value for key, value in result.items() if key != FINGERPRINT_KEY}
    if changed is not None:
        served["profile_changed"] = changed
    return served
