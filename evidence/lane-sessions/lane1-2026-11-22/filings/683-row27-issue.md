# Validate inbox directories against the declared root

Part of #683, finding 27 (P2). Verified against `main` `8fc28a0e` on
2026-11-25: still present.

## Current evidence

driver_core/mission_executor.py:208 `_directory()` joins and creates the path with no root or symlink check; `_mission_path` line 224 tests `os.path.islink(path)` on the file only, so a symlinked `missions/` reads and removes files outside the declared root.

## The finding

**

If `root/missions` is a symlink to an external directory, the parent comparison succeeds because both sides resolve to that external directory, while `islink(path)` checks only the mission file itself. The executor therefore reads, executes, and removes missions outside the declared private root; this is reproducible with an ordinary JSON file beneath a symlinked `missions` directory. Validate the directory itself against the root and reject symlinked inbox directories; the same directory helper also allows receipts and archives to be redirected outside the root.

## Requested fix

The behaviour the finding describes is still reachable at the path and line
above. Fix it there, not by widening the caller.

## Acceptance

- The reproduction the finding describes no longer occurs at
  `driver_core/mission_executor.py`.
- A hermetic test pins the fixed behaviour.

Provenance: https://github.com/Treystu/harness/pull/612#discussion_r4611145898
