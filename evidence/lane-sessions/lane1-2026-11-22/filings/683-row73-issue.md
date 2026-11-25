# Preserve unpublished status for posted-content subtypes

Part of #683, finding 73 (P2). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Method

Code read of the named path at `8fc28a0e`: `harness/citation_resolver.py` and the code it calls,
on 2026-11-25. No repository code changed in that act, so this is a read
of the shipped path, not a run and not a test.

## Result

harness/citation_resolver.py:137-143 merges the two fields: `subtype = str(message.get("subtype") or message.get("type") or "").lower()`, then tests that merged value against `("posted-content", "preprint")` and otherwise assigns `version = "published"`. A record with `type: "posted-content"` and `subtype: "working_paper"` therefore never matches the parent type and is stamped published.

## The finding

For a registry record with `type: "posted-content"` and `subtype: "working_paper"`, `"report"`, or `"other"`, preferring `subtype` discards the posted-content classification and assigns `version: "published"`. Crossref explicitly describes [posted content as not formally published](https://support.crossref.org/hc/en-us/articles/213126346-Posted-content-includes-preprints). With an injected working-paper record, `verify_citation` consequently returns `supported` for a citation incorrectly claiming `version: "published"`. Check the parent type before assigning published status, and omit the version when the registry does not establish a supported classification.

## Scope of this issue

Read the parent type before assigning a version, and omit `version` when the registry does not establish a classification this gate can stand behind. The subtype may still refine a published record; it must not upgrade a posted-content record to published.

## Not claimed

- Not claimed: that every Crossref type missing from the current tuple needs its own version string. The fix is to stop promoting posted-content, not to enumerate the registry.
- Not claimed: any change to how a missing `version` is scored elsewhere; omitting it is the registry saying it does not know.

## Acceptance

- A record with `type: "posted-content"` and a subtype of working_paper, report or other is not stamped published.
- `verify_citation` no longer returns supported for a citation claiming `version: "published"` over such a record.
- A hermetic test injects the working-paper record the finding describes.

Provenance: https://github.com/Treystu/harness/pull/645#discussion_r4647990348

