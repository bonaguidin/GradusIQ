"""`decomposable_categories` on the profile-detail payload.

The field is a thin projection of weighting._decomposition_children -- the
single definition of the gate. These tests drive api._syllabus_profile_detail_response
directly (it is the shared builder behind the GET detail route and the
corrections / confirm / grade-state routes) with a hand-built `assembled`
dict, so they exercise the serialization + gate wiring without a DB or HTTP.
"""

from GradusIQ_career.api import _syllabus_profile_detail_response
from GradusIQ_career.syllabus.models import Assessment, GradeCategory, GradeModel, GradingMethod


def _assembled(*, confirmed: GradeModel | None, extracted: GradeModel | None = None) -> dict:
    return {
        "profile": {
            "id": "p1",
            "institution": None,
            "course_code": "CSCE 222",
            "term": None,
            "section": None,
            "review_state": "confirmed",
        },
        "current_revision": None,
        "reconciliation": None,
        "confirmed_grade_model": confirmed,
        "extracted_grade_model": extracted if extracted is not None else confirmed,
        "calculator_ready": confirmed is not None,
        "grade_state": None,
        "grade_state_revision": None,
    }


def _decomposable_model() -> GradeModel:
    """CSCE 222's real shape: 'midterm exam' (30, count 2) decomposes into
    'midterm I' + 'midterm II' at 15 each; single-child 'final exam' too.
    """
    return GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Homework assignment", weight=35),
            GradeCategory(name="midterm exam", weight=30, count=2),
            GradeCategory(name="final exam", weight=35, count=1),
        ],
        assessments=[
            Assessment(name="midterm I", category="midterm exam", weight=15, date="Sept. 24"),
            Assessment(name="midterm II", category="midterm exam", weight=15, date="Oct. 29"),
            Assessment(name="final exam", category="final exam", weight=35),
        ],
    )


def _midterms_model(
    *,
    child_weights=(15.0, 15.0),
    category_weight=30.0,
    count=2,
    child_names=("Midterm 1", "Midterm 2"),
    extra_assessments=(),
) -> GradeModel:
    w1, w2 = child_weights
    n1, n2 = child_names
    return GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Homework", weight=70),
            GradeCategory(name="Midterms", weight=category_weight, count=count),
        ],
        assessments=[
            Assessment(name=n1, category="Midterms", weight=w1),
            Assessment(name=n2, category="Midterms", weight=w2),
            *extra_assessments,
        ],
    )


def _flag(assembled: dict) -> list[str]:
    return _syllabus_profile_detail_response(assembled)["decomposable_categories"]


# --- happy path ---------------------------------------------------------------


def test_decomposable_model_returns_its_category_names():
    assert _flag(_assembled(confirmed=_decomposable_model())) == ["midterm exam", "final exam"]


def test_single_decomposable_category_is_listed():
    assert _flag(_assembled(confirmed=_midterms_model())) == ["Midterms"]


# --- each gate condition failing independently -> empty list ------------------


def test_gate_condition_1_no_child_assessments_returns_empty():
    model = GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Homework", weight=70),
            GradeCategory(name="Midterms", weight=30, count=2),
        ],
    )
    assert _flag(_assembled(confirmed=model)) == []


def test_gate_condition_2_child_missing_weight_returns_empty():
    assert _flag(_assembled(confirmed=_midterms_model(child_weights=(15.0, None)))) == []


def test_gate_condition_3_child_weights_do_not_sum_to_parent_returns_empty():
    assert _flag(_assembled(confirmed=_midterms_model(child_weights=(15.0, 10.0)))) == []


def test_gate_condition_4_stated_count_mismatch_returns_empty():
    assert _flag(_assembled(confirmed=_midterms_model(count=3))) == []


def test_gate_condition_5_name_collision_returns_empty():
    # a standalone assessment normalizing to the same name as a child
    collision = _midterms_model(
        extra_assessments=(Assessment(name="midterm 1", weight=5),),  # normalizes onto "Midterm 1"
    )
    assert _flag(_assembled(confirmed=collision)) == []


def test_tolerance_boundary_within_0_01_is_still_listed():
    assert _flag(_assembled(confirmed=_midterms_model(child_weights=(15.0, 15.005)))) == ["Midterms"]


# --- no confirmed model -----------------------------------------------------


def test_no_confirmed_model_returns_empty_even_if_extracted_is_decomposable():
    assembled = _assembled(confirmed=None, extracted=_decomposable_model())
    assert _flag(assembled) == []


def test_no_model_at_all_returns_empty():
    assert _flag(_assembled(confirmed=None, extracted=None)) == []
