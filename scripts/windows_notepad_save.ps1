param([long]$Window, [string]$Destination)
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

if (Test-Path -LiteralPath $Destination) { throw 'The destination already exists.' }
$editor = [Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Window)
$process = [Diagnostics.Process]::GetProcessById($editor.Current.ProcessId)
if ($process.ProcessName -ine 'Notepad') { throw 'The bound window is no longer Notepad.' }
$file = Find-Control $editor 'File' ([Windows.Automation.ControlType]::MenuItem)
if (!$file) { $file = Find-Control $editor 'File' ([Windows.Automation.ControlType]::Button) }
if (!$file) { throw 'Could not identify one Notepad File menu.' }
Open-Control $file
for ($attempt = 0; $attempt -lt 20 -and !$save; $attempt++) {
    $save = Find-Control $editor 'Save' ([Windows.Automation.ControlType]::MenuItem)
    if (!$save) { Start-Sleep -Milliseconds 100 }
}
if (!$save) { throw 'Could not identify one Notepad Save menu item.' }
Open-Control $save

$root = [Windows.Automation.AutomationElement]::RootElement
$owner = [Windows.Automation.PropertyCondition]::new(
    [Windows.Automation.AutomationElement]::ProcessIdProperty, $process.Id)
for ($attempt = 0; $attempt -lt 30 -and !$nameField; $attempt++) {
    $windows = $root.FindAll([Windows.Automation.TreeScope]::Children, $owner)
    foreach ($windowNode in $windows) {
        if ($windowNode.Current.Name -ine 'Save As') { continue }
        $dialog = $windowNode
        $nameField = Find-Control $dialog 'File name:' ([Windows.Automation.ControlType]::Edit)
    }
    if (!$nameField) { Start-Sleep -Milliseconds 100 }
}
if (!$nameField) { throw 'Could not identify the Notepad Save As filename field.' }
$value = $nameField.GetCurrentPattern([Windows.Automation.ValuePattern]::Pattern)
$value.SetValue($Destination)
if ($value.Current.Value -cne $Destination) { throw 'Save As filename readback differed.' }
if (Test-Path -LiteralPath $Destination) { throw 'The destination appeared before save.' }
$saveButton = Find-Control $dialog 'Save' ([Windows.Automation.ControlType]::Button)
if (!$saveButton) { throw 'Could not identify one Save As Save button.' }
Open-Control $saveButton
