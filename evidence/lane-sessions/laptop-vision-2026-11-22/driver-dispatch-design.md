# Efficient vision dispatch on the laptop

The verified Lane 1 open used three Jev requests. The verified send and response check used five. The traces record probabilities and elapsed capture time. Token usage per request is a remaining measurement gap. [Open trace](freebuff-open.jsonl) · [Send trace](freebuff-send.jsonl)

| Work | Preferred implementation |
| --- | --- |
| Poll, claim, check deadlines and file receipts | Local code using GitHub API cursors and the existing driver-core mission inbox, claim store and receipt format. An idle watcher consumes zero model tokens. |
| Locate labels and verify literal drafts | Exact OCR in the bound window and action region. Prefer a verified native control ID if the app exposes one. Use one fresh frame if a caret or redraw makes OCR ambiguous. |
| Confirm controls and visible results | Pin `jev-1.14.0` for the tested path. Use small HWND-scoped crops and batch independent typed questions from the same capture. Use OCR geometry for known labels. TypeSafe marks images and Box as experimental. [TypeSafe models](https://docs.typesafe.ai/models.md) · [Image support](https://docs.typesafe.ai/go/images.md) |
| Investigate a new failure | Use the saved crop and trace offline. Use GPT-6.1 Sol at medium reasoning and Standard speed if the failure needs judgment. Use Tier 1 for explicitly delegated mechanical work. |

## Direct GitHub dispatch

1. Keep #684 as the oversight and receipt surface. Use the existing private ledger for structured, expiring mission payloads. The GitHub comment can point to a payload. Validate repository, authenticated author, exact payload digest, and the fixed action vocabulary before claiming it.
2. Run the watcher in the signed-in Windows user's interactive session, outside Lane 1's checkout. Reuse existing GitHub authentication and inject the existing Jev credential only into the trusted driver child. Use the existing mission claim store to prevent replay by comment ID and payload digest.
3. Ack the claim, then require exact session, action, text, foreground, and fresh target evidence. Persist the one-send marker before submitting. If a process exits after sending, recover by reading back the existing turn and filing its state.
4. Rehearse against captured fixtures for staged text, dim suggestion, unrelated draft, occupied lane, hours refusal, obscured target and recovery after send. Report action count, Jev input tokens and p95 capture time per run. Complete the live T8 receipt only after the prerequisite matrix tests are accounted for.
