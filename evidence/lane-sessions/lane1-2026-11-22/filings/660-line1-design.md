Design note for `#660` line 1: the shared native result reviewer. Nothing here
is built; this is the shape the build will follow, and the one question the
issue leaves open.

## What exists already

`harness/jev_policy.py` has the seat pattern line 1 asks for, in
`evaluate_file_triage`: one preflighted call (`self._preflight`) against a
`noul` question pack, answers read back per item, a validated subset returned,
a keyword fallback when the evaluator refuses, and a structural accounting
record (`self._account`) that carries the reservation. `harness/jev_packs.py`
owns the pack builder (`file_relevance_question_pack`). There is no equivalent
for a fetched web result: admission today is per-candidate URL/redirect logic
in `harness/web.py`, which is deterministic and cheap and stays.

## The slice

1. `harness/jev_packs.py`: `result_relevance_question_pack(results)` — one noul
   per result ("Is this result, as read, relevant to the request?"), bounded by
   the same small maximum the gatherer already uses (`max_sources`).
2. `harness/jev_policy.py`: `evaluate_result_relevance(prompt, results, *,
   site="web-results", task_id=None) -> (JevEvaluationResult, structural)`,
   modelled on `evaluate_file_triage`: same reservation, same refusal and
   spend-limit handling, same structural receipt.
3. Typed verdicts. A noul is a probability, so the type is a band on it, stated
   in code and in the docstring rather than left to a reader:
   `>= 0.70 relevant`, `<= 0.30 rejected`, otherwise `uncertain`. Each verdict
   carries the probability and the pack's own reason string, so the record
   names why.
4. Admission. Results whose verdict is `rejected` or `uncertain` are removed
   from `web_sources` before the model sees them — absent, not down-ranked —
   and an `emit` record names each excluded URL with its verdict and
   probability. The exclusion runs at one point for every retrieval path, in
   the hourglass web gathering and the conversation web gathering alike, so
   both lanes share the same reviewer seat.

## The open question (named, not assumed)

`#660` fixes what an uncertain or rejected verdict does. It does not say what
admission does when the reviewer cannot answer at all — evaluator refusal, a
spend limit, a transport error. Two rules are defensible and they differ in
kind:

- **exclude all, disclose the outage**: nothing unreviewed reaches the model,
  and the run says the evidence was withheld. Safe against fabricated
  relevance; costs the whole web detour when Jev is down.
- **admit, labelled unreviewed**: the evidence still arrives, each item marked
  `(unreviewed)` so the model and the user can tell it was not screened. Safer
  against silent evidence loss; risks passing unrelated content, which line 1
  exists to prevent.

This lane will not choose by itself. Until oversight rules, the build does the
narrower thing that satisfies the acceptance text and cannot misrepresent:
excluded, with the outage disclosed in the run record and in the answer-path
evidence block. The two #343 lines do not cover the outage case, so the choice
is recorded on `#660` for a ruling rather than buried in code.

## Cost

One pack call per web turn, not one per result, under the existing
`JEV_MAX_INPUT_TOKENS` ceiling and the ordinary reservation/ceiling path.
Results are bounded to what the gatherer already keeps (3 by default), so the
pack is small and the ceiling check does not change shape.

## Not in this slice

- No new checkpoint, ledger, or response-schema field. If a per-result verdict
  must survive a resume, the existing checkpoint already stores the source
  dicts, so the verdict rides on them; nothing new is invented.
- No claim-level provenance (`#422`) and no lifecycle binding (`#344`).
