STANDUP RECEIPT - boundary restart SENDS end to end and holds RUNNING; Lane 1 draft still pending

Census first. Desktop FreeBuff (PID 6652, hwnd 1180834) was live and served every capture. SCMessenger (2ae32937, DeepSeek V4.1 Flash Slow, Local) was paused at its hour limit when this pass began - a real turn boundary. Lane 1 (315608d2) was not mid-turn. No lane was acted on while mid-turn: the only send below went to SCMessenger after its boundary was verified, and Lane 1 received no input at all.

## The send-route refusal, its cause, and the cure

The frontier was exactly as the last result recorded: prepare proved the lane, typed once, and the send refused with "the active FreeBuff document did not expose the exact pinned thread".

Cause, measured twice rather than inferred:

1. `verify_active_session` required exactly one exposed accessibility route. The helper returns `[]` on this handle - re-measured live this pass on the same window - which is the dead tree `routes()` already documents. A proof that is usually absent cannot be the only identity a send may stand on. Cure `6c3ba7dc`: the route stays primary, the settled exact-selection for the pinned label in its pinned project becomes the fallback, and `route_fallback` plus the pinned UUID are recorded.
2. The next run then refused from a different branch, "the exact pinned session route is required for this standing dispatch". The archived send frame shows why: at send time this app draws the selection as a 1 px outline (104 on a 237 background) with the row's interior equal to the background, so the fill-based band probe that proved the lane during prepare cannot see it. An outline detector was prototyped against that frame and **discarded**, because the sidebar draws a vertical guide line through every row and the prototype matched every row - a detector that marks everything selected is worse than none. Cure `d1d8ee4e`: the proofs are ordered and recorded by source - exposed route, then settled exact-selection, then, at send only, the approved continuation this lane already holds, which is exact for this app because drafts are kept per session and is the rule the code already trusted for a non-standing send. `verify_session_identity`'s SCMessenger branch and its Lane 1 branch use the same proof, so a standing lane cannot be blocked by a ring it cannot see.

Non-standing sends still require the route. Freshness, one send, no navigation and the unchanged-composer-pixels bound are untouched. Tests: `tests/test_freebuff_send_route.py`, eight tests including three that fail without the second cure; 112 freebuff tests pass, ruff clean, compileall exit 0 at `d1d8ee4e`.

The stored continuation was reconciled by **adoption, not retyping**: iteration 4's authorised prepare had left exactly `continue in full` in the composer, prepare recorded it as staged, and the send run shows `type_freebuff` **zero** times. The lane received exactly one continuation, once.

## One boundary-restart dispatch SENT end to end

Dispatch `7126585210` (iteration 6), ack `7126596959`, result `7126717228` at 08:54:43Z - **verified running**. Receipt: `trace-7126585210/`.

- identity: `active-session-id` with `route_fallback: exact-scoped-selection`, `pinned_uuid: 2ae32937-c991-4c33-87d4-68b8c956ba98`, thread 2ae32937
- freshness: `pre-send-freshness` age 16.856 s
- actions: `query_freebuff 1`, `scroll_freebuff 4`, `click_freebuff 9`, `type_freebuff 0`, `send_freebuff 1` with `ok: true`, step `send-once`
- runner verdict: `verified running`

## Sustained-turn standard, not a cold green

- corroboration 1, 08:56:40Z: `Working for 2m 35s` in view (`trace-7126585210/corroborate-1-085640.png`)
- corroboration 2, 08:58:07Z: `Working for 4m 02s` in view (`corroborate-2-085807.png`) - the timer advanced 87 s against 87 s of wall clock
- lane-side: `Sovereign-Communication/SCMessenger` `pushed_at` moved to **2026-11-24T08:54:26Z**, the minute of the send, from 05:42:42Z when the owner's dispatch was filed

Verdict: **RUNNING, double-proven** - still working in view across two reads minutes apart, with lane-side GitHub activity at the send minute. Not a start cue.

## Lane 1 - owner draft still there, recorded pending, nothing typed

Manual read first, and it is filed as what it was: the Lane 1 row was scrolled out of the sidebar; after a visibility-only reveal the row click landed on a view showing the new-chat greeting, which is not the Lane 1 session, so it established nothing. No input was typed in that view, no session was created, no model or settings changed. That view also reported a Stop cue on a greeting screen, so the stop detector is not trusted there (census row for the worklist).

The authoritative read came from the driver's own gate. Dispatch `7126889770` (ack `7126931327`) claimed, walked, selected, and prepare refused (`7126962272`, 09:06:14Z):

```
composer-route: the composer holds a foreign draft, not 'continue in full'; not typing over it
('ownermodulewithanownertest1...')
```

So the owner's draft is **still present**; nothing was typed over it and nothing was sent to Lane 1. Its restart stays the owner's decision.

## Launch cold run - NOT-RUN

Desktop FreeBuff was live for the whole pass and a verified turn (SCMessenger) was working during it. A cold launch would stand up a second window and risk a duplicate session while that turn runs, which the census rule forbids. Filed not-run with that reason rather than manufacturing a green.

## Checks and CI as GitHub reports it

At branch head `bc54e696` (code head `d1d8ee4e`): 112 freebuff tests OK, `ruff check scripts tests` clean, `compileall` exit 0. CircleCI: read per context on the exact head and reported as pending until it lands; GitHub Actions is red in seconds on every job, which is the known billing lock, not a code verdict. PR #685 stays OPEN and unmerged; #701 and #702 untouched.

## Gate receipts

- `gates-send-route.py` -> `gates-send-route.json`: product Jev ESCALATE / disposition proceed, advances 0.84, destructive 0.12, lead 0.18, investigated with no actual risk found (one bounded send at a verified boundary); Lucas Gate v2 **pass**, artifact `fcb3e647d9a7cf07`.
- `gates-sustained-send.py` -> `gates-sustained-send.json`: product Jev investigate / proceed, advances 0.89, destructive 0.06, confidence 0.58; Lucas Gate v2 **pass**, artifact `379adac53d39f72b`.

## Operator state left set

`narrow-walk.flag` remains ON under `%LOCALAPPDATA%\harness-freebuff-runner\` (the operator switch that lets the SCMessenger walk finish inside its bound). The driver watch is idle at the end of the pass, port 8765 answers, Desktop FreeBuff is up and serving.

## Open

1. Lane 1 restart: the owner's draft is still in the composer; the decision is the owner's (send, clear, or authorise an overwrite).
2. Launch cold run: needs a window with no live desktop turn.
3. One stray blank chat view is open in the app from the inconclusive manual Lane 1 read; nothing was typed in it and it holds no session.
4. Desktop restart and the fleet fill remain outside this pass.
