# FreeBuff Lane 1 dispatch audit

| Step | State | Evidence |
| --- | --- | --- |
| Identify FreeBuff and bring it forward | Done | The driver confirmed the visible wordmark with Jev and recorded `foreground: true` after the consent-bound activation. [Open trace](freebuff-open.jsonl) |
| Open Harness Lane 1, thread `315608d2` | Done | Exact OCR located the row at (157, 662), Jev confirmed the target, and the driver clicked only that renderer. Jev confirmed Lane 1 selection at 0.98. [Selected session](https://github.com/Treystu/slow-lane-ledger/blob/laptop-vision-20261122/dispatch/laptop-driver/evidence/20261122/freebuff/lane1-selected.png) |
| Send once | Done | The first composer capture showed a dim Tab suggestion. The driver typed `continue in full`. The later draft was visible and sent as-is at 17:31:51 HST. The send trace records exact-text and Send-arrow Jev checks and one accepted input action. [Send trace](freebuff-send.jsonl) |
| Verify Lane 1 state | Running | At 17:31:56 HST the driver capture showed the exact sent message, “Working for 4s,” and the Stop control. Jev classified the turn as running at 0.98. It was left running. [Running screenshot](https://github.com/Treystu/slow-lane-ledger/blob/laptop-vision-20261122/dispatch/laptop-driver/evidence/20261122/freebuff/lane1-running.png) |

The first live OCR check on the draft failed while the caret was visible. The send proceeded before the stricter OCR steering arrived, with Jev exact-text verification and visual readback. Offline OCR then confirmed exact text in the saved pre-send frame. The follow-up change requires exact OCR before any future send, permits one fresh-frame retry, and binds the send grant to the thread and text. No second send was made. The original window PNGs stayed local.

## Follow-up audit

1. Exact foreground restoration remains open. The Notepad run verified the file but recorded `restore=false`. The original desktop view was restored separately.
2. FreeBuff uses HWND/PID-scoped compositor capture and sends explicit crops to Jev. Full capture timing now includes setup. Native capture teardown still needs a hard deadline, and action crops need freshness checks immediately before input.
3. FreeBuff receipts carry exact per-action parameters. The follow-up adds thread and text to the send receipt. The Notepad fallback New window and restore steps need independent scoped receipts.
