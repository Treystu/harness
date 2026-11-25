# Compare panel titles against the effective final scale

Part of #683, finding 30 (P2). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Current evidence

harness/answer_plot_consistency.py:384-397 compares each title against every `set_xscale`/`set_yscale` setter consistent with the state, not against the final effective scale, so an initialized-then-overridden axis is reported as a contradiction.

## The finding

**

If a script initializes an axis with `ax.set_xscale("linear")` and later switches it to `"log"` before display, a `"Log scale"` title is correct, but this loop reports the earlier linear setter as a contradiction. It compares the title against every setter rather than the final effective setting, so even an unconditional, statically resolvable initialization followed by an override can cause a correct answer to be withheld. Derive the final scale for each axis dimension and state before comparing it with the title.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/answer_plot_consistency.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/613#discussion_r4612926663
