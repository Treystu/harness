## CHECK-IN pass-19 — Lane 1 (genuine-issue burn, order items 1, 3, 4 done; item 2 confirmed)

Lane 1 resumed and moved: three of the four already-confirmed priority items are landed on `main` with the full 16/16 CircleCI rail green at each landing head, and the item-2 confirmation act is filed. No edit was made to `laptop-vision-20261122` (PR #685); that branch still has one editor, the standup lane.

**DONE**

- **#705 - live infinite recursion (order item 1).** PR #708, head `84882777`, rail n=16 ok=16 pend=0 bad=. Squash-merged as **`e2494696`**. The cure bounds the conversation/plan-lane handoffs at one shared per-request budget (`_HANDLER_HANDOFF_LIMIT = 3`) and re-injects the sibling guards (`allow_escalation=False, persist=False`) on `_refused_edit`'s conversation re-entry (`harness/execution_stages.py`, `harness/conversation_lifecycle.py`, `harness/hourglass_lifecycle.py`, `harness/edit_lifecycle.py`). `tests/test_handler_handoff_705.py` carries 6 tests; 4 of the 5 original cases fail on the pre-cure tree.
- **#706 - markdown renderer corrupting `**` inside code blocks (order item 3).** PR #710, head `e7923753` (merge of `main`), rail n=16 ok=16. Squash-merged as **`add52b70`**. `renderSimpleMarkdown` now holds code segments as tokens across inline-marker replacement (`harness/ui/app.js`); `tests/ui_markdown_code.test.cjs` and `tests/test_ui_markdown_code.py` fail on the pre-cure tree by producing `a = 2 <strong> 3`.
- **#707 - edit scope ignored the pasted path (order item 4).** PR #711, head `b8a6477d`, rail **n=16 ok=16 pend=0 bad=**. Squash-merged as **`7233fbbc`**. Scope precedence is now local-only: the pasted absolute path the prompt names (`pasted_absolute_path`, new in `harness/repo_scope.py`), then workspace discovery, then a prior plan's `target_files`, with the prompt's full triage left in its old position so no model call was added ahead of the common path. `tests/test_edit_scope_707.py` (4 tests) reproduces the recorded session and fails on the pre-cure tree.
- **The `audit` context's cause, measured.** At `a2a12f1d` every CircleCI context was green except `ci/circleci: audit`. Reproduced with D12's own rule at that head: the diff added 15 executable statement lines and the refusal guard in `pasted_absolute_path` (the loop's `continue`) was never reached - the URL case never matches the pattern at all - so D12 measured 14/15 = 93% against its 95% bar. `b8a6477d` asserts the refusal case, a trace of the four tests executes all 15 added statement lines, and the audit context turned green on the same head with no other change. Not a retry: the number moved because the line was executed.
- **#685 rail regression named (order item 2).** Filed on #684 (7128456963) and here (7128457544). Four deterministic failures reproduced at the exact head `3a3ce6db` under CI's own command (`Ran 7880 tests`, `FAILED (errors=5, skipped=89)`), root cause `1391be24` (`require_driver_runtime()` added to `run_burn`, `poll_dynamic_dispatches`, `run_restoration` without updating the tests that drive them, and its own new test asserting a runtime a Linux runner cannot have). Main relevance: the gate is branch-only code bound for `main`; `main` is not red for it. No CircleCI token in this lane, so those are reproductions, not log quotes - the gap is stated, not hidden.

**WIP**

- Order item 5, STEP 0: the two-independent-counts trace-persistence verification (in-memory trace count versus the ledger's `decision_trace` entries on one live brief run), to be filed on #466, then the champion-set closure (#475, #469). In progress; no result claimed yet.

**NEXT**

- Item 5 as above, then item 6 (#655 loopback port split), then item 7 (#342, #344), then item 8 (remove the root scratch files `_append_tests.py`, `_fix_imp.py`, `_imp2.py`, `_pt.py` from `main`).

**BLOCKERS**

- Item 6's stated sequence is "after #701/#704 land". #701 is open (`e280e20f`); there is no PR #704 in the repository, so the second half of that condition cannot be satisfied as written. Item 6 stays behind #701 until that is resolved.
- #342 and #344 are uncured feature gaps, not resource waits, and this filing states them from their own bodies rather than from memory: #342 has `evaluate_research_plan` / `evaluate_research_results` defined with no production caller and no `ResearchPlan` type at all; #344 reproduces old web evidence delivered on a changed prompt with zero route reviews and zero context rebuilds. Neither is blocked on a key or on another lane - both wait only on their own fix, which is order item 7.

**WAIT-STATE:** idle: none.

**GATE RECEIPT.** Lucas Gate v2 typed track: **pass**, artifact sha256 `b6241cc32d241fb0803a80c50b4b849c77f7f56c4a4a29424619ed223ea8f932` (`evidence/lane-sessions/lane1-2026-11-22/filings/receipt-295-pass19.json`). Product Jev: label **investigate**, disposition **proceed** (supported 0.08, margin 0.20, model jev-1.14.0). The investigate label is discharged against primary sources in this filing: the two blocker rows were re-read from the issues themselves (#342's own body, #344's two reproduced cases) and the earlier shorthand that #342 waits on a key was corrected above; "no PR #704" is a live API read, not an assumption (#704 resolves to no pull request). The gate ran on the text above it; this paragraph and that one correction are the only additions after it.

Refs #705, #706, #707, #685, #466.
