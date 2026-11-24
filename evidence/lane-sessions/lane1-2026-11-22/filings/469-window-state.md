## W469 window state - 2026-11-22 (clock day 1, 0 of 30 campaigns)

**Live read:** `main` `4fa960ce7e5ecd08125fa317e0fff70cee615b65`. Clock opened
2026-11-21T02:12:16Z on this issue; that is day 1, not a completed window.

**Corpus:** zero campaigns. `harness/flush_loop.py` now retains a campaign
history (`campaign_trace`, PR #644 `280ee3d4`: product entry injects the writer,
default sink resolved through the configured ledger), but no campaign has been
run since the writer was wired, and the repo carries no campaign stop/pass
events to replay. The only `"campaign"` strings under `audits/` are unrelated
scratch fixtures.

**Consequence, stated plainly:** the acceptance cannot be decided yet. It needs
replayed campaign pass histories to simulate the comparators (bar 90 + streak 3,
bar 95 + streak 1) and to look for a real 4-cycle. With zero campaigns there is
nothing to simulate, and a verdict of either kind would be invented. **No
completion credit is taken and the item stays open.**

**What would make it decidable:** 30 campaigns inside the window whose
histories reach the retained ledger, then an offline replay that counts escapes
per comparator and the cycle lengths actually present.
