## STEP 0 - trace persistence, two independent counts

Order item 5 asked for the two-count trace-persistence verification (in-memory trace count versus the ledger's `decision_trace` entries) on one live brief run. This filing gives the verification, states exactly what ran, and states what did **not** run. The live brief run is **not claimed** - see "The gap" below.

Script: `evidence/lane-sessions/lane1-2026-11-22/w466_step0_trace_counts.py` at `f304e915`. Machine-readable result: `evidence/lane-sessions/lane1-2026-11-22/filings/466-step0-trace-counts.json`, committed at the same SHA. Exit code 0.

### Part A - the live gate, measured as it behaves

One live decision-gate call through the product seam the CLI faces use (`jev_face_governor` -> `policy_for` -> `ledger_for`), on this lane's own pass-19 filing text, with a real Jev model call: verdict `investigate`, disposition `proceed`, supported 0.08.

Counts: in-memory writes **0**, reader rows **0**, raw file rows **0**.

That is not a leak or a missing write. `JevPolicy.evaluate_decision` has no trace attribute of its own (`grep "self.trace" harness/jev_policy.py` returns nothing): the gate decides, and its **callers** persist. Naming it here matters, because a reader who saw "0 rows" without the reason would file a defect that does not exist.

### Part B - the persistence seam, two independent counts

The persist seam those callers use, driven twice through the real CLI (`harness assess --trace-ledger`, the `record_disposition` call site at `harness/cli.py`), over one temp ledger:

- count 1, the writer's own answer: **2** event ids, both non-empty
- count 2, the shared reader `read_trace_events`: **2** rows
- count 3, a raw line scan that does not use the reader: **2** `decision_trace` rows
- event id sets: **identical** across all three
- kinds: `assessment.disposition` only, no second sink
- sequence: 1, then 2
- `prev_hash` chain: row 2's `prev_hash` equals row 1's `hash`; `AutonomyLedger.verify()` returns **true**
- rows: `9f3c3f6b813d437894fa54e3fba81247` (hash `2b840c8e...bf94`, prev null), then `b8e4140dbb964350925ef9f7e9792838` (hash `d778a237...2230`, prev `2b840c8e...bf94`)

So on this seam, what the writer says it wrote, what the reader returns, and what is on disk are three agreeing numbers, over a ledger whose chain verifies. That is the acceptance act's substance.

### The gap, stated rather than papered over

The order's literal acceptance is "one live brief run". It cannot be executed on this machine: `load_settings()` resolves **only** the Jev key (`jev_api_key` set; `api_key`, `openrouter_api_key`, `typesafe_api_key` all None), so no brief or plan run can reach a model. Part A's live Jev call is a real model call, but it is a decision-gate call, not a brief run.

Therefore: the persistence verification above **is delivered and is real**; the live brief run **is not claimed**, and item 5 stays open on that leg until a provider key exists on the machine that runs it. This is the same class of blocker as order item 7's #342/#344 work: the code path exists, the resource does not.

### What closes this

- With a provider key: re-run the same script with Part A replaced by one real brief run; the persistence half needs no change.
- Or: accept the two-count result above as the persistence verification and re-scope the order's "live brief run" to the live gate call, if the owner prefers that reading. This filing does not take that decision for the owner; it records both halves and names the missing one.

Lane 1 made no other change in this act. No issue is closed by this filing.

### Gate receipt and what the escalate label is discharged against

Lucas Gate v2 typed track: **pass**, artifact sha256 `4cb085e15968f5e20ebc437f6871ae11c88baef1c60ba58f25012436378fd230` (`filings/receipt-466-step0.json`). Product Jev: label **escalate**, disposition **proceed** (supported 0.06, margin 0.20, model jev-1.14.0). Each claim the label could be about is answered from the artifacts themselves:

- "the gate persists nothing" - measured, not inferred: Part A counted 0 writes at the writer, 0 rows at the reader and 0 rows in the raw file while a live call was made; the `self.trace` grep is corroboration, not the basis.
- "only the Jev key resolves" - measured by `load_settings()` in the same run and reported per field in the JSON.
- "the persistence counts agree" - three separate numbers with the ids and hashes printed, and the chain re-verified by the ledger's own `verify()`.
- The one thing this filing could overstate, it does not: Part B's judgment payload is **supplied**, not model-produced, and the case is stated as the persist seam only. The live brief leg is withheld, so no credit is taken for it.

Refs #466, #475, #469.
