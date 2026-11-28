Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class W {
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, System.Text.StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, System.Text.StringBuilder s, int n);
}
"@
$py = Join-Path $env:TEMP 'harness-notepad-venv-20261122\Scripts\python.exe'
$p = Start-Process -FilePath $py -ArgumentList '-c','import time; time.sleep(12)' -PassThru
Start-Sleep -Seconds 3
$h = $p.MainWindowHandle
if ($h -eq 0) { $h = [W]::GetForegroundWindow() }
$c = New-Object System.Text.StringBuilder 256
$t = New-Object System.Text.StringBuilder 512
[void][W]::GetClassName($h, $c, 256)
[void][W]::GetWindowText($h, $t, 512)
"hwnd=$h class=$($c.ToString()) title=$($t.ToString())"
Wait-Process -Id $p.Id -Timeout 20 -ErrorAction SilentlyContinue
