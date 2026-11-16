# Dogfood round report - 2026-11-14 laptop lane, round 2

Structured round per #277: one section per surface, every item recorded, silence not counted as a result.

## CLI

Checklist: every command incl. help text, error paths, exit codes on bad input

- **declared entry point help** - exercised: `python -m harness.cli --help` rc=0, 'usage: harness [-h]'
- **`python -m harness` package invocation** - FINDING (low, issue #529): no harness/__main__.py: `python -m harness` exits 1 with 'No module named harness.__main__' [the obvious invocation fails before argparse runs]
- **--version surface** - FINDING (low, issue #529): no --version flag on the CLI: `--version` exits 2 [argparse answers with usage and rc=2; no version flag exists]
- **declared subcommands: mission, serve, overlay (--help each)** - exercised: all three rc=0; rc=0, 'usage: harness mission [-h] {init,status,findings,resume,run} ...'
- **unknown subcommand** - exercised: refused with usage, rc=2, 'usage: harness [-h]'
- **unknown option** - exercised: refused with usage, rc=2, 'usage: harness [-h]'
- **bad argument value (mission bad choice)** - exercised: refused, rc=2, 'usage: harness mission [-h] {init,status,findings,resume,run} ...'
- **missing required argument (mission status)** - exercised: refused, rc=2, 'usage: harness mission status [-h] --id MISSION_ID [--root ROOT] [--ou'
- **probe discipline: three guessed subcommands (panel/audit/jev)** - exercised: not defects: those --help calls returned rc=2 because the subcommands do not exist; the declared set is mission/serve/overlay, so no finding is filed

Verdict: issues filed (#529)

## GUI

Checklist: launch, every pane, every primary interaction; dead controls and stale state

- **launch, every pane, every primary interaction** - NOT EXERCISED: no GUI host on this lane: the desktop driver is not serving (8765 is held by harness.cli serve and is DO NOT STOP per D-2026-11-13-001) and DRIVER_SCREEN is unset

Verdict: not exercised (1 of 1 items) - launch, every pane, every primary interaction: no GUI host on this lane: the desktop driver is not serving (8765 is held by harness.cli serve and is DO NOT STOP per D-2026-11-13-001) and DRIVER_SCREEN is unset

## MCP

Checklist: every tool/resource via a real MCP client; each description vs its behaviour

- **every tool/resource via a real MCP client; description vs behaviour** - NOT EXERCISED: no MCP client is registered in this lane, so no tool was called; running without one would be a simulated pass

Verdict: not exercised (1 of 1 items) - every tool/resource via a real MCP client; description vs behaviour: no MCP client is registered in this lane, so no tool was called; running without one would be a simulated pass

## WEBSITE

Checklist: every page loads; content matches the current product (commands, flags, versions)

- **every page loads; content matches the current product** - NOT EXERCISED: no preview host is registered for this lane; fetching the public site would measure the deployed site, not this tree

Verdict: not exercised (1 of 1 items) - every page loads; content matches the current product: no preview host is registered for this lane; fetching the public site would measure the deployed site, not this tree

## Verdicts

| surface | verdict |
|---|---|
| cli | issues filed (#529) |
| gui | not exercised (1 of 1 items) - launch, every pane, every primary interaction: no GUI host on this lane: the desktop driver is not serving (8765 is held by harness.cli serve and is DO NOT STOP per D-2026-11-13-001) and DRIVER_SCREEN is unset |
| mcp | not exercised (1 of 1 items) - every tool/resource via a real MCP client; description vs behaviour: no MCP client is registered in this lane, so no tool was called; running without one would be a simulated pass |
| website | not exercised (1 of 1 items) - every page loads; content matches the current product: no preview host is registered for this lane; fetching the public site would measure the deployed site, not this tree |
