param([string]$Python, [string]$Thread, [string]$Phase, [string]$Evidence)
$ErrorActionPreference = 'Stop'
$wrapper = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex/bin/typesafe-credential.ps1'
& $wrapper -Action Run -TrustedChild -FilePath $Python -ArgumentList @(
    '-m', 'scripts.windows_freebuff_dispatch', '--thread', $Thread,
    '--phase', $Phase, '--evidence', $Evidence, '--scoped-input'
)
exit $LASTEXITCODE
