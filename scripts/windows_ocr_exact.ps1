param([string]$Path, [string]$Label, [switch]$WholeText, [switch]$ReadText, [int]$Ordinal)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime]
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and
        $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1
function Await-Operation($Operation, $ResultType) {
    $task = $asTask.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.Wait()
    $task.Result
}
$file = Await-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$stream = Await-Operation ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
try {
    $decoder = Await-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await-Operation ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    try {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
        if (!$engine) { throw 'Windows OCR has no available language.' }
        $result = Await-Operation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        if ($ReadText) {
            @{ text=($result.Lines.Text -join "`n") } | ConvertTo-Json -Compress
            exit 0
        }
        if ($WholeText) {
            $matches = @($result.Lines)
            if (($matches.Text -join ' ').Trim() -cne $Label) { throw 'OCR text differed from the requested message.' }
        } else {
            $matches = @($result.Lines | Where-Object { $_.Text.Trim() -ceq $Label })
            if ($Ordinal) {
                if ($matches.Count -ne 2 -or $Ordinal -notin 1,2) { throw "Expected two exact candidate rows; found $($matches.Count)." }
                $matches = @($matches[$Ordinal-1])
            } elseif ($matches.Count -ne 1) { throw "Expected one OCR line with the requested label; found $($matches.Count)." }
        }
        $rects = @($matches | ForEach-Object { $_.Words } | ForEach-Object { $_.BoundingRect })
        $left = ($rects.X | Measure-Object -Minimum).Minimum
        $top = ($rects.Y | Measure-Object -Minimum).Minimum
        $right = ($rects | ForEach-Object { $_.X + $_.Width } | Measure-Object -Maximum).Maximum
        $bottom = ($rects | ForEach-Object { $_.Y + $_.Height } | Measure-Object -Maximum).Maximum
        @{ x=[int](($left+$right)/2); y=[int](($top+$bottom)/2) } | ConvertTo-Json -Compress
    } finally {
        $bitmap.Dispose()
    }
} finally {
    $stream.Dispose()
}
