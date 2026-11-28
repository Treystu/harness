AUDIT — PREVIOUS DRIVER SESSION'S METHOD (7095488264). Sources read: PR #685 branch evidence/lane-sessions/laptop-vision-2026-11-22/ (README.md run-12 Notepad proof, freebuff-dispatch.md, freebuff-send/open/capture jsonl, t3-disk-audit-*, t4-scm-blocked, t6-exact-focus, driver-dispatch-design.md, runner.md) and the ledger T8 receipts. Read-only.

1) RECONSTRUCTED METHOD
T1 Notepad proof: isolated temp venv; input and compositor capture bound to the driver's OWN Notepad HWND/PID; Jev receives the caller goal on each decision; capture 0.184s against a 2s limit; exact bytes verified independently (11 bytes, sha256 b94d27b9...). Restoration was recorded separately and FAILED (restore=false).
T2 Lane 1 launch: Jev confirms the FreeBuff wordmark, consent-bound activation, record foreground=true; exact OCR locates row 315608d2 at (157,662), Jev confirms the target, click only that renderer; composer read, dim Tab suggestion recognised, exact text typed and sent once at 17:31:51 HST with consent bound to thread+text; then verify the sent message + "Working for 4s" + Stop control.
T3 Disk Audit: read-only preflight on saved crops, exact label, then the same send discipline; no model/settings change.
T6 foreground restore: record prior hwnd/pid/title, restore exact, verify; failure is surfaced, never assumed.
T7 bystanders: two distinct visible titles captured before/after and compared pixel-for-pixel; identical RGB is the safety proof.
T8 unaided restart: GitHub-authenticated payload, digest+expiry+fixed vocabulary, create-only claim, one-send marker persisted before submission, readback after send.
Common thread: small HWND-scoped crops to Jev, exact OCR for literals, one fresh-frame retry when a caret obscures text, one send per restart, evidence hashes sealed in the audit chain.

2) LESSON TABLE (EMBODIED at PR #685 head / MISSING)
- Window-bound capture + input (EMBODIED: windows_freebuff_capture + WindowsWindowScreen; title/handle revalidation).
- Exact OCR for labels and drafts, one fresh-frame retry (EMBODIED: locate_exact_text/read-exact-draft-retry).
- One send bound to thread+text, consent receipt (EMBODIED: SEND params + one-send marker).
- Bystander pixel equality (EMBODIED: runner.same_pixels + capture_set).
- Exact foreground restore with named failure (EMBODIED: execute() finally-block, foreground-restored audit row).
- Project-scoped identity for duplicate titles (MISSING in the old session; EMBODIED now: 0c06ab16/6d39d6b0 series, selected-row-project refusal).
- Heading vs chat with the same name, collapsed project (MISSING; EMBODIED now: 01ae9065 session_candidates + one expand).
- Foreground contention from the scheduled watch console (MISSING; EMBODIED now: 9ac0f417/64d398c5 obtain-and-verify, temp-root python title match).
- Renderer returns to New-chat home after the child exits (MISSING; PARTIAL: 3725f613 re-open at send + 44d55d1d banner-over-glyph).
- Per-request token accounting (MISSING: traces record model and probabilities, no token counts).
- "Working for Ns" as an independent running signal (MISSING: we read Stop glyph + banner only).
- Durable verdict corroboration rule (MISSING: visual post-start is unreliable because the app reloads; GitHub leg must be primary).

3) IMPLEMENTATION ITEMS added to the self-fix set (7095171339) under 7095426512
I-1 Read "Working for Ns" from the transcript header as a second running signal; record it in the verdict row. (new)
I-2 Record per-request Jev token counts in driver.jsonl from the client response; report p95 capture and tokens per run. (new)
I-3 Verdict template requires the GitHub leg or a re-opened, re-verified view; a home-page frame may never corroborate a lane. (new; operationalized today in the Lane 1 verdict)
I-4 Close R3 (heading/chat + collapsed project) on a clean SCM cold run; cure landed 01ae9065. (register R3)
