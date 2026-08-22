#!/usr/bin/env python3
"""
Validates all 5 student JSON files: parses valid JSON, checks the
unified student profile contract, and verifies expected record counts.
"""

import json
import sys
import os

STUDENTS_DIR = os.path.dirname(os.path.abspath(__file__))

REQUIRED_KEYS = {
    "student",
    "courses",
    "enrollments",
    "assignments",
    "submissions",
    "career",
    "profile_completeness",
    "examTopicTags",
}

REQUIRED_STUDENT_KEYS = {
    "id",
    "name",
    "classification",
    "institution",
    "gpa_current",
}

REQUIRED_CAREER_KEYS = {
    "target_roles",
    "interests",
    "career_goals",
    "geographic_preference",
    "ai_anxiety_level",
    "skills_self_reported",
    "certifications",
    "work_experience",
    "projects",
}

REQUIRED_SKILL_KEYS = {"technical", "soft", "ai_exposure"}
REQUIRED_COMPLETENESS_KEYS = {"academic", "career", "overall"}
REQUIRED_FEATURE_KEYS = {"FIT", "GAP", "SHIFT"}

# Demo-critical inputs the analyzers actually consume (previously unchecked).
REQUIRED_EXAM_TAG_KEYS = {"question_id", "topic", "score", "max_score"}
MIN_SUBMISSION_COMMENTS = 3

EXPECTED = {
    "student_jordanReyes.json":  {"courses": 5, "enrollments": 5, "assignments": 12, "submissions": 11},
    "student_priyaNair.json":    {"courses": 6, "enrollments": 6, "assignments": 19, "submissions": 14},
    # Courses/enrollments updated to 8 (from 6) for the SMU CS-BS conversion
    # (planning-docs/degree-planner-spec.md §8.4); assignments/submissions
    # deliberately untouched -- still describe the old TAMU profile pending
    # new SMU-specific content, per this file's own _notes.
    "student_ethanBrooks.json":  {"courses": 8, "enrollments": 8, "assignments": 24, "submissions": 17},
    "student_marcusWebb.json":   {"courses": 4, "enrollments": 4, "assignments": 9,  "submissions": 9},
    "student_sofiaRamirez.json": {"courses": 5, "enrollments": 5, "assignments": 17, "submissions": 12},
}

errors = []


def is_non_empty_string(value):
    return isinstance(value, str) and bool(value.strip())


def validate_string_list(value, field_name, issues, allow_empty=False):
    if not isinstance(value, list):
        issues.append(f"{field_name}: expected list")
        return
    if not allow_empty and not value:
        issues.append(f"{field_name}: expected non-empty list")
        return
    bad_items = [item for item in value if not is_non_empty_string(item)]
    if bad_items:
        issues.append(f"{field_name}: all items must be non-empty strings")


def validate_resume_items(items, required_fields, field_name, issues, allow_empty=False):
    if not isinstance(items, list):
        issues.append(f"{field_name}: expected list")
        return
    if not allow_empty and not items:
        issues.append(f"{field_name}: expected non-empty list")
        return
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            issues.append(f"{field_name}[{index}]: expected object")
            continue
        missing = required_fields - set(item.keys())
        if missing:
            issues.append(f"{field_name}[{index}]: missing keys {sorted(missing)}")


def validate_unified_profile(data, issues):
    student = data.get("student")
    if not isinstance(student, dict):
        issues.append("student: expected object")
    else:
        missing_student = REQUIRED_STUDENT_KEYS - set(student.keys())
        if missing_student:
            issues.append(f"student: missing keys {sorted(missing_student)}")
        if not isinstance(student.get("id"), int):
            issues.append("student.id: expected integer")
        for key in ["name", "classification", "institution"]:
            if not is_non_empty_string(student.get(key)):
                issues.append(f"student.{key}: expected non-empty string")
        # Accept either legacy `major` or the split `major_current` + `major_intended`
        has_major = is_non_empty_string(student.get("major"))
        has_split = (is_non_empty_string(student.get("major_current")) and
                     is_non_empty_string(student.get("major_intended")))
        if not has_major and not has_split:
            issues.append("student: expected non-empty major or major_current + major_intended")
        if not isinstance(student.get("gpa_current"), (int, float)):
            issues.append("student.gpa_current: expected number")

    career = data.get("career")
    if not isinstance(career, dict):
        issues.append("career: expected object")
        return

    missing_career = REQUIRED_CAREER_KEYS - set(career.keys())
    if missing_career:
        issues.append(f"career: missing keys {sorted(missing_career)}")

    validate_string_list(career.get("target_roles"), "career.target_roles", issues)
    validate_string_list(career.get("interests"), "career.interests", issues)
    for key in ["career_goals", "geographic_preference", "ai_anxiety_level"]:
        if not is_non_empty_string(career.get(key)):
            issues.append(f"career.{key}: expected non-empty string")

    skills = career.get("skills_self_reported")
    if not isinstance(skills, dict):
        issues.append("career.skills_self_reported: expected object")
    else:
        missing_skills = REQUIRED_SKILL_KEYS - set(skills.keys())
        if missing_skills:
            issues.append(f"career.skills_self_reported: missing keys {sorted(missing_skills)}")
        validate_string_list(skills.get("technical"), "career.skills_self_reported.technical", issues)
        validate_string_list(skills.get("soft"), "career.skills_self_reported.soft", issues)
        if not is_non_empty_string(skills.get("ai_exposure")):
            issues.append("career.skills_self_reported.ai_exposure: expected non-empty string")

    validate_resume_items(
        career.get("work_experience"),
        {"employer", "role", "duration", "location", "description", "skills_gained"},
        "career.work_experience",
        issues,
    )
    validate_resume_items(
        career.get("projects"),
        {"name", "timeframe", "description", "tools"},
        "career.projects",
        issues,
    )
    validate_resume_items(
        career.get("certifications"),
        {"name", "issuer", "status"},
        "career.certifications",
        issues,
        allow_empty=True,
    )

    completeness = data.get("profile_completeness")
    if not isinstance(completeness, dict):
        issues.append("profile_completeness: expected object")
    else:
        missing_completeness = REQUIRED_COMPLETENESS_KEYS - set(completeness.keys())
        if missing_completeness:
            issues.append(f"profile_completeness: missing keys {sorted(missing_completeness)}")
        for key in REQUIRED_COMPLETENESS_KEYS:
            value = completeness.get(key)
            if not isinstance(value, (int, float)) or value < 0 or value > 1:
                issues.append(f"profile_completeness.{key}: expected number from 0 to 1")
        by_feature = completeness.get("by_feature")
        if not isinstance(by_feature, dict):
            issues.append("profile_completeness.by_feature: expected object")
        else:
            missing_features = REQUIRED_FEATURE_KEYS - set(by_feature.keys())
            if missing_features:
                issues.append(f"profile_completeness.by_feature: missing keys {sorted(missing_features)}")
            for feature in REQUIRED_FEATURE_KEYS:
                gate = by_feature.get(feature)
                if not isinstance(gate, dict):
                    issues.append(f"profile_completeness.by_feature.{feature}: expected object")
                    continue
                if not isinstance(gate.get("ready"), bool):
                    issues.append(f"profile_completeness.by_feature.{feature}.ready: expected boolean")
                required = gate.get("required")
                if not isinstance(required, dict):
                    issues.append(f"profile_completeness.by_feature.{feature}.required: expected object")
                else:
                    bad_required = [
                        key for key, value in required.items()
                        if not is_non_empty_string(key) or not isinstance(value, bool)
                    ]
                    if bad_required:
                        issues.append(
                            f"profile_completeness.by_feature.{feature}.required: expected string keys and boolean values"
                        )

def validate_demo_inputs(data, issues):
    """Guard the exact inputs the demo features consume: professor comments
    (academic.py) and exam topic tags (GAP/academic layer). These were
    previously unchecked, so the dataset could silently regress on them."""
    submissions = data.get("submissions")
    if not isinstance(submissions, list):
        issues.append("submissions: expected list")
    else:
        comment_count = 0
        for sub in submissions:
            if not isinstance(sub, dict):
                continue
            sc = sub.get("submission_comments", [])
            if isinstance(sc, list):
                comment_count += len(sc)
        if comment_count < MIN_SUBMISSION_COMMENTS:
            issues.append(
                f"submission_comments: expected >= {MIN_SUBMISSION_COMMENTS} total across "
                f"submissions, got {comment_count}"
            )

    exam_tags = data.get("examTopicTags")
    if not isinstance(exam_tags, dict):
        issues.append("examTopicTags: expected object")
    elif not exam_tags:
        issues.append("examTopicTags: expected non-empty object (at least one tagged exam)")
    else:
        for assignment_id, tags in exam_tags.items():
            if not isinstance(tags, list) or not tags:
                issues.append(f"examTopicTags[{assignment_id}]: expected non-empty list")
                continue
            for index, tag in enumerate(tags):
                if not isinstance(tag, dict):
                    issues.append(f"examTopicTags[{assignment_id}][{index}]: expected object")
                    continue
                missing = REQUIRED_EXAM_TAG_KEYS - set(tag.keys())
                if missing:
                    issues.append(
                        f"examTopicTags[{assignment_id}][{index}]: missing keys {sorted(missing)}"
                    )


print(f"{'File':<30} {'Keys':>5}  {'Courses':>7}  {'Enroll':>6}  {'Assign':>6}  {'Subs':>5}  Status")
print("-" * 80)

for fname, expected_counts in sorted(EXPECTED.items()):
    path = os.path.join(STUDENTS_DIR, fname)

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"{fname:<30}  FILE NOT FOUND")
        errors.append(f"{fname}: file not found")
        continue
    except json.JSONDecodeError as e:
        print(f"{fname:<30}  INVALID JSON: {e}")
        errors.append(f"{fname}: invalid JSON")
        continue

    missing_keys = REQUIRED_KEYS - set(data.keys())
    has_notes = "_notes" in data

    actual = {
        "courses":     len(data.get("courses", [])),
        "enrollments": len(data.get("enrollments", [])),
        "assignments": len(data.get("assignments", [])),
        "submissions": len(data.get("submissions", [])),
    }

    count_ok = all(actual[k] == expected_counts[k] for k in expected_counts)
    keys_ok = len(missing_keys) == 0

    issues = []
    if missing_keys:
        issues.append(f"missing keys: {missing_keys}")
    for k, v in expected_counts.items():
        if actual[k] != v:
            issues.append(f"{k}: expected {v} got {actual[k]}")
    validate_unified_profile(data, issues)
    validate_demo_inputs(data, issues)

    status = "OK" + (" +_notes" if has_notes else "") if not issues else "FAIL: " + "; ".join(issues)

    print(
        f"{fname:<30} {len(REQUIRED_KEYS - missing_keys):>5}  "
        f"{actual['courses']:>7}  {actual['enrollments']:>6}  "
        f"{actual['assignments']:>6}  {actual['submissions']:>5}  {status}"
    )
    if issues:
        errors.extend([f"{fname}: {i}" for i in issues])

print("-" * 80)
print()
if errors:
    print(f"RESULT: FAILED ({len(errors)} error(s))")
    for e in errors:
        print(f"  {e}")
    sys.exit(1)
else:
    print("RESULT: All 5 student JSON files valid.")
