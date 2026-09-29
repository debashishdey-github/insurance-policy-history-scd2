"""Overlap detection -- the safety net checked after every change.

`apply_change` is written to prevent overlaps by construction, but this
module exists so the guarantee is verified, not assumed. It also gives you a
standalone check to run against history that arrived from somewhere else
(a source extract, a restored backup) that never went through apply_change.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .model import PolicyVersion


@dataclass(frozen=True)
class Overlap:
    first: PolicyVersion
    second: PolicyVersion


def find_overlaps(versions: list[PolicyVersion]) -> list[Overlap]:
    """Detect any pair of (non-voided) versions for the same policy that overlap in time."""
    overlaps: list[Overlap] = []
    active = [v for v in versions if not v.voided]
    ordered = sorted(active, key=lambda v: v.valid_from)
    for prev, curr in zip(ordered, ordered[1:]):
        if prev.policy_id != curr.policy_id:
            continue
        if curr.valid_from < prev.effective_end:
            overlaps.append(Overlap(prev, curr))
    return overlaps


def assert_no_overlaps(versions: list[PolicyVersion]) -> None:
    overlaps = find_overlaps(versions)
    if overlaps:
        first = overlaps[0]
        raise AssertionError(
            f"overlapping versions for {first.first.policy_id}: "
            f"[{first.first.valid_from}, {first.first.valid_to}) and "
            f"[{first.second.valid_from}, {first.second.valid_to})"
        )


def query_as_of(history: list[PolicyVersion], as_of: date) -> PolicyVersion | None:
    """Return the single version valid on as_of, or None. Raises if more than one matches.

    Under a correctly maintained (nonoverlapping) history at most one version
    can ever match; raising here turns a broken invariant into a loud failure
    instead of a query that silently picks whichever row the database
    happened to return first.
    """
    matches = [v for v in history if not v.voided and v.covers(as_of)]
    if len(matches) > 1:
        raise AssertionError(f"invariant violated: {len(matches)} versions match {as_of}, expected at most 1")
    return matches[0] if matches else None
