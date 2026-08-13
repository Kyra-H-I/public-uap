"""Schema-only UAP workflow vocabulary, adopted 2026-08-10.

This module freezes the closed words and bounds needed to generate an unambiguous
public schema for queries and plans. It deliberately contains no evaluator or plan
executor: query execution, repair orchestration, and plan execution remain gated
until they enter the conformance surface. Keeping vocabulary separate from execution prevents a
published draft from spawning incompatible grammars without pretending the host can
already run them.
"""

from __future__ import annotations

from enum import StrEnum

MAX_PLAN_STEPS = 32
MAX_PREDICATE_DEPTH = 8
MAX_PREDICATE_TERMS = 16
MAX_QUERY_FIELDS = 32
MAX_QUERY_ORDER_TERMS = 8
MAX_CURSOR_CHARS = 256
MAX_RESULT_PATH_CHARS = 256


class PredicateOperator(StrEnum):
    """The one recursive predicate carrier shared by queries and plan guards."""

    PREDICATE = "predicate"
    AND = "and"
    OR = "or"
    NOT = "not"


class ComparisonOperator(StrEnum):
    """Typed scalar comparisons available to ``prop.cmp`` in core."""

    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LTE = "lte"
    GT = "gt"
    GTE = "gte"


CORE_PREDICATES: tuple[str, ...] = (
    "ref.eq",
    "type.is",
    "rel.of",
    "prop.cmp",
    "text.range",
    "text.contains",
    "view.visible",
    "symbol.matches",
)


class QueryDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class PlanFailureMode(StrEnum):
    """What a guard failure does. Action failure always stops the plan."""

    STOP = "stop"
    SKIP_IF_GUARD_FAILED = "skip_if_guard_failed"


class PlanStatusKind(StrEnum):
    COMPLETED = "completed"
    STOPPED_AT = "stopped_at"
    CANCELLED = "cancelled"


class PlanStepState(StrEnum):
    """Accounting for every declared step, including ones that never ran."""

    RAN = "ran"
    SKIPPED = "skipped"
    NOT_RUN = "not_run"


class PlanRollbackState(StrEnum):
    """Per-step truth for a reverse-walk rollback attempt."""

    REVERTED = "reverted"
    FAILED = "failed"
    NOT_RUN = "not_run"
