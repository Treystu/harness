## CHECK-IN pass-24 - Lane 1 (order item 10: the suite pinned its ledger but not the operator home)

Lane 1 read the lane's GitHub surfaces, found no newer steering than its own
pass-23 filing, and took the first unworked, unblocked item. Items 1-4, 7-9 of
the filed order have landed in earlier passes; item 5 stays delivered only to
the limit of this machine's data; item 6 stays skipped (#655 waits on PR #701,
which is open and refs-only, and #704 still has no PR).

### VERIFIED AT TURN START

- `treystu/main` at `2e156c92`, the #653 squash merge this lane landed last
  pass. Local tree clean apart from untracked scratch logs.
- #295 comments read to the last page: the newest are this lane's own pass-23
  check-in (`7140872246`) and its gate receipt (`7140872941`). No newer Treystu
  comment, no STOP, no steering.
- #653 read: this lane's landing evidence (`7140870687`) and receipt
  (`7140871324`) are the newest. The issue stays OPEN, as intended.
- #684 read: newest is the owner's oversight push from 2026-11-23, unchanged.
- Open PRs: #709 (`6ed34b80`, #654, not this lane's), #702 (`7e4ec0bf`),
  #701 (`e280e20f`, refs-only for #655), #685 (`18e8160b`, the standup lane's
  tree this lane does not edit). None is this lane's work; nothing of this
  lane's was waiting on a read.

### DONE THIS PASS - #656

Took #656, the hourglass test-isolation defect: the nearest genuine, unblocked,
in-repo item after #653. PR #719 at head `492c01d0`, rail read per context at
that head **n=16 ok=16 pend=0 bad=**, squash-merged **`746e3621`**.

- Guard: `tests/__init__.py` now pins `HARNESS_HOME` and `HARNESS_CONFIG_DIR` at
  one ephemeral directory per process. The issue's receipt named a
  `conftest.py`, but CI runs `python -m unittest discover -s tests`, so a
  conftest never loads; the suite's existing per-process seam is
  `tests/__init__.py`, which already pins `HARNESS_LEDGER` (`DF-LEDGER-2`).
- Count, from this laptop's operator document as the primary source: **1117 of
  1163 facts (96.0%) are test-run rows**, 46 durable kept. The historical figure
  was 3766 of 5254 (71.7%).
- Cleanup: `scripts/clean_memory_contamination.py`, dry-run by default, backup
  before `--apply`, idempotent, refuses a hash-chained `ledger.jsonl`.
- Measured proof the leak stopped: the operator memory was `331511` bytes, mtime
  `1795544445`, sha256 prefix `777408f0` before and after a full `7916`-test
  run, byte- and mtime-identical. The operator document was not modified by this
  lane.
- Full CI-equivalent run: `Ran 7916 tests in 627.747s`,
  `FAILED (failures=1, errors=1, skipped=81)`. Both reproduce on unmodified
  `main` in this clone (`test_local_fit_optional_ci_311`, and a CPython 3.14
  `subprocess.communicate` `AttributeError` in
  `test_serve_log_574...test_desktop_command_opens_its_own_log`, proven by
  restoring the unmodified `tests/__init__.py` and rerunning that module).
- `ruff check harness tests scripts` clean; `harness repo-cards --check` up to
  date.

Filings: #656 landing evidence `7142456829`, gate receipt `7142482584`. #653
evidence and pass-23 receipts are unchanged from last pass. No
`docs/jev-roadmap.md` edit: the register carries #656 only in the open-set line,
with no per-issue row, and the landing does not change its state.

### WIP

Nothing in flight. No PR of this lane is open.

### NEXT

The next genuine, unblocked defect after #656: #654's UI badge is already under
PR #709 by another lane, #469/#475 stay blocked on champion replay inputs, and
item 5 stays blocked on this machine's missing keys. #660 is the nearest
candidate this lane has not worked, pending the same read of its body and
comments every item gets.

### BLOCKERS

- Item 5 live-brief leg: `load_settings()` resolves only `jev_api_key`;
  `api_key`, `openrouter_api_key`, `typesafe_api_key` are None on this machine.
- Item 5 champion replays: the home ledger holds 2892 `jev_eval` rows with no
  retry index, no attempt number, no breaker state and no 429 marker, and zero
  campaign `record_stop` rows.
- Item 6 (#655): PR #701 (`e280e20f`) is open and refs-only; #704 still has no
  PR.

### WAIT-STATE

`idle: none`. main `746e3621`; lane evidence pushed at the next SHA named in
this check-in's receipt comment.
