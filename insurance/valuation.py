"""Stage 4 -- Pin valuation inputs.

Records exactly which snapshot, model version and business date a valuation
run used, and lets that run be reproduced later from the same pinned inputs.
Product-specific actuarial calculations are out of scope here -- this module
only proves the *reproducibility contract*, using premium totals and
coverage-group counts as stand-ins for a real pricing model's outputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .model import PolicyVersion
from .validation import query_as_of


@dataclass(frozen=True)
class ValuationRun:
    source_snapshot_id: str
    model_version: str
    business_date: date
    policy_versions_as_of: dict[str, PolicyVersion | None]


def pin_valuation_run(
    all_histories: dict[str, list[PolicyVersion]],
    source_snapshot_id: str,
    model_version: str,
    business_date: date,
) -> ValuationRun:
    as_of = {
        policy_id: query_as_of(history, business_date)
        for policy_id, history in all_histories.items()
    }
    return ValuationRun(source_snapshot_id, model_version, business_date, as_of)


def reproduce(run: ValuationRun, all_histories: dict[str, list[PolicyVersion]]) -> bool:
    """Re-derive the run from the same pinned inputs and confirm identical output.

    A `False` result here means either the histories changed since the run
    (which should never happen for an already-pinned snapshot) or the
    query logic itself is non-deterministic -- both are gate failures.
    """
    replay = pin_valuation_run(all_histories, run.source_snapshot_id, run.model_version, run.business_date)
    return replay == run


def total_premium_minor(run: ValuationRun) -> int:
    return sum(
        version.attributes.get("premium_minor", 0)
        for version in run.policy_versions_as_of.values()
        if version is not None
    )


def coverage_group_counts(run: ValuationRun) -> dict[str, int]:
    counts: dict[str, int] = {}
    for version in run.policy_versions_as_of.values():
        if version is None:
            continue
        group = version.attributes.get("coverage_group", "UNKNOWN")
        counts[group] = counts.get(group, 0) + 1
    return counts
