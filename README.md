# Insurance Policy History (SCD Type 2)

A small, fully tested reference implementation of effective-dated policy
history for an insurance book of business: nonoverlapping version ranges,
backdated corrections, three distinct kinds of "deletion," and reproducible
valuation runs.

This is a **focused reference pipeline**, not a platform. It has no database,
no orchestrator, and no I/O layer. Every function takes plain Python data in
and returns plain Python data out, so the core algorithm — the part that is
easy to get subtly wrong — is easy to read, test, and reuse independently of
whatever storage engine or workflow tool a real system would use.

## Project status

Built as a teaching companion to the [Insurance policy history & valuation
playbook](https://datasparkle.academy) on DataSparkle Academy. It implements
that playbook's four stages end to end and is exercised by a test suite that
maps directly onto the playbook's own acceptance checks. It is not affiliated
with, and does not depend on, any insurance carrier's actual systems.

## Why this is harder than it looks

A policy's premium, coverage, and status change over time, and a valuation or
audit needs to ask "what did this policy look like as of date X" for any X —
not just today. The naive approach — insert a new row for every change — falls
apart the moment a correction arrives out of order: a backdated fix can leave
two rows both claiming to be valid on the same date, and a query for that date
becomes ambiguous.

This project treats that as the central problem to solve, not an edge case to
handle later:

- **[`insurance/model.py`](insurance/model.py)** — `PolicyVersion` with a
  half-open `[valid_from, valid_to)` range. Half-open, not closed on both
  ends, so a version ending on a date and a version starting on that same
  date can never both match a query for it.
- **[`insurance/scd2.py`](insurance/scd2.py)** — `apply_change()`, the core
  algorithm. Inserting a new version truncates, splits, or fully supersedes
  any existing version it overlaps, so the result is nonoverlapping *by
  construction* rather than by hoping every caller got the dates right.
- **[`insurance/validation.py`](insurance/validation.py)** — `find_overlaps()`
  and `assert_no_overlaps()` as an independent safety net checked after every
  change, plus `query_as_of()`, which raises loudly if more than one version
  ever matches a single date (it never should, but a query that silently
  picks whichever row a database happened to return first is worse than a
  crash).
- **[`insurance/events.py`](insurance/events.py)** — cancellation, archival
  eligibility, and erroneous-version removal as three separate functions with
  three different effects on history, because a generic "delete" collapses
  business events that behave nothing alike: a cancellation closes an open
  range but keeps prior history queryable; archival never touches effective
  dating at all; an erroneous removal excludes a version from every query,
  past and present, as if it never existed.
- **[`insurance/valuation.py`](insurance/valuation.py)** — pins the exact
  snapshot, model version, and business date behind a valuation run, so that
  run can be reproduced later and compared bit-for-bit against what was
  originally published — even after later corrections have changed what
  "today's" answer would be.

## Known limitation

`void_erroneous_version()` removes the voided version from every query, but it
does not undo truncations or splits that version's original insertion caused
to *other* versions. If version B was inserted after version A and truncated
A's range, voiding B removes B cleanly but leaves A truncated — a real
coverage gap. Repairing that exactly requires replaying the full event log
with the voided entry excluded, which is a materially bigger job (an
event-sourced history, not a flat version list) and is deliberately left out
of this project's scope. See the docstring on `void_erroneous_version` and the
second half of the `pipeline.py` demo, which reproduces this gap on purpose so
it is visible rather than silently wrong.

## Running it

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -v
python3 -m insurance.pipeline   # walks through new business, a backdated
                                # correction, a pinned valuation run, a
                                # cancellation, and a clean void, printing
                                # each stage's effect on history
```

## What the tests actually check

`tests/test_scd2.py` maps to the playbook's stated acceptance gates:

- At most one version ever matches a query for a given date (the half-open
  range guarantee).
- A backdated correction can truncate an open version, split a closed version
  down the middle, or fully supersede a version it completely contains —
  and `find_overlaps()` reports zero overlaps after every case.
- Cancellation, archival, and erroneous removal are verified to have three
  genuinely different effects on the same starting history, not the same
  effect under three names.
- A valuation run pinned against one snapshot reproduces identically when
  replayed against that same snapshot, and is shown to diverge (correctly)
  if replayed against a history that changed afterward.

## License

MIT — see [LICENSE](LICENSE).
