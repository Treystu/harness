## Correction + completion of the check states at `c4feb15a` (follows `7122501428`)

`7122501428` recorded the CI read at 04:55Z as `pending` (4 success / 11 pending) and the FreeBuff suite as `82 tests OK`. Both readings were true at that moment and both have since resolved. Neither was a green claim, and this is the completed picture.

**Head:** `c4feb15a404726fa689824dfb694b68b9a82f95c` on `laptop-vision-20261122` (code head `4b905cc9`; `c4feb15a` adds evidence only). Every register commit in `7122501428` remains an ancestor.

### 1. Full hermetic suite at this head - one pre-existing error, not from this diff

```
python -W error::ResourceWarning -m unittest discover -s tests
Ran 7858 tests in 539.134s
FAILED (errors=1, skipped=88)
```

The single error is `tests/test_serve_log_574.py::test_desktop_command_opens_its_own_log`:

```
File "harness/ui.py", line 65, in main -> harness/server.py:2709 make_server
  -> :1563 serve_identity -> :1541 _git_describe -> harness/osal.py:144 run
  -> subprocess.py:1221 communicate -> :1663 _communicate
AttributeError: '_Thread' object has no attribute 'is_alive'
```

It is **not this branch's work**:
- `git diff --stat 78ae71b9..HEAD -- harness/ tests/test_serve_log_574.py` is **empty** - neither the failing test nor any module in its traceback was touched by this pass.
- It fails the same way **standalone** (`Ran 13 tests ... FAILED (errors=1)`, 2.7 s), so it is not an ordering artifact of the vision tests.
- It fails **with and without** `-W error::ResourceWarning`, so it is not the warnings policy.
- Last commit touching that test: `a4dd345e` (#644).

So the suite is **red by one pre-existing error under Python 3.14**, and the FreeBuff surface this pass changed is green: `Ran 82 tests ... OK`, `ruff check scripts tests` clean, `compileall` clean, and the same ruff/compileall over the CI's own targets (`harness tests examples/oc_handoff driver_core`) pass (`ruff_exit=0`, `compile_exit=0`).

### 2. CI at this head - red, and I am not attributing it to code without evidence

Read 05:07Z-05:10Z:

| Head | State | Breakdown | Failing contexts |
| --- | --- | --- | --- |
| `c4feb15a` (this head) | `failure` | 8 success / 3 pending / 5 failure | hermetic (macos py3.11, ubuntu py3.11, ubuntu py3.13, windows py3.11), `test` |
| `4b905cc9` | `failure` | 8 success / 8 failure | the six hermetic legs, `test`, `audit` |
| `7d44f056` | `failure` | 8 success / 8 failure | the six hermetic legs, `test`, `audit` |
| `2591be98` (**docs only**) | `failure` | 8 success / 8 failure | the six hermetic legs, `test`, `audit` |
| `78ae71b9` | `success` | 16 / 16 | none |

The decisive comparison: **`2591be98` is a documentation-only commit and it fails the same eight contexts** as the code heads after it. A docs-only commit cannot break six hermetic legs on three operating systems, so the red at these heads is not explained by their content. That matches the two filings oversight already made on this same head series (`7122100267`, `7122107462`: red with zero executed steps), i.e. the executor/billing pattern rather than a test verdict.

**What I could not do:** this machine has no CircleCI CLI and no token, so I could not read the job logs or a failure report. I therefore **do not** claim the CI red is infrastructure - only that the evidence above shows it is not attributable to this pass's content, and that the content is green under the same commands the jobs run.

### 3. What that leaves

- Register: unchanged from `7122501428` - R1-R19 each on a commit reachable from this head; R7 and R10 built here; revert-proof 8 failures without / 45 OK with.
- Claim-and-execute: unchanged from `7122501428` - four claims, four executions, `send_freebuff: 0`, `type_freebuff: 0`, no sustained-turn verdict, and the withholding cause named (the exhaustive uniqueness walk exceeding the 240 s bound, not the desktop gate, which was open).
- Still open: the pre-existing `test_serve_log_574` error under Python 3.14 (a real defect, outside this pass's register and not caused here), the `navigate_by_unique_prefix` cost decision that is oversight's to make, and everything the pass scope excluded.
