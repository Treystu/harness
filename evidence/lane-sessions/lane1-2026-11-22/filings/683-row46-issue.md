# Check tracked fixture files rather than local directory existence

Part of #683, finding 46 (P2). Verified against `main`
`8fc28a0e` on 2026-11-25: still present.

## Current evidence

tests/test_local_fit_optional_ci_311.py:246 asserts that (ROOT/'audits'/'scmessenger'/'_runs').is_dir() is false; a legitimate gitignored local artifact directory therefore fails the default suite. Only the keep-file check (:247-248) tests tracked state.

## The finding

Check tracked fixture files rather than local directory existence

On a developer checkout containing the legitimate, gitignored `audits/scmessenger/_runs/` artifacts, this assertion fails the default test suite even though no fixture has been committed. The existing extraction tests explicitly support that directory being present (`tests/test_local_fit_extract.py`), so its presence is not an invalid repository state. I reproduced the failure by creating an empty `_runs` directory and running this test. Check whether fixture files are tracked, or retain only the ignore-rule assertion, instead of requiring developers to remove their local audit data.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `tests/test_local_fit_optional_ci_311.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/620#discussion_r4625632390
