PRIMARY TAKEOVER - audit context cured at b6d33b5 (2026-11-15)

Took this PR over per the oversight comment. Two defects were on it, and both are cured at cause.

**1. `ci/circleci: audit` RED at 7939910 - cause found, not guessed.**
The failing row is `sd_contributing` (D10). It fails when a public `harness/*.py` module has no ownership row in `CONTRIBUTING.md`, and this branch adds `harness/availability.py` without one. Reproduced on the exact tree:

```
sd_contributing at 7939910 -> uncovered: ['availability']
```

The assist lane had the row written but left it **uncommitted in its worktree** - the fix lived only on that disk, never on the branch, so CI could never see it. That edit is now preserved (its own commit, `976e0a6`) and the row is in the branch. Same row re-run on the merged head:

```
sd_contributing -> (1.0, 'CONTRIBUTING covers every public module; layering rules present')
```

**2. The PR was `CONFLICTING` with main.** `#545` (`9959b16`) changed `_refusal_reason` in `harness/conversation_lifecycle.py` while this branch carried its own second implementation of the same #543 cure (a structural `_answer_is_substantive` test). Two implementations of one rule cannot both land. Resolved to main's merged semantics - the `_REFUSAL_SUBSTANCE_WORDS` floor - and the branch's duplicate helper removed, because #543 is already closed by #545 and a second owner for the same classification is exactly the drift the structural row (S7) exists to prevent. Merge commit `b6d33b5`; the branch's remaining diff against main is the #538-#542/#544 work only.

**Bundle review against the acceptance blocks** (primary-side diff read, D-2026-11-13-012 item 4): each issue's acceptance is backed by an executable test, not by a claim -

- #538 failover: `test_provider_spend_limit_walks_the_whole_ladder_before_stopping`, `test_provider_exhaustion_is_rotatable_not_terminal`, `test_only_the_run_budget_cap_is_terminal`.
- #539 selection: `test_funding_blocks_paid_models_but_not_free_ones`, `test_restriction_blocks_only_the_named_model`, `test_verdicts_persist_across_runs`, `test_probe_budget_is_bounded_and_cost_recorded`, `test_live_backends_names_what_is_selectable`.
- #540 ordinary-answer ordering: `test_free_route_answers_while_the_paid_head_is_dry`, `test_answer_rotates_and_records_the_refused_pair`.
- #541 decomposition repair: `test_malformed_decomposition_is_salvaged_without_a_second_call`, `test_repair_cost_is_strictly_less_than_a_full_second_call`, `test_unparseable_decomposition_falls_back_loudly_with_evidence`, `test_fail_closed_preview_still_carries_the_raw_output`.
- #542 research detour: `test_the_2026_11_14_artifact_request_is_not_a_research_request`, `test_a_genuine_lookup_still_researches`, `test_zero_char_named_source_aborts_the_detour_before_searching`.
- #543: closed by #545; this branch no longer carries a second implementation.
- #544 workspace gate: `test_no_file_scope_request_answers_without_a_workspace`, `test_file_write_without_a_workspace_stops_at_the_operation`, `test_preview_gate_message_is_unchanged`.

**Vehicle for #541: this PR.** #546 duplicates the #541 portion with the same audit defect and a narrower diff; it is closed with a pointer here rather than iterated.

**Rail is the only evidence.** Structural, doc and layering rows were re-read on the merged head (D10, D7, S1, S2, S3, S4, S5, S6 all 1.0) and D12's changed-line measurement is running; merge waits on the CircleCI rail green at the exact head, per the standing rule. No merge on red.

Gate note: Lucas Gate v2 on these words. Jev canonical key check: NOT CHECKED this pass (no live jev-decide probe run in this seat).
