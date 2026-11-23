param([Parameter(Mandatory)][long]$Window, [string]$Project)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$root = [Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Window)
$scope = [Windows.Automation.TreeScope]::Descendants
$walker = [Windows.Automation.TreeWalker]::ControlViewWalker

if ($Project) {
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    $query = [Windows.Automation.PropertyCondition]::new(
        [Windows.Automation.AutomationElement]::NameProperty, $Project)
    $anchors = @($root.FindAll($scope, $query))
    $groups = @()
    foreach ($anchor in $anchors) {
        $parent = $anchor
        for ($depth = 0; $parent -and $depth -lt 5; $depth++) {
            $item = $parent.Current
            $children = @()
            for ($child = $walker.GetFirstChild($parent); $child; $child = $walker.GetNextSibling($child)) {
                $c = $child.Current
                $bounds = $c.BoundingRectangle
                $children += @{
                    name = $c.Name; kind = $c.ControlType.ProgrammaticName; hidden = $c.IsOffscreen
                    bounds = if ($bounds.IsEmpty) { @() } else { @($bounds.X, $bounds.Y, $bounds.Width, $bounds.Height) }
                }
                if ($children.Count -ge 100) { break }
            }
            $groups += @{ name = $item.Name; kind = $item.ControlType.ProgrammaticName; children = $children }
            if ($item.ControlType -eq [Windows.Automation.ControlType]::Document) { break }
            $parent = $walker.GetParent($parent)
        }
        if ($groups.Count -ge 20) { break }
    }
    ConvertTo-Json -InputObject @{ anchors = $anchors.Count; groups = $groups } -Depth 5 -Compress
    exit 0
}
$document = [Windows.Automation.PropertyCondition]::new(
    [Windows.Automation.AutomationElement]::ControlTypeProperty,
    [Windows.Automation.ControlType]::Document)
$active = @()
foreach ($element in $root.FindAll($scope, $document)) {
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
