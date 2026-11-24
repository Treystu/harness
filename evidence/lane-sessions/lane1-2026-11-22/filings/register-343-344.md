# Register rows for #343 and #344

Head `663ee651463bdca406e3810cbe4028a0789bbd79`, branch `lane1/register-343-344`,
base `main` `4fa960ce7e5ecd08125fa317e0fff70cee615b65`.

## What changed

`docs/jev-roadmap.md` rows 180-181 for #343 and #344 named neither what had
landed nor what the issues still mean -- they carried a register pointer only.
Each row now records the landed PRs with their merge SHAs (#647 `fecc4692`,
#658 `4fa960ce`; #648 `6602e00d`) and the acceptance lines that remain unbuilt,
exactly as filed on the issues.

## Why this is not closure

Both issues stay OPEN. The remaining lines are named on each issue and in this
row: for #343 the shared native result reviewer and the snippet-versus-rendered
evidence distinction; for #344 a declined-retrieval control, approved
plan/receipt binding, saved native-route reuse, and a public-adapter control.
No completion credit is taken and no issue is closed.
