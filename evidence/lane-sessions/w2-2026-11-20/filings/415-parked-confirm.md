## #415 - PARKED CONFIRMED, unblocker unchanged and precisely named: account credit, not the key limit

**State:** the live GUI ask with the Jev semantic approval path remains unrun on the paid route.

**Unblocker, exactly:** **OpenRouter account credit exhausted**, not a key budget problem. On the recorded run `/api/v1/key` returned **200** with `limit_remaining 1.5` while the paid dispatch returned **402 `spend limit exhausted`**, and the `$0` lane (`openrouter/free`) returned **200 at cost 0**. The serve prints `key_remaining=$1.500000` headroom it does not have - filed as the intake row `spend-key-remaining-stale` (#415).

**Consequence for this lane:** no paid ask is attempted, so #415's acceptance (model, spend and verdict recorded from a real GUI ask) cannot be met. The two findings already routed from this issue stand: `freelane-reasoning-in-answer` (high) and `web-records-before-plan` (high, shared with #342).

**Up to date:** yes - re-checked this turn against the live key surface; the discrepancy is unchanged. Parked and proceeded from, not waited on.
