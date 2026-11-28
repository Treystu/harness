param([long]$Window, [switch]$NewWindow)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes

function Find-Control($Root, $Name, $Type) {
    $nameCondition = [Windows.Automation.PropertyCondition]::new(
        [Windows.Automation.AutomationElement]::NameProperty, $Name,
        [Windows.Automation.PropertyConditionFlags]::IgnoreCase)
    $typeCondition = [Windows.Automation.PropertyCondition]::new(
        [Windows.Automation.AutomationElement]::ControlTypeProperty, $Type)
    $condition = [Windows.Automation.AndCondition]::new($nameCondition, $typeCondition)
    $found = $Root.FindAll([Windows.Automation.TreeScope]::Descendants, $condition)
    if ($found.Count -eq 1) { $found.Item(0) }
}

function Open-Control($Control) {
    $pattern = $null
    if ($Control.TryGetCurrentPattern([Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) {
        $pattern.Invoke()
    } elseif ($Control.TryGetCurrentPattern([Windows.Automation.ExpandCollapsePattern]::Pattern, [ref]$pattern)) {
        $pattern.Expand()
    } else {
        throw 'The Notepad control has no Invoke or Expand pattern.'
    }
}

$editor = [Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Window)
$process = [Diagnostics.Process]::GetProcessById($editor.Current.ProcessId)
if ($process.ProcessName -ine 'Notepad') { throw 'The bound window is no longer Notepad.' }
$file = Find-Control $editor 'File' ([Windows.Automation.ControlType]::MenuItem)
if (!$file) { $file = Find-Control $editor 'File' ([Windows.Automation.ControlType]::Button) }
if (!$file) { throw 'Could not identify one Notepad File menu.' }
Open-Control $file
$menuName = if ($NewWindow) { 'New window' } else { 'Save' }
for ($attempt = 0; $attempt -lt 20 -and !$menuItem; $attempt++) {
    $menuItem = Find-Control $editor $menuName ([Windows.Automation.ControlType]::MenuItem)
    if (!$menuItem) { Start-Sleep -Milliseconds 100 }
}
if (!$menuItem) { throw "Could not identify one Notepad $menuName menu item." }
Open-Control $menuItem
