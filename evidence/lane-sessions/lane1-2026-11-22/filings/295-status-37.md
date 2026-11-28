# Lane 1 check-in - status 37: watch execution state, measured

This filing reports what the watch actually did and what it could not do. It
closes nothing and takes no completion credit. It supersedes nothing; status 36
reported the watch's status file, and this one reports its dispatch behaviour.

## DONE

- The watch process is alive and ticking. Status file read at `20:18:32Z`:
  `state: idle_watching`, `enabled: true`, `paused: false`, `head_sha
  08ce64fe`, `pid 10924`, `last_run 2026-11-25T20:18:32Z`, `exit_code 0`,
  `last_error` empty. The log shows ticks at `20:12:33Z`, `20:14:32Z`,
  `20:16:35Z` and `20:18:32Z`, each `tick ok sha=08ce64fe state=active`. The
  pid differs from the earlier read (`24796`), so the supervisor has respawned
  the watcher at least once; the respawn came back healthy.
- The claim scan is live, not blind. Its own heartbeat on #684
  (`7173429655`, `20:16:34Z`) reports: "scan saw 504 owner comment(s) through
  `#7173337507`; 34 dispatch-shaped; 0 claimable". The first heartbeat in this
  session with a cursor is `7173337507` at `20:12:33Z`, which reports the same
  34-and-0 counts against a smaller scan, so the cursor is advancing and the
  verdict is stable across two scans rather than a one-off empty read.
- **0 claimable is the correct answer here, not a stall.** The dispatches the
  scan lists are all either past the 24-hour TTL or already claimed; the newest
  restart for this lane was claimed at `20:10:38Z`, which is what drove that
  tick. A watch with nothing new to claim should claim nothing, and this one
  does exactly that with the counts to prove it.

## WIP - the one thing that did go wrong, and why

The `20:10:34Z` result on #684 (`7173292215`) shows the last delivery attempt
reached the desktop and parked:

```
parked: prepare: BLOCKED: composer-route: the composer holds a foreign draft,
not 'continue in full'; not typing over it
('continuetheauditmissionfilethep5testintegritycheckpointforloop8atthecurrenttipwithfreshreadstab')
```

The same park appears twice more in the log for different drafts
(`standupbranchandgive...`, `burndownbyverifying43and44...`). The mechanism is
worth stating plainly, because it is the difference between a lane that is
broken and a lane that is correctly holding still:

- Dispatch delivery types into the desktop app's composer. The composer
  currently holds a draft that belongs to another lane's work, not the dispatch
  instruction.
- The watch refuses to overwrite a foreign draft. That refusal is the correct
  behaviour; typing over someone's in-progress text would destroy it.
- So delivery parks instead of typing, and the dispatch is not executed. That
  is a desktop-state blocker, not a defect in the claim loop, and the lane
  cannot clear it from code without doing the thing the guard exists to
  prevent.

Clearing it needs one human action: empty or copy out the draft sitting in the
composer. Until then, every delivery for this lane parks at `prepare`, and the
heartbeat will keep truthfully reporting `state=active` on a queue it cannot
deliver into.

## NEXT

1. The queue behind the tracker: #649, #650, #651, #652, then #703.
2. Read PR #724's rail one context at a time on its current head until green or
   red. At `fbb004b8` the read was 8 success, 8 pending, none red.

## BLOCKERS

- The composer park above. It is the one blocker that stops dispatch execution,
  and it is outside what this lane may change itself.
- CircleCI queue depth: contexts sit pending for tens of minutes, and every
  evidence commit moves the head, so a green read always trails the newest
  evidence by one run.
- GitHub Actions `ci` completes every job with zero steps in one to three
  seconds. That is a runner-start condition, so it is not read as a test result
  in either direction.

## Not claimed

- Not claimed: that the watch will claim the next dispatch. It will, when one
  becomes claimable and the composer is free; neither is true at this read.
- Not claimed: that the parked dispatches are lost. They remain on #684; they
  are simply undelivered.
- Not claimed: any causation between the watcher respawn and the parks. The
  respawn is observed; the parks are observed; nothing here links them.

## DIRECTIVES

No new directive from oversight was found on #295 or #684 at this read. The
execute-once guarantee, the 60-second freshness re-read and the episode-state
check are unchanged and were not bypassed to get dispatch approval.
