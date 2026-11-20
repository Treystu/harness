Sergeant checkpoint - DONE / WIP / NEXT / BLOCKERS + SHAs (2026-11-19, increment 4: #475 scoped from live code; #635 parked by fence)

Acks - nothing new. Between my own last comment (7008788342, 12:14:36Z) and this status there is **no new oversight comment, no lane status, no review, and no STOP** on #295: the thread was read again at turn start, and again after each of this turn's four filings (466 at 7008883247, 475 at 7008874997, 635 at 7008883838). Nothing was left unacked from the previous window either - W1's `…obpErQ` and W2's `…ocApTw` were both acked at 7008772295 / 7008788342.

BASELINE RE-PROVED LIVE (no cached readings):
- main is 17906e2c13295c4fac66b7870ca1220d9b23d289 - unchanged from the locked baseline, moved by nobody this turn.
- Five train PRs still MERGED: #619 a7ca742e, #620 8187bc3c, #621 53dbc72f, #623 7acd2df3, #622 dbb54a7f. Plus my later cars: #632 d2e724ba, #631 42d43f3f, #627 17906e2c.
- Rails read context-by-context at exact heads this turn (CircleCI only):

| PR | Head | CircleCI at that head | GitHub state |
|---|---|---|---|
| #624 | 966de1dd | **14/15 - red on `ci/circleci: ui-playwright-smoke`** | MERGEABLE / BEHIND, ready |
| #625 | 7bc45715 | 15/15 | CONFLICTING / DIRTY |
| #626 | cc192ddf | 16/16 | MERGEABLE / BEHIND |
| #627 | ec664518 | 16/16 incl audit | MERGED (17906e2c) |
| #628 | 7cf5ef8d | 15/15 | **CONFLICTING / DIRTY**, draft |
| #630 | 0c591c87 | 15/15 | MERGEABLE / BEHIND, draft |
| #633 | eb509014 | 16/16 | MERGEABLE / UNSTABLE, draft |
| #634 | f816deb5 | 7/15 with 8 pending (my own evidence branch push; not claimed green) | MERGEABLE / BEHIND, draft |
| #635 | b37db05d | **16/16 incl audit, 0 failures** | MERGEABLE / BEHIND, ready |

DONE - THE SINGLE INCREMENT: **persistence queue item 4 (#475) now carries a code-grounded scoped spec**, filed as 7008874997 on the carrier and indexed in the queue table on #466 as 7008883247.

It is built from the code at `17906e2c`, with file:symbol:line for every claim: `harness/events.py::emit`:223, `harness/panel.py::_run_panel_slot`:343 with its 429 loop 353-410 and backoff 408-410, `harness/jev.py`:707/754 `model_request_start`/`request_end` and `CircuitBreakers`:453 with `acquire`:463 and `record`:492, `harness/chat.py`:1018-1028 with `note_reasoning_param_rejection`:292, and the writer it must target, `harness/decision_trace.py::DecisionTrace.record`:112 with `read_trace_events`:190.

The finding is sharper than the brief's wording and that is why the spec earns its place: **the values #475 says are missing are already computed and then thrown away.** `emit`:223 returns immediately when no sink is registered - the default CLI path - so Jev's accurate `http_status`/`duration_s`, panel's `http_status` on rotation, and chat's param-rejection notice exist only for a process that installed a sink and never survive the process; `CircuitBreakers` state is in-memory, so a restart erases the evidence a site was breaking. The spec's first acceptance condition is therefore sink-independence (no sink, scripted `429,429,200`, durable rows must carry `[429,429,200]` - a condition that fails today by construction), with seven more falsifiable ones: one-row-per-attempt, status fidelity, timing sanity, byte-identical behaviour without the path, silence on refusals, reader-side ladder reconstruction, and breaker reconstruction after restart. Gates: product Jev investigate/proceed then Lucas Gate v2 pass (`gates-475spec.json`).

#635 - THE INTENDED CAR - WAS TESTED AND PARKED BY FENCE, not merged. Verified at b37db05d: 16/16 incl audit, ready, MERGEABLE, one-file diff, body+diff close-scan 0 hits, content exactly as claimed. It is BEHIND main 17906e2c and strict protection refused verbatim: "the head branch is not up to date with the base branch". I did not use `--auto`, did not use `--admin`, and did not update a branch that is W2's to update. Disposition recorded on the PR itself (7008883838) with the unblocker named.

WIP - nothing in flight; no background process, no port held. Evidence pushed to sergeant/evidence-2026-11-19.

CENSUS - two ways at main 17906e2c:
- List API: **41 open**.
- Roadmap inventory: register section **44** issue rows. register-not-open = {311, 407, 419} - the three closed train rows kept as landed history; open-not-register = {} empty. Same 41, each exactly once, none missing. Non-issue rows counted separately (#295 tracker, SELF-IMPROVE, CANON-1 subsection).
- Delta: none. This turn closed no issue - the increment was a spec filing, which takes no completion credit by design - so 41 is the expected number, unchanged by construction.

NEXT (pull order, each with its unblocker stated):
1. **#635** - needs only a W2 branch update onto 17906e2c plus a fresh rail; then I land it with Jev-first/Lucas-second and a receipt. It is the closest thing to a landable car in the repo.
2. **#624** - red at 966de1dd on `ui-playwright-smoke`; W1 cure at that context, never below 15/15.
3. **#626** - W2 rebase onto 17906e2c.
4. **#628** - now CONFLICTING/DIRTY after its base merged; W1 branch update, and it is the #468 unblocker.
5. **#630**, **#633** - W1 branch updates; #633 also owes the #472 spec-conformance increment.
6. Queue item 5 (**#473**, router health + ordering at each rotation) is the next spec to write, in the #472/#475 shape.

BLOCKERS (each parked alone on #295/#466, unblocker named, queue proceeding):
- #635 - BEHIND 17906e2c; unblocker: W2 branch update.
- #624 - red on `ui-playwright-smoke`; unblocker: W1 cure.
- #626 - BEHIND; unblocker: W2 rebase.
- #625 - CONFLICTING/DIRTY; unblocker: W3 branch update.
- #628, #630, #633 - branch updates (W1); #633 additionally the spec increment.
- W468/W469 - now runnable (the persistence write landed with #627); unblocker is lane scheduling, not code.
- #415 paid route - OpenRouter account credit; #412 steps 4-7 - owner window; #422 - product wiring decision.

SHAs: main 17906e2c13295c4fac66b7870ca1220d9b23d289; train #619 a7ca742e, #620 8187bc3c, #621 53dbc72f, #623 7acd2df3, #622 dbb54a7f; #632 d2e724ba, #631 42d43f3f, #627 17906e2c (all MERGED by me); #635 b37db05d; #634 f816deb5 (draft); #633 eb509014 (draft); #630 0c591c87 (draft); #628 7cf5ef8d (draft); #626 cc192ddf; #625 7bc45715; #624 966de1dd (red: ui-playwright-smoke).
