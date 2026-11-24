Register update for the `#660` line-2 landing. Code change was PR #663,
squash-merged as `75fe2a8ada93983bbb913f5d7fd29e67acc112a1`.

## What this row now says

The `#660` row recorded "No code landed yet". It now names the landing, the
merge SHA, and what that landing actually covers, and keeps the issue OPEN with
line 1 named as unbuilt. That is the honest split: one of the two #343
acceptance sentences moved, the other did not, and #660 carries both.

## What did not change

- Issue count: 40 open before and 40 open after. No row changes disposition, so
  the canonical census line and the open-set enumeration are untouched, as are
  both wave tables and the mirror arithmetic.
- `#343` stays CLOSED at its operator close time with the #660 pointer, and
  `#344` keeps its own landed rows (`6602e00d`, `03306b0e`) and its two named
  remainders.

## Verification

- `pytest tests/test_docs_contracts.py tests/test_driving_hygiene.py -q` ->
  26 passed, 2 subtests passed.
- `python scripts/driving_hygiene_ci.py` over the committed diff -> clean.
