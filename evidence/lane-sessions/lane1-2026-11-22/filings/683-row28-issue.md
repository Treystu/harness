# Resolve bar positions before reporting a tick-unit mismatch

Part of #683, finding 28 (P2). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Current evidence

harness/answer_plot_consistency.py:219 and :299 append every named bar-position argument to `plain_bar_positions` without resolving its value; finding (3) at :419 reports a tick-unit mismatch whenever power ticks exist.

## The finding

**

For a valid script using `xs = [10 ** k for k in range(3)]`, `ax.bar(xs, heights)`, and matching power-of-ten ticks, this check reports that `xs` does not contain powers of ten. `_record_call` adds every named bar-position argument to `plain_bar_positions` without inspecting its value, so the finding is unsupported even when positions and ticks match exactly. The lifecycle consequently spends a revision and withholds a correct script if the generator preserves those positions. Resolve the position values and associate them with the relevant axes before asserting a mismatch.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/answer_plot_consistency.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/613#discussion_r4612926629
