param([Parameter(Mandatory)][long]$Window)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$root = [Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Window)
$document = [Windows.Automation.PropertyCondition]::new(
    [Windows.Automation.AutomationElement]::ControlTypeProperty,
    [Windows.Automation.ControlType]::Document)
$active = @()
foreach ($element in $root.FindAll([Windows.Automation.TreeScope]::Descendants, $document)) {
    if ($element.Current.IsOffscreen) { continue }
    $pattern = $null
    if (!$element.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern, [ref]$pattern)) { continue }
    $url = $null
    if (![Uri]::TryCreate($pattern.Current.Value, [UriKind]::Absolute, [ref]$url)) { continue }
    if ($url.Scheme -ne 'https' -or $url.Host -notin @('freebuff.com', 'www.freebuff.com', 'app.freebuff.com')) {
        continue
    }
    # Only expose a session identifier from the active document's own route.
    # Do not read the text of links, query parameters, or unrelated elements.
    if ($url.AbsolutePath -match '/(?:c|chats?|sessions?)/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/?$') {
        $active += $Matches[1].ToLowerInvariant()
    }
}
ConvertTo-Json -InputObject @($active | Sort-Object -Unique) -Compress
