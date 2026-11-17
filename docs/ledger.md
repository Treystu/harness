# Ledger semantics

The autonomy ledger is a local JSONL evidence log. Each entry contains a
sequence number, previous hash, canonicalized body, and SHA-256 hash.

## What it proves

`ledger verify` proves that the entries currently loaded from the active file
form an internally consistent hash chain. It does not prove that the recorded
event happened, that the model's claim was true, or that an attacker with
filesystem access did not replace the complete file.

Malformed or torn lines are quarantined on load and reported. A repair
operation truncates the invalid tail file-locally: healthy segments are left
byte-identical and only the cut file is rewritten (or unlinked when nothing
in it survives). Repair is destructive to the invalid tail and should be
treated as an operator action; repairing a healthy ledger is a no-op.

The active ledger rotates after the configured size limit and retains a bounded
number of old files. Every rotation opens the fresh active file with a chained
`segment` event naming the moved file and its tip hash, so segment boundaries
stay cryptographically linked. `ledger verify` additionally reports chain
status: whether the loaded evidence spans segments, per-file bounds, and --
critically -- whether the retained chain starts mid-history (`pruned`), in
which case a `True` verdict means "valid suffix", never "complete genesis
chain". Rotated files are retention artifacts; users requiring a
complete audit archive should preserve and externally protect all segments.

## Operational guidance

- Keep the ledger on a durable local filesystem.
- Back it up before repair.
- Restrict permissions on the ledger directory.
- Preserve rotated files if evidence must remain complete.
- Treat `quarantined`, failed verification, and repair output as audit events
  requiring review.

## Resolving cited ledger entries (`D-YYYY-MM-DD-nnn`)

Because the autonomy ledger is local and uncommitted, **it is not stored in or
readable from a git repository checkout alone** unless an explicit sanitized
export has been committed. Repo-committed tracking summaries live in
[jev-roadmap.md](jev-roadmap.md) and GitHub issues.

- **Operator inspection command:** when an operator needs to inspect a local
  ledger entry or cited `D-YYYY-MM-DD-nnn` dispatch record on the host where
  the ledger lives, run:

  ```bash
  python -m harness.cli ledger tail --limit 50 --json
  ```

  (or inspect the `ledger.jsonl` / rotated segment files in the configured
  Harness config directory and verify integrity with
  `python -m harness.cli ledger verify --json`).
- **Checkout-only agent contract (fail closed):** an agent limited strictly to
  the repository tree cannot resolve an un-exported `D-YYYY-MM-DD-nnn` ID from
  source files. Do not probe outside workspace boundaries or invent missing item
  lists; **park** any dependency whose scope exists only in an unavailable `D-...`
  entry, naming the exact `D-YYYY-MM-DD-nnn` identifier in the report/blocker so
  the operator can supply or export it.
