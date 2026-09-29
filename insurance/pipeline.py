"""End-to-end demo wiring the four stages together on a small, readable scenario.

Run with: python3 -m insurance.pipeline
"""
from __future__ import annotations

from datetime import date

from .events import apply_cancellation, apply_new_business_or_correction, void_erroneous_version
from .model import PolicyVersion
from .validation import assert_no_overlaps, query_as_of
from .valuation import coverage_group_counts, pin_valuation_run, reproduce, total_premium_minor


def _demo() -> None:
    history: list[PolicyVersion] = []

    # New business: policy P1001 written effective 2026-01-01.
    history = apply_new_business_or_correction(history, PolicyVersion(
        policy_id="P1001", valid_from=date(2026, 1, 1), valid_to=None,
        recorded_at=date(2026, 1, 1), change_seq=1,
        attributes={"premium_minor": 84000, "coverage_group": "AUTO", "status": "ACTIVE"},
    ))
    print(f"after new business: {len(history)} version(s)")

    # A valuation run is pinned against the state as of 2026-04-01, before any correction arrives.
    run_q1 = pin_valuation_run(
        {"P1001": history}, source_snapshot_id="snap-2026-04-01",
        model_version="pricing-v3", business_date=date(2026, 4, 1),
    )
    print(f"Q1 run: total premium = {total_premium_minor(run_q1)}, groups = {coverage_group_counts(run_q1)}")

    # A backdated correction arrives on 2026-05-20: the true premium from 2026-03-01 was higher.
    history = apply_new_business_or_correction(history, PolicyVersion(
        policy_id="P1001", valid_from=date(2026, 3, 1), valid_to=None,
        recorded_at=date(2026, 5, 20), change_seq=2,
        attributes={"premium_minor": 91500, "coverage_group": "AUTO", "status": "ACTIVE"},
    ))
    assert_no_overlaps(history)
    print(f"after backdated correction: {len(history)} version(s), no overlaps")

    # The Q1 valuation run must still reproduce its ORIGINAL answer -- it was pinned
    # before the correction existed, so replaying it against today's (corrected) history
    # would silently change a number that was already published. This is the drift check.
    print(f"Q1 run reproducible against corrected history? {reproduce(run_q1, {'P1001': history})}")
    # A fresh run pinned against the current state picks up the correction.
    run_q2 = pin_valuation_run(
        {"P1001": history}, source_snapshot_id="snap-2026-06-01",
        model_version="pricing-v3", business_date=date(2026, 6, 1),
    )
    print(f"post-correction run: total premium = {total_premium_minor(run_q2)}")

    # The policyholder cancels effective 2026-09-01.
    history = apply_cancellation(history, "P1001", date(2026, 9, 1), recorded_at=date(2026, 9, 1), change_seq=3)
    assert query_as_of(history, date(2026, 8, 31)).attributes["status"] == "ACTIVE"
    assert query_as_of(history, date(2026, 9, 1)).attributes["status"] == "CANCELLED"
    print("after cancellation: prior history intact, current status CANCELLED")

    # A second policy, P1002, is loaded twice from a duplicate feed file by mistake --
    # the whole version should never have existed. Because it was never applied on top
    # of (or under) any other version, voiding it removes it cleanly with no side effects.
    duplicate_load = [PolicyVersion(
        policy_id="P1002", valid_from=date(2026, 2, 1), valid_to=None,
        recorded_at=date(2026, 2, 1), change_seq=1,
        attributes={"premium_minor": 45000, "coverage_group": "HOME", "status": "ACTIVE"},
    )]
    voided = void_erroneous_version(duplicate_load, change_seq=1)
    assert query_as_of(voided, date(2026, 6, 1)) is None
    print("after voiding the duplicate load: P1002 answers no query, as if it never existed")
    print(
        "note: voiding only removes the voided version itself -- if its original insertion "
        "truncated or split a neighboring version (as change_seq=2 did to change_seq=1 above), "
        "that side effect is not automatically undone. Reversing it exactly requires replaying "
        "the event log with the voided entry excluded, which is outside this module's scope."
    )


if __name__ == "__main__":
    _demo()
