Add-Type -AssemblyName System.Windows.Forms
$idle = [System.Windows.Forms.SystemInformation]::IdleTime.TotalSeconds
"IDLE_SECONDS=$idle"
"--- FreeBuff / python / gh processes ---"
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match 'FreeBuff|python|node' -or $_.CommandLine -match 'windows_freebuff' } |
  Select-Object ProcessId, Name, @{n='Started';e={$_.CreationDate}}, @{n='Cmd';e={ if ($_.CommandLine) { $_.CommandLine.Substring(0,[Math]::Min(160,$_.CommandLine.Length)) } }} |
  Format-Table -AutoSize | Out-String -Width 240
"--- visible top-level windows ---"
Get-Process | Where-Object { $_.MainWindowTitle } |
  Select-Object Id, ProcessName, MainWindowTitle | Format-Table -AutoSize | Out-String -Width 200
