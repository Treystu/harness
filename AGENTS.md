# Harness — agent context

**Read this first.** Then read the canon. Tool-neutral: Claude Code (primary
lane) loads this via `CLAUDE.md`; any other agent reads it directly.

## Single source of truth

| File | Role |
|---|---|
| **`docs/jev-roadmap.md`** | **CANON** — STATUS, tracker, next slice, DoD. The only operational plan. |
| `CLAUDE.md` | Claude Code operating notes (model tiering, skills, gates, MCP) |
| `docs/claude-context.md` | Agent-lane context pack: files, trust/permissions, launch recipes, legacy Freebuff notes |
| `docs/jev-mission-prompt.md` | Mission prompts (`/isolated-mission`, headless `claude -p`) |
| `docs/system-one-integration.md` | Architecture rationale only (not STATUS) |
| `docs/MODEL_SELECTION_HANDOFF_2026-09-13.md` | Model policy evidence |
| `.agents/skills/typesafe-ai/SKILL.md` | TypeSafe / System One skill (read before touching `jev*.py`) |
| `.claude/skills/`, `.claude/agents/` | `/isolated-mission`, `/isolated-request`, seats `/cto` `/ceo` `/bod`; scout / implementer / verifier tiers |
| `HANDOFF/{CTO,CEO,BOD}_STATE.md` | Seat state (read at seat resume; updated at session close) — not plans |

If a local `docs/jev-roadmap.md` disagrees with `origin/main`, **fetch origin** —
origin wins. The operator tree (`main`) may lag; reconcile before trusting STATUS.

## Current mission (generated pointer - do not hand-edit)

**Generated:** 2026-11-27 at `origin/main` `58b0ea5a`, from a two-method live read
(`gh issue list --state open --limit 400` = 43; search API `type:issue is:open`
agrees at 43).
Regenerate this block in the same act that refreshes the canonical register in
[docs/jev-roadmap.md](docs/jev-roadmap.md); if the two disagree, the register wins
and this block is regenerated, never hand-edited. Every change, including this
block, goes through a reviewed PR with local gates and green CI; one phase PR at
a time; never push directly to `main`.

**The open set.** Issue #295 is the live queue; the **Canonical burndown register -
2026-11-19** section in `docs/jev-roadmap.md` owns its count, placement and order,
and the register mirror under it is that register's generated live-state annex.
**43 open issues**, of which **26 are placed** in the register's tables and **17 are
filed but not yet placed** (ports #655, security #652, #653, #805, gap audit #684,
driver #703, #704, #722 and #818-#826); placing them is the register owner's taxonomy
act, so this block names them as unplaced rather than inventing a wave.

| Register section | Placed open |
|---|---|
| Train | 0 |
| W1 - defects + Cluster E deliverables | 15 |
| W2 - verification + Champion program | 6 |
| W3 - parked (owner-present tails) | 3 |
| Tracker / blocked | 2 |
| Filed, not yet placed | 17 |

**Canon rows are a different unit and are not in the counts above.** The `HV-*` /
`EV-*` / `DRV-*` / `GAP-*` / `DF-*` families live in the roadmap's own tables:
`EV-8` and `OC-HANDOFF` are open, `GAP-jury` / `JEV-P2-jury` are **deferred by
operator ruling - do not invent them**, and `CIVICSCOPE-COMPLETION` is deferred in
a sibling repository. Every other row in those families is complete.

| Rule | Truth |
|---|---|
| Completion rule | STATUS may say complete only when `harness jev-phase --phase <ID>` passes the bar (hard gates + sentiment buckets) **and** CI is green on the merge |
| Do not | redo shipped phases; mark complete while audit/CI red; merge red CI; hardcode provider brands in phase code |

## Worktrees

`git worktree list` is authoritative. Convention: one worktree per phase PR at
`C:\Users\SCM\Documents\GitHub\Harness-<slug>` on its feature branch, created
off `origin/main`; remove it after the PR merges. The operator tree
`C:\Users\SCM\Documents\GitHub\Harness` stays on `main`. Worktrees whose tip is
already an ancestor of `origin/main` are historical — leave them alone or prune.
`.freebuff/worktrees/*` are legacy Freebuff session trees (gitignored).

## Model tracking policy (operator ruling 2026-09-21)

Hermetic unit tests stay hermetic (`test/model` doubles) — they prove contracts, not provider quality.

**Live tracking / dogfood / smoke** must not be free-tier-only (`*:free`, especially ling). Use **cheap paid** rungs first so cost, parseability, and escalation are real:

| Seat | Prefer (paid cheap) | Avoid as sole live evidence |
|---|---|---|
| Apply primary | `deepseek/deepseek-v4.1-flash` | `inclusionai/ling-3.0-flash-fin:free` |
| Judge | `z-ai/glm-5.3-flash` | free gemma-only when rate-limited |
| Paid ling (if used) | `inclusionai/ling-3.0-flash` | free `ling-…:free` |
| Escalation | `z-ai/glm-5.3-flash` → `deepseek/deepseek-v4-pro` → `qwen/qwen3.8-max-0902` | free-only ladder |

Live probe snapshot (2026-09-21, OpenRouter fusion key, small “OK” chat):

| Model | Status | Notes |
|---|---|---|
| `inclusionai/ling-3.0-flash-fin:free` | 200 / $0 | Free baseline only |
| `google/gemma-4-31b-it:free` | **429** | Free pool unstable — do not gate tracking on it |
| `inclusionai/ling-3.0-flash` | 200 / ~$0.0000007 | Cheapest paid ling |
| `deepseek/deepseek-v4.1-flash` | 200 / ~$0.000002 | Default paid apply |
| `z-ai/glm-5.3-flash` | 200 / ~$0.00001 (reasoning-off retry) | Default paid judge |
| `qwen/qwen3.8-max-0902` | 200 / ~$0.00029 | Frontier rung — use sparingly |

Operator harness config (`~/.config/harness/config.json`) already arms paid escalation. For tracking runs prefer paid apply/judge via env or config (`HARNESS_USE_FREE=false`, paid pools in `harness/config.py`). The OpenRouter key has a small daily limit (≈$0.75 on 2026-09-22) — keep probes tiny.

The model policy above governs **Harness's own lanes**. The policy for the
coding agent's own delegation (no static model tiers) is in `CLAUDE.md`.

## Rules every agent keeps

1. Canon STATUS only — no parallel plans; update existing docs instead of adding new ones.
2. One phase PR at a time; merge only when **local gates + CI audit** green.
3. Builder ≠ sole grader; fail ≠ approve; no fake complete.
4. No provider brand hardcoding in phase code PRs — resolve via ladders / `MS-*`.
5. Do not game `audits/self/coverage_baseline.json` to hide untested new lines; refresh only after real tests execute those lines.
6. Report blocked with exact command/output — never “will do”.
7. Every change to `main` — STATUS and docs included — lands through a PR with green CI; never push directly to `main` (2026-09-22: direct STATUS pushes left `main` red, `DF-GOV-1`).
8. **Uncommitted work is at-risk work.** Commit on the phase branch as you go — a `wip:` checkpoint beats a dirty tree — and push the feature branch early; the push is the backup, not the merge (see `CONTRIBUTING.md` → *Commit and push safety*). Never force-push a shared branch, never rewrite `main`, and never run `git checkout .`, `git reset --hard` or `git clean -fd` over work you have not committed — park it on a `backup/*` ref first, the convention this repo already uses. A push is not done until the CI run for that commit is green: a queued run is not green, no run is not green, and the merge gate stays local gates + CI audit.
9. **A PR body names the head it is about.** Any `Head SHA` or `Verification`
line names the PR's current head; when a commit lands after the body was
written, refresh the body in the same act. The rail at the exact head is the
evidence and the body is only the pointer to it, so a body pinned to a
superseded head describes a tree nobody is reviewing (#573).

## LANE PROTOCOL - all agent lanes, all sessions (added 2026-10-29)
1. ONE BRANCH, ONE CLONE. Work in the canonical clone only. Never create worktrees or scratch/backup branches. Your lane branch (THIS REPO line below) is the only branch you work on; it carries ONE standing DRAFT PR into the base - oversight's live view of all your work, WIP included.
2. PUSH MANDATE. If it isn't pushed, it doesn't exist. Commit + push incomplete work (prefix "wip:" + what state it's in) at every turn end, every sub-step, before any risky operation, and at least every 20 minutes. Never end a session unpushed. Before every push: git status - never commit secrets, API keys, .env files, private keys, credentials, build output, or binaries; if a file matters but can't be committed, leave it untracked and name it in your status comment. Never push main or the base directly. No force-push except --force-with-lease on your own lane branch, and never rewrite a commit a comment already references.
3. STEERING LOOP. At every turn start, and again after every push: read new comments on your draft PR, on every open PR you own, and on every issue you're working, plus newly filed issues. Comments from Treystu are authoritative directives (the owner and his oversight agent): they outrank your prompt and your plan; newest wins. Acknowledge each in-thread, do it, then reply with evidence (SHA, the rail's per-check statuses, test results). If one is ambiguous, ask ONE clarifying question in-thread and keep working on everything else.
4. STATUS + RESUME. End every turn with a status comment on the draft PR (mirror to the tracker in the THIS REPO line): DONE / WIP / NEXT / BLOCKERS / DIRECTIVES, with SHAs. Resume from GitHub alone: fetch, read the latest status comment + every newer Treystu comment, verify lane-branch HEAD matches the status SHA. GitHub beats local state and local notes, always.
5. LANDING + GATES. Work reaches the base only under your tasking's merge rules (green + verified + non-destructive; the rail is the CircleCI commit statuses, read individually on the exact head, and a combined status is not evidence; on this repo GitHub Actions check-runs are a billing lock, not a signal, so they are never the read; revert first if a landing turns the base red). WIP on the lane branch may be red - say so in the commit message. Lucas Gate v2 first, Jev for decisions/dispositions, on every comment, review, and disposition you post. No emoji in repo content.
THIS REPO: lane branch lane/burndown; base main; standing draft PR lane/burndown -> main; tracker issue #295 - mirror every status comment there.
