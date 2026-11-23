param([string]$Python, [string]$Thread, [string]$Phase, [string]$Evidence, [switch]$Standing)
$ErrorActionPreference = 'Stop'
$wrapper = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex/bin/typesafe-credential.ps1'
if ($Phase -eq 'project-census') {
    if (!$Standing -or $Thread -ne '2ae32937') { throw 'Census requires the standing pinned target' }
    $arguments = @('-m', 'scripts.windows_freebuff_t4', '--phase', $Phase, '--evidence', $Evidence)
} else {
    $arguments = @(
        '-m', 'scripts.windows_freebuff_dispatch', '--thread', $Thread,
        '--phase', $Phase, '--evidence', $Evidence, '--scoped-input'
    )
    if ($Standing) { $arguments += '--standing' }
}
& $wrapper -Action Run -TrustedChild -FilePath $Python -ArgumentList $arguments
exit $LASTEXITCODE
