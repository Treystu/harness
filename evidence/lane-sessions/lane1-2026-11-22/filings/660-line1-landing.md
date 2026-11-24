Line-by-line landing record for this issue. Both acceptance lines are now
built. The issue stays OPEN: closure is the operator's call, and this lane
takes no completion credit for a close it did not receive.

**DONE - line 1, the shared native result reviewer** (PR #665, merged as
`d6dec51f158a8064e8c198ae0a82a130c887eb4d` at head
`1a5ce93f545b9aab3db77f52f2447d9cb1699307`, 16/16 CircleCI at the exact head,
including `audit`).

Built as the design already filed on this issue, not invented here. The seat
mirrors `evaluate_file_triage` in `harness/jev_policy.py`: `evaluate_result_relevance`
preflights, asks one bounded noul per gathered result
(`result_relevance_question_pack`, `MAX_RESULT_REVIEW = 6`), and returns a typed
verdict per result. The bands are code-owned, not model prose: `>= 0.70`
`relevant`, `<= 0.30` `rejected`, else `uncertain`. Each admitted or excluded
result carries its verdict, probability and reason, and a structural receipt is
recorded once per run.

`harness/web.py`'s `apply_result_review` is the one admission point. Both
retrieval paths reach it through the single `_gather_web_context` call in
`harness/conversation_lifecycle.py`, which `harness/hourglass_lifecycle.py`
forwards into with the same policy, so a per-call filter cannot reappear on one
lane and not the other. Rejected and uncertain results are **excluded** from the
evidence handed to the answer model, not down-ranked - the verdict also rides on
the source dict so the run record and the checkpoint copy keep it.

**The outage rule, as ruled** (oversight decision `7078539288`, fail closed).
When the reviewer cannot answer at all - evaluator refusal, budget refusal,
provider spend limit, cancel, lost usage, or a reviewer that raises - every
result is reported `unreviewed`, excluded from the evidence, and the outage is
disclosed in the run record and in both evidence blocks. No item is ever
admitted under a label that says it was not reviewed.

**The unkeyed case, honestly bounded.** With no model key installed there is no
reviewer to be down, so the run admits and records an admitted verdict whose
reason names the method (query match plus the gather-time URL gates) instead of
claiming a review that did not happen. A term-overlap relevance heuristic was
implemented first and **rejected**: it dropped a legitimate search hit in
`tests/test_agent.py::test_refusal_caveat_inside_successful_web_turn_stays_ok`,
because a term count cannot re-judge the search engine's own match. The pack
function still exposes `heuristic_result_relevance` for that recorded-label path;
it never rejects.

A page the request itself named is admitted by naming, tagged `pinned` at the
prompt-URL fetch, and records `relevant` with reason "named by the request" - the
request is the relevance evidence for it.

Acceptance for line 1, from the filing:

- a typed verdict with its reason for every admitted result -
  `test_every_result_carries_a_typed_verdict_with_its_reason`.
- rejected results absent from the evidence -
  `test_rejected_and_uncertain_results_are_absent_from_the_evidence`.
- uncertain excluded rather than admitted - the same test, plus
  `test_a_missing_answer_is_uncertain_not_admission` and
  `test_bands_are_typed_on_the_probability`.
- one reviewer in the same seat for every retrieval path -
  `test_one_shared_point_admits_for_both_retrieval_paths`.
- the fail-closed outage, disclosed - `test_a_reviewer_refusal_is_an_outage_not_an_admission`,
  `test_a_budget_refusal_is_recorded_and_fails_closed`,
  `test_a_provider_spend_limit_is_an_outage_not_an_exception`,
  `test_a_reviewer_outage_withholds_everything_and_discloses_it`,
  `test_the_hourglass_evidence_block_discloses_a_reviewer_outage`,
  `test_the_conversation_evidence_block_discloses_a_reviewer_outage`.

Verification at that head: the reviewer file plus its ten neighbours -> 264
passed; `ruff check` over the CI scope -> clean; `compileall` -> clean; full
`pytest tests` -> 7549 passed, 82 skipped, with two environment-only files
excluded (a CPython 3.12 subprocess-thread failure in `test_serve_log_574` and an
untracked `audits/scmessenger/_runs` directory seen by
`test_local_fit_optional_ci_311`; neither is in the diff and both legs are green
in CI). The audit/D12 bar was measured with the audit's own statement rule
against a full-suite trace: 131 changed executable `harness/` statements, 131
executed (100%, bar 95%). The earlier head `88b3d2c` was red on `audit` for
exactly that reason - its thinner test set left the failure branches unexecuted -
and the third commit added the 24-test file that covers them.

Line 2, already recorded above, still holds at this head: the snippet-versus-
rendered labels, the legend, and the `#343` mixed-target and final-URL subject
gate tests in `tests/test_web.py` pass unchanged.

Register: PR #665 carried code only. The `docs/jev-roadmap.md` #660 row was
updated in a follow-up PR (#666, head `16a92df`, 16/16 CircleCI at that exact
head, merged as `f4b2109922da6adc615ced558ef68d145cb2a2ef`): it names the line-1
merge SHA and keeps the row's live state OPEN with the census at 40 unchanged.
