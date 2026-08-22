"""v1 degree-requirement scheduler: topological ordering + credit-hour
bin-packing over an already-curated set of no-choice remaining courses.

Scope and design decisions: planning-docs/degree-planner-spec.md §10/§10.1.
Investigated and proposed against action_planning/query.py's
dependency_order() -- mirrored as closely as possible rather than
reinvented, same discipline the requirement-satisfaction engine used
matching this package's existing shape. Cycle detection is REUSED
directly from action_planning.builder.detect_cycles() (this module builds
throwaway PlanNode/PlanEdge objects to call it), not reimplemented --
dependency_order() itself is not reused, because its own Kahn's-algorithm
loop is written directly against UnifiedActionPlan/CourseDiscoveryResult,
neither of which this module's course-scheduling problem has any use for;
the ordering loop here is a small, separately-written mirror of that
function's lexicographic-tie-break style instead.

WHAT THIS MODULE DOES NOT DECIDE (a separation this codebase already
draws between action_planning/builder.py's classification and query.py's
ordering): which requirement-tree leaves are "no-choice" and therefore
in v1 scope, and which are genuinely-selection or freeform and therefore
belong in `unscheduled`. Callers pass in an already-curated `courses`
list and an already-curated `unscheduled` list; this module only orders
and bin-packs the former, and passes the latter through untouched.

Pure: no Client parameter, no I/O, no network access. `already_satisfied`
and the term horizon are supplied by the caller from already-fetched data
(course_records, expected_graduation), exactly as
requirement_satisfaction_fetch.py supplies already-fetched rows to
course_discovery/requirement_satisfaction.py's pure evaluator.
"""

from __future__ import annotations

from typing import Any, Iterable, Literal, Mapping

from pydantic import Field, model_validator

from GradusIQ_career.action_planning.builder import detect_cycles
from GradusIQ_career.action_planning.models import PlanEdge, PlanFailure, PlanNode
from GradusIQ_career.planning.term_view import term_key

from .models import StrictModel, StructuredPrerequisite

# v1 long-term-only cadence, per spec §10's term-offering-data
# simplification ("v1 assumes every course is offered every long term") --
# May/Summer/August intersessions are deliberately excluded from
# scheduling, not merely unhandled.
_NEXT_LONG_TERM: Mapping[str, tuple[int, str]] = {
    "Fall": (1, "Spring"),
    "Spring": (0, "Fall"),
}

# Course-record statuses counted as prerequisite-cleared for scheduling
# purposes. In-progress counts as cleared here, not just completed --
# consistent with §8.4's satisfaction-engine decision, but this is a
# SEPARATE, v1-scheduler-specific extension of it (§10.1), not the same
# rule as course_discovery.prerequisites.evaluate_prerequisites()'s
# conservative real-time gate: that function deliberately returns
# UNRESOLVED (not ELIGIBLE) for an in-progress prerequisite, because it
# answers "can I register right now". This module answers a different
# question -- "will this be done before the later term I'm placing the
# dependent course into" -- for which an in-progress course this term is
# safe to treat as cleared.
_CLEARED_STATUSES = frozenset({"completed", "in_progress"})

DEFAULT_CREDIT_HOUR_CAP = 15.0


class CourseToSchedule(StrictModel):
    """One already-decided, no-choice course still needed, with the
    requirement leaf it fulfills. Building this list (which leaves are
    no-choice, which course each one names) is the caller's job -- see
    the module docstring."""

    course_code: str = Field(min_length=1)
    credit_hours: float = Field(gt=0)
    requirement_group_id: str = Field(min_length=1)
    requirement_group_name: str = Field(min_length=1)
    selection_limitations: list[str] = Field(default_factory=list)


class ScheduledCourse(StrictModel):
    course_code: str
    credit_hours: float
    requirement_group_id: str
    # Human-readable notes on prerequisite facts this scheduler could not
    # safely turn into a hard ordering edge -- e.g. an OR-clause where
    # neither alternative is otherwise known to be satisfied. Never
    # silently dropped; see _clause_limitation().
    limitations: list[str] = Field(default_factory=list)


class TermPlan(StrictModel):
    term_key: str
    courses: list[ScheduledCourse] = Field(default_factory=list)
    total_credit_hours: float


UnscheduledReason = Literal["SELECTION_DEFERRED", "FREEFORM_MANUAL_REVIEW"]


class UnscheduledRequirement(StrictModel):
    """A requirement-tree leaf explicitly out of v1 scope, carried through
    into the output unchanged so the result is never silently incomplete
    -- matching DependencyOrderResult's unconstrained/limitations-never-
    silent convention."""

    requirement_group_id: str
    name: str
    reason: UnscheduledReason


ScheduleStatus = Literal["SCHEDULED", "ERROR"]


class ScheduleResult(StrictModel):
    student_id: str
    program_id: str
    terms: list[TermPlan] = Field(default_factory=list)
    unscheduled: list[UnscheduledRequirement] = Field(default_factory=list)
    status: ScheduleStatus = "SCHEDULED"
    failure: PlanFailure | None = None

    @model_validator(mode="after")
    def execution_contract(self):
        # Mirrors UnifiedActionPlan/DependencyOrderResult's own contract
        # exactly: an ERROR result carries a PlanFailure and NOTHING else,
        # so a caller can never mistake a fail-closed result for a partial,
        # silently-truncated plan.
        if self.status == "ERROR":
            if self.failure is None:
                raise ValueError("an ERROR result requires a PlanFailure")
            if self.terms or self.unscheduled:
                raise ValueError("an ERROR result cannot carry partial schedule data")
        elif self.failure is not None:
            raise ValueError("a non-ERROR result must not carry a PlanFailure")
        return self


def satisfied_course_codes(course_records: Iterable[Mapping[str, Any]]) -> set[str]:
    """course_records rows -> the set of course codes counted as
    prerequisite-cleared. See _CLEARED_STATUSES for the in-progress-counts
    decision this implements."""
    return {
        str(row["course_code"])
        for row in course_records
        if row.get("status") in _CLEARED_STATUSES and row.get("course_code")
    }


def _clause_limitation(course_codes: list[str]) -> str:
    alternatives = " or ".join(course_codes)
    return f"prerequisite ({alternatives}) not modeled as a hard ordering edge -- OR-clause, not tracked to a single alternative"


def _external_limitation(course_code: str) -> str:
    return f"prerequisite {course_code} is outside the scheduled course set and not yet satisfied -- not modeled as a hard ordering edge"


def _external_corequisite_limitation(course_code: str) -> str:
    return f"corequisite {course_code} is outside the scheduled course set and not yet satisfied -- same-term fulfillment cannot be verified"


def _build_dependencies(
    courses: list[CourseToSchedule],
    prerequisites: Mapping[str, StructuredPrerequisite],
    already_satisfied: Iterable[str],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], dict[str, list[str]]]:
    """Strict edges, same-term-eligible corequisite pairs, and limitations.

    Only single-course requires_all clauses whose one course is itself in
    `courses` become hard edges. Everything else -- an OR-clause with
    multiple alternatives, or a single-course clause naming a course
    outside both `courses` and `already_satisfied` -- is dropped from the
    graph and recorded as a limitation instead of being guessed at, per
    §10.1's OR-clause decision (mirroring action_planning/builder.py's own
    documented policy for PrerequisiteMode.ANY: "emitting nothing is the
    only choice that doesn't misrepresent the requirement").
    """
    in_scope = {course.course_code for course in courses}
    satisfied = set(already_satisfied)
    edges: list[tuple[str, str]] = []
    corequisite_pairs: list[tuple[str, str]] = []
    limitations: dict[str, list[str]] = {
        course.course_code: list(course.selection_limitations) for course in courses
    }

    for course in courses:
        structured = prerequisites.get(course.course_code)
        if structured is None:
            continue
        coreq_allowed = set(structured.coreq_allowed)
        coreqs_seen_in_clauses: set[str] = set()
        for clause in structured.requires_all:
            codes = clause.course_codes
            if any(code in satisfied for code in codes):
                # At least one alternative is already cleared -- the whole
                # clause is met, regardless of how many codes it names.
                continue
            clause_coreqs = [code for code in codes if code in coreq_allowed]
            coreqs_seen_in_clauses.update(clause_coreqs)
            if clause_coreqs:
                in_scope_coreqs = [code for code in clause_coreqs if code in in_scope]
                if len(in_scope_coreqs) == 1:
                    corequisite_pairs.append((course.course_code, in_scope_coreqs[0]))
                elif len(in_scope_coreqs) > 1:
                    limitations[course.course_code].append(
                        f"corequisite ({' or '.join(in_scope_coreqs)}) not resolved to a single alternative"
                    )
                else:
                    limitations[course.course_code].append(
                        _external_corequisite_limitation(clause_coreqs[0])
                    )
                codes = [code for code in codes if code not in coreq_allowed]
                if not codes:
                    continue
            if len(codes) > 1:
                limitations[course.course_code].append(_clause_limitation(codes))
                continue
            (code,) = codes
            if code in in_scope:
                edges.append((course.course_code, code))
            else:
                limitations[course.course_code].append(_external_limitation(code))

        # Pure corequisites (e.g. "Corequisite: BIOL 1301" or "concurrent
        # enrollment in CSCE 313") do not appear in requires_all at all.
        for code in structured.coreq_allowed:
            if code in coreqs_seen_in_clauses or code in satisfied:
                continue
            if code in in_scope:
                corequisite_pairs.append((course.course_code, code))
            else:
                limitations[course.course_code].append(_external_corequisite_limitation(code))

    return edges, corequisite_pairs, limitations


def _next_long_term(year: int, season: str) -> tuple[int, str]:
    if season not in _NEXT_LONG_TERM:
        raise ValueError(f"Unsupported starting season {season!r}; expected 'Fall' or 'Spring'.")
    year_delta, next_season = _NEXT_LONG_TERM[season]
    return year + year_delta, next_season


def schedule_courses(
    student_id: str,
    program_id: str,
    courses: list[CourseToSchedule],
    prerequisites: Mapping[str, StructuredPrerequisite],
    already_satisfied: Iterable[str],
    unscheduled: list[UnscheduledRequirement],
    *,
    starting_year: int,
    starting_season: Literal["Fall", "Spring"],
    max_terms: int,
    credit_hour_cap: float = DEFAULT_CREDIT_HOUR_CAP,
) -> ScheduleResult:
    """Topologically order `courses` by real prerequisite edges, then
    greedily bin-pack that order into up to `max_terms` long terms
    starting at (starting_year, starting_season), each capped at
    `credit_hour_cap` credit hours.

    Fails closed (status="ERROR", terms=[], unscheduled=[]) rather than
    returning a partial or silently-wrong plan when:
      - the requires-graph among `courses` contains a cycle;
      - a single required course's credit_hours exceeds credit_hour_cap
        on its own (nothing could ever be scheduled for it); or
      - `courses` cannot all be placed within `max_terms` (over-
        constrained: more requirements than terms/capacity allow before
        the student's expected graduation).

    Tie-breaking among courses that become ready in the same term is
    plain lexicographic course_code order -- no ranking, no preference
    logic -- matching action_planning/query.py::dependency_order()'s own
    documented tie-break rule exactly.
    """
    course_by_code = {course.course_code: course for course in courses}

    plan_nodes = [
        PlanNode(node_id=code, node_type="course", source_ref=code, status="OPEN")
        for code in course_by_code
    ]
    edge_pairs, corequisite_pairs, limitations_by_code = _build_dependencies(
        courses, prerequisites, already_satisfied
    )
    plan_edges = [
        PlanEdge(from_node_id=dependent, to_node_id=prerequisite, relation="requires")
        for dependent, prerequisite in edge_pairs
    ]

    if detect_cycles(plan_nodes, plan_edges):
        return ScheduleResult(
            student_id=student_id,
            program_id=program_id,
            status="ERROR",
            failure=PlanFailure(
                error_class="CycleDetected",
                safe_message="The prerequisite graph contains a requires cycle and cannot be scheduled safely.",
            ),
        )

    successors: dict[str, list[str]] = {code: [] for code in course_by_code}
    in_degree: dict[str, int] = {code: 0 for code in course_by_code}
    for dependent, prerequisite in edge_pairs:
        successors[prerequisite].append(dependent)
        in_degree[dependent] += 1

    corequisites_by_dependent: dict[str, list[str]] = {code: [] for code in course_by_code}
    for dependent, corequisite in corequisite_pairs:
        corequisites_by_dependent[dependent].append(corequisite)

    # A course whose own credit_hours already exceeds the cap can never be
    # scheduled -- fail closed immediately rather than looping forever
    # trying to fit it.
    for course in courses:
        if course.credit_hours > credit_hour_cap:
            return ScheduleResult(
                student_id=student_id,
                program_id=program_id,
                status="ERROR",
                failure=PlanFailure(
                    error_class="CreditHourCapTooSmall",
                    safe_message=(
                        f"{course.course_code} requires {course.credit_hours} credit hours, "
                        f"exceeding the {credit_hour_cap}-credit-hour term cap on its own."
                    ),
                ),
            )

    ready = sorted(code for code, degree in in_degree.items() if degree == 0)
    placed: set[str] = set()
    terms: list[TermPlan] = []
    year, season = starting_year, starting_season

    for _ in range(max_terms):
        if not ready:
            break
        chosen: set[str] = set()
        ready_set = set(ready)

        def corequisite_closure(code: str, visiting: set[str] | None = None) -> set[str] | None:
            """Courses that must accompany `code` this term.

            A corequisite already placed in an earlier term is cleared. An
            in-scope corequisite not yet strictly ready cannot accompany the
            dependent safely. `visiting` makes mutual corequisites a single
            same-term component rather than a dependency cycle.
            """
            if code in placed or code in chosen:
                return set()
            if code not in ready_set:
                return None
            visiting = set() if visiting is None else visiting
            if code in visiting:
                return set()
            visiting.add(code)
            closure = {code}
            for corequisite in corequisites_by_dependent.get(code, []):
                if corequisite in placed or corequisite in chosen:
                    continue
                nested = corequisite_closure(corequisite, visiting)
                if nested is None:
                    return None
                closure.update(nested)
            return closure

        for code in ready:
            if code in chosen:
                continue
            closure = corequisite_closure(code)
            if closure is None:
                continue
            additional = closure - chosen
            credits = sum(course_by_code[item].credit_hours for item in additional)
            current_total = sum(course_by_code[item].credit_hours for item in chosen)
            if current_total + credits <= credit_hour_cap:
                chosen.update(additional)

        term_courses = sorted(chosen)
        total = sum(course_by_code[code].credit_hours for code in term_courses)
        if not term_courses:
            break

        terms.append(
            TermPlan(
                term_key=term_key(year, season),
                courses=[
                    ScheduledCourse(
                        course_code=code,
                        credit_hours=course_by_code[code].credit_hours,
                        requirement_group_id=course_by_code[code].requirement_group_id,
                        limitations=limitations_by_code.get(code, []),
                    )
                    for code in term_courses
                ],
                total_credit_hours=total,
            )
        )

        newly_ready: list[str] = []
        for code in term_courses:
            for successor in successors[code]:
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    newly_ready.append(successor)
        placed.update(term_courses)
        ready = sorted((ready_set - chosen) | set(newly_ready))
        year, season = _next_long_term(year, season)

    if ready:
        # Every course that will ever become ready given credit_hour_cap
        # has been tried, and courses remain -- genuinely over-constrained
        # for this term horizon, not a bug in the loop above.
        return ScheduleResult(
            student_id=student_id,
            program_id=program_id,
            status="ERROR",
            failure=PlanFailure(
                error_class="OverConstrained",
                safe_message=(
                    f"{len(ready)} required course(s) could not be placed within "
                    f"{max_terms} term(s) at a {credit_hour_cap}-credit-hour cap: "
                    f"{', '.join(ready)}."
                ),
            ),
        )

    return ScheduleResult(
        student_id=student_id,
        program_id=program_id,
        terms=terms,
        unscheduled=unscheduled,
        status="SCHEDULED",
        failure=None,
    )
