# Enforce the accepted plan's aggregate source limit

Part of #683, finding 82 (P2). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Method

Code read of the named path at `8fc28a0e`: `harness/research_plan.py` and the code it calls,
on 2026-11-25. No repository code changed in that act, so this is a read
of the shipped path, not a run and not a test.

## Result

harness/research_plan.py:771-781 appends every search's `max_results` sources and one source per fetch, and never reads `plan.max_sources`; the field is validated at :354-355 as a plan property only. A two-query plan with `max_results=3` and `max_sources=1` therefore returns six sources, past the budget the reviewed plan carried.

## The finding

For a multi-query plan, each search appends up to `max_results` sources and every fetch appends another source, but execution never reads `plan.max_sources`. For example, a valid accepted plan with two searches, `max_results=3`, and `max_sources=1` returns six sources. This exceeds the source budget included in the reviewed plan and exposes downstream consumers to evidence beyond that bound. Enforce the aggregate source limit across search and fetch results.

## Scope of this issue

Enforce the plan max_sources across search and fetch results, so the sources returned never exceed the budget the reviewed plan carried. The per-query max_results stays as it is.

## Not claimed

- Not claimed: that the plan validation changes; max_sources is already banded there.
- Not claimed: that a truncated run must report insufficient evidence; the bound is a ceiling, not a target.
- Not claimed: any behaviour for a single-query plan whose max_results already fits.

## Acceptance

- A plan whose queries would produce more than max_sources sources returns at most max_sources.
- The bound applies across search and fetch sources together.
- A hermetic test uses two searches with max_results 3 and max_sources 1 and asserts one source.

Provenance: https://github.com/Treystu/harness/pull/669#discussion_r4658925854

