# Windows Notepad vision proof

Run 12 at Harness commit `88849da` passed the driver-only launch, typing and save. Jev received the caller goal in each decision. Jev confirmed the blank editor and the typed text at 0.99 probability. Notepad-only captures took 0.184s and 0.118s against a 2s limit.

- [Driver screenshot](https://github.com/Treystu/slow-lane-ledger/blob/laptop-vision-20261122/dispatch/laptop-driver/evidence/20261122/run-12/notepad.png)
- [Driver audit chain](https://github.com/Treystu/slow-lane-ledger/blob/laptop-vision-20261122/dispatch/laptop-driver/evidence/20261122/run-12/driver.jsonl), 16 valid records, head `c774a2b4c671f893c7928a273dcee4713194683dd7720abb300b405cbfd56362`
- `Desktop\vision-test.txt` contained exactly 11 UTF-8 bytes, `hello world` with no terminating newline. SHA-256 `b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9`.

The runner exited 1 because Windows did not return the exact previous foreground handle. The proof windows were minimized separately and the original desktop view was visually confirmed. FreeBuff received no input. An earlier retry saved under Notepad's suggested `hello world.txt` name. That file was preserved.

## Repeat on the laptop

1. Open PowerShell in an isolated Windows checkout of `laptop-vision-20261122` containing `88849da`. Check the FreeBuff turn boundary, current authorization for live Jev inference, and that `Desktop\vision-test.txt` is available. The proof refuses to overwrite that file.
2. Create the isolated environment. No Harness or driver service port is needed.

   ```powershell
   $venv = Join-Path $env:TEMP 'harness-notepad-venv-20261122'
   & 'C:/Python314/python.exe' -m venv $venv
   $py = Join-Path $venv 'Scripts/python.exe'
   & $py -m pip install --only-binary=:all: 'windows-capture==2.0.1' 'Pillow==12.3.0'
   ```

3. Invoke the driver with the existing credential wrapper. It binds input and compositor capture to its own Notepad window and saves through the owned Save As dialog.

   ```powershell
   $desktop = [Environment]::GetFolderPath('DesktopDirectory')
   $out = Join-Path $env:TEMP ('harness-notepad-proof-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
   $goal = 'Open Notepad, type exactly hello world, and save Desktop\vision-test.txt.'
   & 'C:/Users/SCM/.codex/bin/typesafe-credential.ps1' -Action Run -TrustedChild -FilePath $py -ArgumentList @('-m','scripts.windows_notepad_proof','--goal',$goal,'--evidence',$out,'--desktop',$desktop)
   ```

4. Inspect `notepad.png` and `driver.jsonl` in `$out`. Verify the exact bytes independently.

   ```powershell
   $file = Join-Path $desktop 'vision-test.txt'
   [Convert]::ToHexString([IO.File]::ReadAllBytes($file)) -eq '68656C6C6F20776F726C64'
   ```

   The trace records desktop restoration separately. A failed restoration check requires visual cleanup of the proof window before leaving the desktop.
