TRIAGE PASS - 83 open issues (owner steering 2026-11-02, item 1) - 2026-11-03

Scope: every open issue read from the live API (83 at 2026-11-03T03:2xZ), evidence checked against main 0780ea74 and lane/burndown c9fdbbc3 (44 lane-only commits, 20+ merged PRs on main since 2026-10-20). No bulk closes: one close this pass, each with its landing SHA; every other class is recorded below with the reason it is not closed.

RESULT: 1 closed / 11 converted / 7 parked / 3 waiting on PR #444 / 61 live. Open count 83 -> 82.

CLOSED (acceptance verified on main)
- #421 consent rotation events. Fixed by 4263c6b (harness/consent.py, tests/test_issue421_rotation_events.py, docs/issue-plans/421.md) + 2959590 (edge paths), merged by PR #437 -> main 0780ea7. Acceptance is asserted in tests/test_issue421_rotation_events.py: one rotation event and one consent_rotate row per unusable candidate, zero for a parsed decision. Closing comment posted on the issue.

CONVERTED (work exists as a named ref; not closed until merged) - 11
Lane/burndown, blocked on the red-head cure (landings cannot proceed on a red head or red base):
- #325 c86b46e (+ d516c1a, 972de55, 1f4afd0, 0aaad81, fe6cc36, a6b0729, c90d9f2) - harness/jev_assessment.py, CLI, tests
- #423 9b68ae5 (+ e27c8e5, 17ca615, 6103d79, c656344, 0c099a7) - harness/source_audit.py
- #427 95db94d, 0335587, 7a234f0 - mission/repo_summary fail-closed
- #429 a43b8a0 - judgment tail recovery
- #433 e6812f9 - harness/lucas_gate.py + lucas_gate_v2 MCP tool
- #438 b208737, 01b1bbd, 83bc010 - headless key provisioning
- #439 a241176, c7e2367, 266f186, bdadb77, c9fdbbc3, 988a141 - read-only run_probe
- #440 4422355, 7cf2e9d, 7d4118b, 7bec5a3 - scripts/driving_hygiene.py
- #443 959f0a9 - py3.14 hermetic matrix
Preserved on their own pushed branches (not main, not lane, awaiting a landing slice):
- #425 freebuff/425-audit-chain-integrity-20261029 (5447bf7)
- #426 freebuff/426-public-egress-20261029 (0530970)

PARKED / RESERVED (explicit hold; not stale) - 7
- #306 Fireworks key ops and #304 Fireworks routing (depends on #306): owner key act; canon parks both.
- #407 visibility-site deploy: owner deploy.
- #424 System One doc claims: parked by ORDER OF OPERATIONS step 6.
- #432 voice proposal: the deferral decision is the owner's.
- #294 provider-onboarding completion: owner-gated Jev >= 0.90 plus the router flag.
- #295 this tracker.

WAITING ON PR #444 (owner merge blocked by branch protection) - 3
- #377, #378, #379. #447 is the follow-on defect filed from that landing pass and stays live.

LIVE - 61 kept
The fast-track wave (#270, #272, #273; #271 deferred by steering; #292, #300), the v4 batches (#275, #277, #280-#286, #289, #291), the Oct 27-28 audit findings not yet implemented (#412-#420, #422, #428, #430, #434), the settled-debt pair (#445, #446), and the low-priority tracking items (#380-#382). Rule applied: no evidence of settlement on any ref -> keep, in recorded order.

Rule per class: CLOSE = acceptance verified on main at a named SHA; CONVERT = acceptance not on main but a named ref carries it (closed only when merged); PARK = a governing comment names the hold; WAIT = blocked on an open PR's merge; KEEP = live work with no settlement evidence.

Gate: Lucas Gate v2 never-rule check on this text: clean - one issue closed with a verified landing SHA, no merge, no destructive action. Jev decision gate (jev-latest): NOT RUN, authentication blocker recorded in the 2026-11-03 lane status on PR #442; no Jev pass is claimed.
