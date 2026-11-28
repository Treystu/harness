param([Parameter(Mandatory)][long]$Window)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$root=[Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Window)
$doc=[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ControlTypeProperty,[Windows.Automation.ControlType]::Document)
$all=@($root.FindAll([Windows.Automation.TreeScope]::Descendants,$doc))
$out=@()
foreach($e in $all){
  $c=$e.Current; $p=$null
  $has=$e.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern,[ref]$p)
  $val=if($has){$p.Current.Value}else{''}
  $b=$c.BoundingRectangle
  $out+=@{name=$c.Name; offscreen=$c.IsOffscreen; hasValue=$has; value=$val; bounds=if($b.IsEmpty){@()}else{@([int]$b.X,[int]$b.Y,[int]$b.Width,[int]$b.Height)}}
}
@{count=$all.Count; documents=$out} | ConvertTo-Json -Depth 4 -Compress
