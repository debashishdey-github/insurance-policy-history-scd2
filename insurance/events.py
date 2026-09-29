"""Stage 3 -- Apply corrections and deletes.

The playbook is explicit that "a deletion might mean cancellation, archival
or physical removal -- those are different business events." This module
gives each one its own function with its own effect on history, rather than
collapsing all three into one generic delete.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from enum import Enum

from .model import PolicyVersion
from .scd2 import apply_change


class PolicyEventType(Enum):
    NEW_BUSINESS = "NEW_BUSINESS"
    CORRECTION = "CORRECTION"
    CANCELLATION = "CANCELLATION"
    ARCHIVAL = "ARCHIVAL"
    ERRONEOUS_REMOVAL = "ERRONEOUS_REMOVAL"


def apply_new_business_or_correction(history: list[PolicyVersion], version: PolicyVersion) -> list[PolicyVersion]:
    """NEW_BUSINESS and CORRECTION both go through the same effective-dating machinery.

    The distinction between them is business metadata (was this the first
    version of the policy, or a change to an existing one), not a difference
    in how the version is applied to history.
    """
    return apply_change(history, version)


def apply_cancellation(history: list[PolicyVersion], policy_id: str, effective_date: date,
                        recorded_at: date, change_seq: int) -> list[PolicyVersion]:
    """A cancellation closes the currently open version; prior history is untouched.

    This is deliberately NOT a delete: every version that existed before the
    cancellation remains exactly as it was, satisfiable by any historical
    query for a date before the cancellation took effect.
    """
    updated: list[PolicyVersion] = []
    closed_one = False
    for v in history:
        if v.policy_id == policy_id and v.valid_to is None and not v.voided:
            updated.append(replace(v, valid_to=effective_date))
            closed_one = True
        else:
            updated.append(v)
    if not closed_one:
        raise ValueError(f"no open version found to cancel for policy {policy_id!r}")
    updated.append(PolicyVersion(
        policy_id=policy_id, valid_from=effective_date, valid_to=None,
        recorded_at=recorded_at, change_seq=change_seq, attributes={"status": "CANCELLED"},
    ))
    return updated


def mark_archival_eligible(history: list[PolicyVersion], as_of: date) -> list[PolicyVersion]:
    """Archival is a retention-lifecycle flag, not a change to effective dating.

    It never alters valid_from/valid_to on any version -- a version that is
    archival-eligible still answers historical queries exactly as before.
    Only a separate storage-lifecycle process, outside this module, decides
    what to do with archival-eligible data.
    """
    return [
        replace(v, attributes={**v.attributes, "archival_eligible": True})
        if v.effective_end <= as_of and not v.voided
        else v
        for v in history
    ]


def void_erroneous_version(history: list[PolicyVersion], change_seq: int) -> list[PolicyVersion]:
    """An erroneous removal means the version should never have existed at all.

    Unlike cancellation, this does not close a range at a business date --
    the voided version is excluded from every query, past and present, while
    remaining physically present (with voided=True) for audit purposes.

    Limitation: this only removes the voided version itself. If its original
    insertion truncated or split a neighboring version (via apply_change), that
    side effect is not undone -- doing so exactly requires replaying the event
    log with the voided entry excluded, which is outside this function's scope.
    """
    updated = [replace(v, voided=True) if v.change_seq == change_seq else v for v in history]
    if not any(v.change_seq == change_seq for v in updated):
        raise ValueError(f"no version with change_seq={change_seq} found to void")
    return updated
