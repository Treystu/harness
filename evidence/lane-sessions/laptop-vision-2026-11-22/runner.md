# T8 direct GitHub runner

The runner watches Harness #684 for a single authenticated owner comment. Its only accepted operation is an exact `continue in full` restart of existing Lane 1 or Disk Audit. SCMessenger remains parked because its visible search title is ambiguous. See [T4 trace](t4-scm-blocked.jsonl).

1. Oversight places a JSON file on private ledger main under `dispatch/laptop-driver/inbox/`. Fields are `action` (`restart-existing`), `thread`, `text`, and UTC `expires_at`.
2. Oversight posts `VISION-DISPATCH dispatch/laptop-driver/inbox/<name>.json <blob-sha>` on #684. The runner checks the GitHub actor ID, blob and bytes, expiry, thread, action, and text. The local comment-ID claim directory persists across restarts.
3. In the signed-in Windows session, use the existing isolated Python environment and credential wrapper. Supply two distinct visible bystander titles for the T7 demonstration.

   ```powershell
   $py = Join-Path $env:TEMP 'harness-notepad-venv-20261122/Scripts/python.exe'
   $state = Join-Path $env:LOCALAPPDATA 'harness-freebuff-runner'
   & $py -m scripts.windows_freebuff_runner --state $state --since '2026-11-23T04:27:00Z' --wait 180 --bystander-title 'Muse - Google Chrome' --bystander-title '*hello world - Notepad'
   ```

4. The runner files a claim, advances the driver through Search, query, exact selection, OCR and send, then posts its verdict and trace links. Before and after PNGs stay local. The receipt records frame hashes and bystander pixel equality. Running-lane cues are observations. The driver input trace carries the scope evidence.

The offline admission tests exercised the approved shape, a foreign author, wrong thread or text, and expired work. A real demonstration needs a fresh authorized idle-lane dispatch. T6 remains open on exact foreground restoration.
