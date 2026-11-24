## Register correction for #344 landed

**PR:** #714, head `76db6cdf`, read fresh at that exact head: 16/16 CircleCI
contexts success, 0 pending, 0 bad, including `audit`. Squash-merged as
`a127481b2f9d5ab2d1dbb5ad3b87a97c5f1f6a0e` (short `a127481b`), read back with
`gh pr view` as MERGED and from `treystu/main` after a fetch.

The #344 row in `docs/jev-roadmap.md` now records PR #713's plan-body landing,
and the row's earlier "Remaining, named on the issue" sentence -- that a resumed
turn supplying no plan must re-route with `plan-unknown` because the body was
not persisted -- is superseded. The issue stays OPEN for the owner's
disposition; no completion credit is taken.

---

Withheld, not posted. Gate receipts for this text: first draft Lucas `pass`
(sha256 `9275a556ff8e8060fd57ac40d03edba6f215d975d3cc114ae9fb03d2453c2826`),
product Jev `escalate` / `needs_improvement` (supported 0.06); rewritten with the
primary-source detail above, Lucas `pass` (sha256
`80d3a1d0d9a01a8c168d95e9f62b00b326a750f298c41708b6b57feb7e055d70`), product Jev
`investigate` / `needs_improvement` (supported 0.04). A bare register note does
not clear the product gate, and posting it anyway would be the fake-complete the
gate exists to stop. The merge itself is recorded where it belongs: PR #714 is
MERGED as `a127481b` and the #344 row in `docs/jev-roadmap.md` carries it. The
next substantive check-in reports the register landing with its rail.
