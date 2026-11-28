param([Parameter(Mandatory)][long]$Window, [int]$Limit=40, [string]$Needle)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$root=[Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Window)
$all=@($root.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition))
$out=@()
foreach($e in $all){
  if($out.Count -ge $Limit){break}
  $c=$e.Current
  if($Needle -and $c.Name -notmatch $Needle){continue}
  $out+=@{name=$c.Name; type=$c.ControlType.ProgrammaticName; offscreen=$c.IsOffscreen}
}
@{total=$all.Count; sample=$out} | ConvertTo-Json -Depth 4 -Compress
