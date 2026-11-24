RESTART DISPATCH - Harness Audit Lane boundary restart, iteration 2 on the cured walk (thread 918dad1a)

Lane: Harness Audit Lane (thread 918dad1a, LOCAL, project Harness).
Pinned route: 918dad1a (identity read by the driver's own gates this run).

Action for the runner: one in-place restart of this lane with exactly "continue in full" - no duplicate session, no model or settings change, no other text.

Why iteration 2 exists: dispatch 7127392966 was claimed, walked and parked with "the project session list does not hold 'Harness Audit Lane'". That was a driver defect, not a lane problem, and it is now cured at commit f946e206:

- the sidebar holds one "Show more" per project section, so the first page carried two and the single-row click raised "'Show more' matched 2 settled rows", ending the whole walk above this lane's heading. Every section control is now expanded in turn, coordinate-bound, the target project's section first;
- the prefix walk parked on "the field holds text this query did not write ('Kalshi Paper Burndow')" - a one-glyph OCR slip on its own query. The readback now tolerates that slip and still refuses genuinely foreign text;
- the route walk censused this lane's exact title under its own project heading and skipped it. An exact title under this lane's project heading is now the pick.

Tests: tests/test_session_walk_expand.py, seven tests, five of which fail on the pre-cure tree. 112 freebuff tests OK, ruff clean at f946e206.

Bounds unchanged: the 240 s phase bound, the narrowed walk behind its operator flag, the bounded bystander probe, worker-isolated capture, one send, and the freshness read immediately before input. At most once ever, and this iteration is that once for the cured walk. A start cue is not a verdict: RUNNING needs this lane's own new activity minutes later, otherwise the negative is filed with the trace.
