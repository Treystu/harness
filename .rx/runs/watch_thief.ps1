$deadline = (Get-Date).AddSeconds(210)
$seen = @{}
while ((Get-Date) -lt $deadline) {
  $hits = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like '*harness-notepad-venv*' -or $_.CommandLine -like '*harness-notepad-venv*' }
  foreach ($h in $hits) {
    if (-not $seen.ContainsKey($h.ProcessId)) {
      $seen[$h.ProcessId] = $true
      $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($h.ParentProcessId)" -ErrorAction SilentlyContinue
      "HIT pid=$($h.ProcessId) ppid=$($h.ParentProcessId) name=$($h.Name) at=$(Get-Date -Format o)"
      "  exe=$($h.ExecutablePath)"
      "  cmd=$($h.CommandLine)"
      if ($parent) { "  parent=$($parent.Name) ppid=$($parent.ProcessId)"; "  parentcmd=$($parent.CommandLine)" }
    }
  }
  Start-Sleep -Milliseconds 400
}
"WATCH-DONE"
