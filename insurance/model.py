"""Data model for effective-dated policy history (SCD type 2).

Ranges are half-open: [valid_from, valid_to). `valid_to = None` means the
version is currently open (still in effect). This is deliberate -- a closed
interval on both ends is what lets a version ending exactly on 2026-09-01 and
a version starting exactly on 2026-09-01 both match a query for that date,
which is exactly the kind of accidental double-match this model avoids.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class PolicyVersion:
    policy_id: str
    valid_from: date
    valid_to: date | None  # None = currently open.
    recorded_at: date  # System time: when this version was recorded, distinct from valid_from.
    change_seq: int
    attributes: dict = field(default_factory=dict)  # e.g. {"premium_minor": 50000, "status": "ACTIVE"}
    voided: bool = False  # True only for an erroneous-removal event; excluded from all queries.

    def __post_init__(self) -> None:
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError(f"valid_to ({self.valid_to}) must be after valid_from ({self.valid_from})")

    @property
    def effective_end(self) -> date:
        """A sentinel far-future date standing in for 'still open', to simplify range math."""
        return self.valid_to if self.valid_to is not None else date.max

    def covers(self, as_of: date) -> bool:
        return self.valid_from <= as_of < self.effective_end
