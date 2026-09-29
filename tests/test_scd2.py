from datetime import date

from insurance.events import (
    apply_cancellation,
    apply_new_business_or_correction,
    mark_archival_eligible,
    void_erroneous_version,
)
from insurance.model import PolicyVersion
from insurance.scd2 import apply_change
from insurance.validation import find_overlaps, query_as_of
from insurance.valuation import pin_valuation_run, reproduce, total_premium_minor


def v(policy_id="P0001", valid_from=date(2026, 1, 1), valid_to=None,
      recorded_at=None, change_seq=1, **attrs):
    return PolicyVersion(
        policy_id=policy_id, valid_from=valid_from, valid_to=valid_to,
        recorded_at=recorded_at or valid_from, change_seq=change_seq, attributes=attrs,
    )


# --- Half-open range basics ---

def test_at_most_one_version_matches_any_business_date():
    history = [v(valid_from=date(2026, 1, 1), valid_to=date(2026, 6, 1), premium_minor=1000),
               v(valid_from=date(2026, 6, 1), valid_to=None, premium_minor=1200, change_seq=2)]
    # The boundary date belongs to the SECOND version, not both -- this is exactly
    # what half-open ranges guarantee and closed ranges would break.
    assert query_as_of(history, date(2026, 5, 31)).attributes["premium_minor"] == 1000
    assert query_as_of(history, date(2026, 6, 1)).attributes["premium_minor"] == 1200
    assert query_as_of(history, date(2026, 12, 1)).attributes["premium_minor"] == 1200
    assert query_as_of(history, date(2025, 1, 1)) is None


# --- Acceptance gate: no unintended overlapping effective ranges per policy. ---

def test_backdated_correction_truncates_the_currently_open_version():
    history = [v(valid_from=date(2026, 1, 1), valid_to=None, premium_minor=1000)]
    correction = v(valid_from=date(2026, 8, 15), valid_to=None, premium_minor=1500, change_seq=2)
    updated = apply_change(history, correction)
    assert find_overlaps(updated) == []
    assert query_as_of(updated, date(2026, 8, 14)).attributes["premium_minor"] == 1000
    assert query_as_of(updated, date(2026, 8, 15)).attributes["premium_minor"] == 1500


def test_backdated_correction_landing_strictly_inside_a_closed_version_splits_it():
    # One existing version spanning the whole year; a correction lands in the middle of it.
    history = [v(valid_from=date(2026, 1, 1), valid_to=date(2026, 12, 1), premium_minor=1000)]
    correction = v(valid_from=date(2026, 4, 1), valid_to=date(2026, 5, 1), premium_minor=1500, change_seq=2)
    updated = apply_change(history, correction)
    assert find_overlaps(updated) == []
    assert query_as_of(updated, date(2026, 2, 1)).attributes["premium_minor"] == 1000  # before-piece
    assert query_as_of(updated, date(2026, 4, 15)).attributes["premium_minor"] == 1500  # the correction itself
    assert query_as_of(updated, date(2026, 6, 1)).attributes["premium_minor"] == 1000  # after-piece
    assert query_as_of(updated, date(2026, 12, 15)) is None  # original end date is unchanged


def test_new_version_that_fully_supersedes_an_existing_one_drops_it():
    history = [v(valid_from=date(2026, 3, 1), valid_to=date(2026, 4, 1), premium_minor=999, change_seq=1)]
    replacement = v(valid_from=date(2026, 1, 1), valid_to=date(2026, 12, 1), premium_minor=1500, change_seq=2)
    updated = apply_change(history, replacement)
    assert find_overlaps(updated) == []
    # The fully-contained original version is gone; the replacement covers its whole range.
    assert query_as_of(updated, date(2026, 3, 15)).attributes["premium_minor"] == 1500
    assert len(updated) == 1


def test_the_documented_playbook_example_no_longer_overlaps_after_apply_change():
    # The exact scenario from the playbook's own has_overlap() example, but run
    # through apply_change instead of only being detected after the fact.
    history = [v(valid_from=date(2026, 1, 1), valid_to=date(2026, 9, 1), premium_minor=1000)]
    backdated = v(valid_from=date(2026, 8, 15), valid_to=None, premium_minor=1100, change_seq=2)
    updated = apply_change(history, backdated)
    assert find_overlaps(updated) == []


# --- Acceptance gate: cancellation, archival and erroneous removal are distinct events. ---

def test_cancellation_closes_current_version_but_preserves_prior_history():
    history = [v(valid_from=date(2026, 1, 1), valid_to=None, premium_minor=1000)]
    updated = apply_cancellation(history, "P0001", date(2026, 6, 1), recorded_at=date(2026, 6, 1), change_seq=2)
    assert query_as_of(updated, date(2026, 3, 1)).attributes["premium_minor"] == 1000
    assert query_as_of(updated, date(2026, 6, 1)).attributes["status"] == "CANCELLED"
    assert find_overlaps(updated) == []


def test_archival_never_changes_effective_dating():
    history = [v(valid_from=date(2020, 1, 1), valid_to=date(2021, 1, 1), premium_minor=500)]
    before = query_as_of(history, date(2020, 6, 1))
    updated = mark_archival_eligible(history, date(2026, 1, 1))
    after = query_as_of(updated, date(2020, 6, 1))
    assert before.valid_from == after.valid_from and before.valid_to == after.valid_to
    assert after.attributes["archival_eligible"] is True


def test_erroneous_removal_voids_a_version_everywhere_not_just_going_forward():
    history = [v(valid_from=date(2026, 1, 1), valid_to=None, premium_minor=1000, change_seq=1)]
    updated = void_erroneous_version(history, change_seq=1)
    # The voided version must not answer a query for ANY date, including ones
    # that were valid before the void -- it should never have existed.
    assert query_as_of(updated, date(2026, 3, 1)) is None
    assert query_as_of(updated, date(2020, 1, 1)) is None


def test_cancellation_and_erroneous_removal_have_different_effects_on_history():
    history = [v(valid_from=date(2026, 1, 1), valid_to=None, premium_minor=1000, change_seq=1)]
    cancelled = apply_cancellation(list(history), "P0001", date(2026, 6, 1),
                                    recorded_at=date(2026, 6, 1), change_seq=2)
    voided = void_erroneous_version(list(history), change_seq=1)
    # Cancellation: the original version is still queryable before the cancellation date.
    assert query_as_of(cancelled, date(2026, 3, 1)) is not None
    # Erroneous removal: the same original version is queryable nowhere at all.
    assert query_as_of(voided, date(2026, 3, 1)) is None


# --- Acceptance gate: a prior published valuation input can be reproduced exactly. ---

def test_valuation_run_is_reproducible_from_pinned_inputs():
    histories = {
        "P0001": [v(policy_id="P0001", valid_from=date(2026, 1, 1), valid_to=None, premium_minor=1000)],
        "P0002": [v(policy_id="P0002", valid_from=date(2026, 1, 1), valid_to=None, premium_minor=2000)],
    }
    run = pin_valuation_run(histories, source_snapshot_id="snap-001", model_version="v1", business_date=date(2026, 6, 1))
    assert reproduce(run, histories) is True
    assert total_premium_minor(run) == 3000


def test_valuation_run_detects_drift_if_histories_changed_after_pinning():
    histories = {"P0001": [v(policy_id="P0001", valid_from=date(2026, 1, 1), valid_to=None, premium_minor=1000)]}
    run = pin_valuation_run(histories, source_snapshot_id="snap-001", model_version="v1", business_date=date(2026, 6, 1))
    mutated_histories = {"P0001": apply_change(
        histories["P0001"], v(policy_id="P0001", valid_from=date(2026, 3, 1), valid_to=None, premium_minor=9999, change_seq=2)
    )}
    assert reproduce(run, mutated_histories) is False


def test_new_business_and_correction_share_the_same_effective_dating_machinery():
    history: list[PolicyVersion] = []
    history = apply_new_business_or_correction(history, v(valid_from=date(2026, 1, 1), valid_to=None, premium_minor=1000))
    history = apply_new_business_or_correction(
        history, v(valid_from=date(2026, 6, 1), valid_to=None, premium_minor=1200, change_seq=2)
    )
    assert find_overlaps(history) == []
    assert query_as_of(history, date(2026, 12, 1)).attributes["premium_minor"] == 1200
