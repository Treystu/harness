# Preserve branch conditions for argparse namespace attributes

Part of #683, finding 29 (P2). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Current evidence

harness/answer_plot_consistency.py:148 `_flag_of` resolves `ast.Name` and aliases only; an `ast.Attribute` such as `args.log` yields None, so both argparse branches collect with identical conditions.

## The finding

**

For the standard argparse pattern `args = parser.parse_args()` followed by `if args.log:`, `_flag_of` does not recognize the attribute expression, so both branches are collected with identical conditions. A correct toggle that sets a log scale and title in one branch and a linear scale and title in the other therefore produces contradictory `panel-title` findings in every checked state. This causes correct toggle answers to be revised and potentially withheld. Track namespace flag attributes, and do not treat mutually exclusive branches as simultaneously executed when their condition is unresolved.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `harness/answer_plot_consistency.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/613#discussion_r4612926649
