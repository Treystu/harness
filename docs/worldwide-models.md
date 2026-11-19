# The worldwide model statistics site (#407)

The worldwide model site is a **separate** public surface from the Proof Bench
results. Proof Bench publishes one operator's sanitized evidence bundle and its
per-run proofs. This surface publishes **aggregate** statistics only: for each
public model, one closed UTC month, the cohort's calls, success rate, cost per
successful task and mean latency — and nothing else.

It is opt-in, revocable, and never attributable. `harness/public_share.py` is
the single owner of the whole surface: the consent record, the client queue and
handoff, the report the client builds, the intake validator, the publisher and
the site's roster payload.

## The disclosure the operator accepts

Sharing is on only while a readable, correctly scoped record with this exact
disclosure says so. The wording is pinned in `tests/test_docs_contracts.py`:

```text
I choose to share aggregate model usage, success, cost, and latency statistics with the public worldwide model site. My raw ledger stays private. The site publishes figures only for qualifying groups. I can turn sharing off at any time. Turning it off discards unsent reports and stops new submissions from this profile. A report already sent may still be counted, even if its group has not yet been published. Previously contributed values cannot be withdrawn from a group, and previously published figures remain available.
```

## Revocation is future-only

- Turning sharing off stops new submissions from that profile and **discards
  unsent work** in the queue.
- A report already handed to the anonymous intake stays eligible for its
  cohort, including when publication happens later.
- Withdrawal is serialized with the client's final handoff: consent is
  rechecked at handoff and again before every retry of a queued submission, so
  a withdrawal either lands before the handoff (the report is dropped) or
  after it (the report is already counted).
- Re-enabling sharing starts a **new consent period**; a queued report from an
  older period is refused rather than handed off under the new one.
- The single-operator Proof Bench export consent (`site-consent-v1`) does not
  authorize this surface. It is a different schema, surface and version, and
  `policy_for` refuses it.

There is no retraction of already counted values, and no pseudonymous
sub-aggregate that could join one contributor's history: those were judged and
rejected in the filed ruling. Withdrawal stops future sharing only.

## What leaves the machine

A report is exactly this shape — the intake allowlist is exact at every level:

| Field | Carries |
|---|---|
| `protocol`, `metric_version` | `public-share-v1`, `1` |
| `round` | the closed UTC month, `YYYY-MM` |
| `model` | one allowlisted public model id |
| `commitment` | a binding commitment over the exact statistics and a nonce |
| `shares` | three secret shares of the statistics (`x`, `v`) |
| `proof` | consent surface and version, a consent-**period digest**, a coarse coverage row count, a chain-verified claim, the statistics digest and an evidence digest |
| `eligibility` | a round-scoped token and the issuer's voucher |

Never on the wire: raw ledger rows, ledger tips or head hashes, precise
consent timestamps, credentials, API keys, paths, free text, prompt or
instruction text, machine or operator identity. The serialized report is
secret-scanned before any other check and again on intake; a report that would
need redacting is refused, never cleaned.

## Distinct operators

Ten uploads from one installation are not ten operators. The client derives a
token from its eligibility credential, scoped to the model and the round, and
the issuer vouches for it. One credential yields one token per model and round,
so a retry — or a hundred retries — counts once. The issuer sees only
round-scoped tokens: never the credential, never an address. Uploads and
sender metadata are never joined to a report.

## Publication floor and suppression

- **Ten distinct verified operators** per model, month and metric, each with an
  eligible observation for that metric. A canary-only installation contributes
  zero, because public ingestion reads evidence through the one canary-filtered
  reader.
- Figures are computed from cohort totals; rates and means never average
  per-operator rates.
- A metric whose denominator has no observations is suppressed.
- A qualifying cell publishes once, after the round closes.
- Companion totals and breakdowns that would let a reader recover a suppressed
  cell by subtraction are suppressed. The site publishes no all-model total.
- A ten-operator figure stays published after one operator turns sharing off.
  A following month with nine qualifying operators shows exactly
  `No verified data` in the site, the API and downloadable results.
- A report whose evidence cannot support the statistics (no cost evidence or no
  observed outcome for the model) is refused locally instead of guessed at.

## Receipts and what a proof establishes

Every published figure names its cohort receipt: the round, model, metric,
value, formula version, cohort operator count, the denominator and the
sufficient totals, the aggregate commitment root, a proof digest and the site
signature. A reader can recompute the displayed arithmetic from the receipt,
and the signature detects a figure changed after publication.

A proof over private local evidence establishes consistency with that evidence.
It does **not** establish that the operator reported every task, and it does not
establish that an outside provider delivered the recorded outcome.

## What is not claimed

No finite cohort protects an exact sum against an observer who knows every other
input. If protection against that observer is required, the exact figure must be
withheld rather than published with a caveat.

## Using it

```python
from harness import public_share as ps

issuer = ps.EligibilityIssuer(key)          # the issuer's key, not the client's
profile = ps.ShareProfile("~/.local/state/harness/public-share",
                          transport=my_intake_transport,
                          issuer=issuer,
                          credential=issuer.credential(profile_secret))
profile.enable()                            # records the disclosure as accepted
profile.submit(ledger, model="deepseek/deepseek-v4.1-flash")
profile.disable()                           # future-only; unsent work is dropped
```

On the receiving side, `PublicPublisher.accept` validates a report,
`.seal(round_id)` publishes the cells that clear the floor, and
`roster_payload(publisher.published())` is the site's data file. Deployment of
the site is a separate operator-confirmed step and is not claimed here.
