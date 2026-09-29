"""Stage 2 -- Model nonoverlapping versions.

`apply_change` inserts a new version into a policy's history and adjusts any
existing version it overlaps, so the result is guaranteed nonoverlapping by
construction rather than by hoping the caller got the dates right. This is
the direct implementation of the playbook's warning: "a naive insert-only
implementation will leave two versions both claiming to be valid on some of
the same dates."
"""
from __future__ import annotations

from dataclasses import replace

from .model import PolicyVersion
from .validation import assert_no_overlaps


def apply_change(history: list[PolicyVersion], new_version: PolicyVersion) -> list[PolicyVersion]:
    """Insert new_version, truncating or splitting any version it overlaps.

    Three cases per overlapping existing version `v`:
      A. v starts before new_version and extends into it   -> truncate v's valid_to to new_version.valid_from.
      B. v is entirely contained within new_version's range -> v is fully superseded; drop it.
      C. v starts within new_version but extends past its end -> push v's valid_from to new_version.valid_to.

    A version can also need both a truncation on one side and a push on the
    other if new_version lands strictly inside it -- that is a genuine split,
    handled by emitting two adjusted copies of v.
    """
    if any(v.policy_id != new_version.policy_id for v in history):
        raise ValueError("apply_change expects history for a single policy_id only")

    new_start = new_version.valid_from
    new_end = new_version.effective_end

    result: list[PolicyVersion] = []
    for v in history:
        v_start, v_end = v.valid_from, v.effective_end
        overlaps = new_start < v_end and new_end > v_start
        if not overlaps:
            result.append(v)
            continue

        starts_before = v_start < new_start
        ends_after = v_end > new_end

        if starts_before and ends_after:
            # new_version lands strictly inside v: split v into a before-piece and an after-piece.
            result.append(replace(v, valid_to=new_start))
            after_valid_to = None if v.valid_to is None else v.valid_to
            result.append(replace(v, valid_from=new_end, valid_to=after_valid_to))
        elif starts_before:
            # v starts before new_version and is truncated at new_version's start.
            result.append(replace(v, valid_to=new_start))
        elif ends_after:
            # v starts within new_version's range but extends past its end.
            result.append(replace(v, valid_from=new_end))
        # else: v is entirely contained within new_version's range -- fully superseded, dropped.

    result.append(new_version)
    result.sort(key=lambda ver: ver.valid_from)
    assert_no_overlaps(result)
    return result
