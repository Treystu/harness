RESTART DISPATCH - CivicScope boundary restart, iteration 2 on the cured driver (thread 46472fcc)

Lane: CivicScope (thread 46472fcc, LOCAL, project civicscope(cloud)).
Pinned route: 46472fcc (pinned in the codebase; identity proven again in this run).

Action for the runner: one in-place restart of this lane with exactly "continue in full" - no duplicate session, no model or settings change, no other text.

Why iteration 2 exists: dispatch 7127711668 was claimed and parked on a driver defect, not on anything about this lane. Three cures have landed since, each with a test that fails without it:

- 503be9f4, the "bystander" cure: the pre-run witness required Lane 1's row to be visible in the sidebar and ended the run when a previous walk had scrolled it away, so the target lane never reached its own first phase. The witness is now bounded and records "bystander-unobserved" instead of blocking.
- f946e206, the walk cure: every collapsed section is expanded in turn (coordinate-bound, the target project's section first), the prefix readback tolerates a one-glyph OCR slip on its own query, and an exact title under this lane's own project heading is the pick.
- 6bba9cae, the bound cure: the claimed dispatch's phase bound is 480 s, because the expanded walk is deeper by design and 240 s was cutting a real census short.

Driver tests and ruff are green at 6bba9cae: 112 freebuff tests, plus the new walk, bystander, phase-bound and CivicScope-identity tests.

Bounds unchanged: one send, no navigation during send, the freshness read immediately before input, and the unchanged-composer-pixels check. At most once ever, and this iteration is that once. A start cue is not a verdict: RUNNING needs this lane's own new activity minutes later, otherwise the negative is filed with the trace.
