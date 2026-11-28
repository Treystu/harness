# ProofGate — Tier 0 required check (every merge)

    python3 tools/proofgate/proofgate.py . <receipt.json> <base_sha> <head_sha>

Receipt schema and rules are in the proofgate.py docstring (the docstring is
the spec; the code reads exactly those fields). Empty ranges fail. Evidence
is content-hash-bound, so a receipt cannot survive an edit to the files it
covers. Enabling this as a *required* status check is a repo-admin act
(branch protection) — this folder lands the check itself.
