"""The single definition of "effective course-level weighted component,"
shared by trust validation (validation.py/reconciliation.py) and the
calculator (calculator/engine.py) so the two layers can never disagree
about what counts toward a weighted course's 100%.

THE RULE
--------
A course-level weighted component is:

    A. every GradeCategory with a known weight, and
    B. every standalone Assessment (Assessment.category is None) with a
       known weight of its own.

An Assessment whose `.category` names a category is EXCLUDED from the
course-level total, regardless of whether that name resolves to a real
GradeCategory in this model. Its own `.weight` is never added on top of
its category's weight, and its category's weight is never reduced to make
room for it. This is a genuine schema ambiguity, not a solved case: the
Phase 1 schema has no field establishing whether such an assessment's
weight is a fraction of its category's weight, an independent course
percentage that happens to share a label, or something else entirely (see
Phase 6's calculator/engine.py module docstring, "WHY CATEGORIES AND
STANDALONE ASSESSMENTS, NEVER AGGREGATED"). Counting it either way would be
a guess; excluding it and surfacing that exclusion (both layers do, via
`categories_without_weight`/`category_scoped_weighted_assessments` here and
their corresponding warnings in validate_category_weights/engine.py) is the
conservative, deterministic choice both layers already made independently
before this module existed to keep them in sync.

THE ONE EXCEPTION: A PROVABLY DECOMPOSABLE CATEGORY
--------------------------------------------------
The ambiguity above disappears when the model itself pins down the
composition. A GradeCategory is "decomposable" -- and its assessments may
then be scored individually, each becoming its own course-level component
in place of the parent -- only when ALL of these hold (see
`_decomposition_children`):

    1. at least one Assessment names the category in `.category`;
    2. every such Assessment has a non-null `.weight`;
    3. those weights sum to the category's own `.weight`, within the same
       0.01 tolerance validate_category_weights uses;
    4. if the category's `.count` is stated, it equals the number of such
       Assessments.

Plus a structural guard: none of those child names may collide, after
normalization, with each other, with another category, or with a
non-child assessment -- a collision puts the child's identity (and so the
course-total arithmetic once it is its own component) back into exactly
the ambiguous territory conditions 1-4 exist to keep out.

Because condition 3 makes the children's weights sum to the parent's,
swapping the parent component for its children leaves `total_weight` and
every downstream sum unchanged -- so `total_weight` still counts the
parent weight here, and the two layers still agree. When ANY condition
fails, behavior is exactly as before: the parent category is the only
component and its assessments stay informational.

This module only reports whether a category COULD be decomposed
(`decomposable_categories` / `decomposed_assessments`). Whether it
actually is, for a given calculation, is the calculator's call and
depends on the student's input -- see engine._build_weighted_components:
a decomposable category stays a single parent component until the student
scores at least one of its child assessments.
"""

from dataclasses import dataclass

from GradusIQ_career.syllabus.models import Assessment, GradeCategory, GradeModel

_DECOMPOSITION_WEIGHT_TOLERANCE = 0.01  # same tolerance validate_category_weights uses


def _normalize_name(name: str) -> str:
    return " ".join(name.lower().split())


@dataclass(frozen=True)
class EffectiveCourseWeights:
    weighted_categories: tuple[GradeCategory, ...]
    standalone_weighted_assessments: tuple[Assessment, ...]
    categories_without_weight: tuple[GradeCategory, ...]
    category_scoped_weighted_assessments: tuple[Assessment, ...]
    # Categories that pass every decomposability condition (see
    # `_decomposition_children`). Still counted in `weighted_categories` and
    # `total_weight` -- condition 3 keeps the arithmetic identical -- but the
    # calculator emits one component per child instead of one for the parent.
    decomposable_categories: tuple[GradeCategory, ...] = ()
    # The child assessments of every decomposable category, flattened. These
    # are a subset of `category_scoped_weighted_assessments`; the calculator
    # treats them like standalone weighted assessments.
    decomposed_assessments: tuple[Assessment, ...] = ()

    @property
    def total_weight(self) -> float:
        return sum(c.weight for c in self.weighted_categories) + sum(
            a.weight for a in self.standalone_weighted_assessments
        )

    @property
    def has_any_component(self) -> bool:
        return bool(self.weighted_categories or self.standalone_weighted_assessments)


def _decomposition_children(
    grade_model: GradeModel, category: GradeCategory
) -> tuple[Assessment, ...] | None:
    """The child assessments that make `category` provably decomposable into
    per-assessment components, or None when it is not. See this module's
    docstring, "THE ONE EXCEPTION", for the four conditions and the
    structural collision guard enforced here.

    Pure and deterministic: returns the children in `grade_model.assessments`
    order so downstream component order is stable.
    """
    if category.weight is None:
        return None

    category_key = _normalize_name(category.name)
    children = tuple(
        a
        for a in grade_model.assessments
        if a.category is not None and _normalize_name(a.category) == category_key
    )
    if not children:
        return None  # condition 1: at least one child
    if any(a.weight is None for a in children):
        return None  # condition 2: every child carries its own weight
    if abs(sum(a.weight for a in children) - category.weight) > _DECOMPOSITION_WEIGHT_TOLERANCE:
        return None  # condition 3: children's weights sum to the parent's
    if category.count is not None and category.count != len(children):
        return None  # condition 4: stated count matches the children found

    # Structural guard: every child must have an unambiguous identity once it
    # becomes its own component -- no normalized-name collision with another
    # child, with any other category, or with a non-child assessment.
    child_keys = [_normalize_name(a.name) for a in children]
    if len(set(child_keys)) != len(child_keys):
        return None
    child_ids = {id(a) for a in children}
    other_category_keys = {
        _normalize_name(c.name) for c in grade_model.categories if _normalize_name(c.name) != category_key
    }
    non_child_assessment_keys = {
        _normalize_name(a.name) for a in grade_model.assessments if id(a) not in child_ids
    }
    for key in child_keys:
        if key in other_category_keys or key in non_child_assessment_keys:
            return None

    return children


def get_effective_course_weights(grade_model: GradeModel) -> EffectiveCourseWeights:
    """Classify every GradeCategory/Assessment into the effective
    course-level weighting picture. Deterministic, pure, no I/O.
    """
    weighted_categories = tuple(c for c in grade_model.categories if c.weight is not None)
    categories_without_weight = tuple(c for c in grade_model.categories if c.weight is None)

    standalone_weighted_assessments = tuple(
        a for a in grade_model.assessments if a.weight is not None and a.category is None
    )
    category_scoped_weighted_assessments = tuple(
        a for a in grade_model.assessments if a.weight is not None and a.category is not None
    )

    decomposable_categories: list[GradeCategory] = []
    decomposed_assessments: list[Assessment] = []
    for category in weighted_categories:
        children = _decomposition_children(grade_model, category)
        if children is not None:
            decomposable_categories.append(category)
            decomposed_assessments.extend(children)

    return EffectiveCourseWeights(
        weighted_categories=weighted_categories,
        standalone_weighted_assessments=standalone_weighted_assessments,
        categories_without_weight=categories_without_weight,
        category_scoped_weighted_assessments=category_scoped_weighted_assessments,
        decomposable_categories=tuple(decomposable_categories),
        decomposed_assessments=tuple(decomposed_assessments),
    )
