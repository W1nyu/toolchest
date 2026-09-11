param(
    [string]$ImagePath,
    [string]$Language = 'ko',
    [Parameter(Mandatory = $true)][string]$OutPath,
    [switch]$ListLanguages
)

$ErrorActionPreference = 'Stop'

try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime

    # 네 타입 모두 명시적으로 로드해야 한다. Windows.Globalization.Language 를
    # 빠뜨리면 TryCreateFromLanguage 호출에서 TypeNotFound 로 죽는다.
    $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]

    $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and
        $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]

    function Await($operation, $resultType) {
        $task = $asTask.MakeGenericMethod($resultType).Invoke($null, @($operation))
        $task.Wait(-1) | Out-Null
        $task.Result
    }

    $maxDimension = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension

    if ($ListLanguages) {
        $tags = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages |
            ForEach-Object { $_.LanguageTag })
        $payload = [pscustomobject]@{ languages = $tags; maxDimension = $maxDimension }
        $payload | ConvertTo-Json -Depth 5 -Compress | Out-File -FilePath $OutPath -Encoding utf8
        exit 0
    }

    if (-not $ImagePath) { throw '-ImagePath 인자가 필요합니다.' }

    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage(
        [Windows.Globalization.Language]::new($Language))
    if ($null -eq $engine) { throw "'$Language' 인식기를 만들 수 없습니다." }

    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) `
        ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) `
        ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) `
        ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

    $lines = @()
    foreach ($ocrLine in $result.Lines) {
        $words = @($ocrLine.Words)
        if ($words.Count -eq 0) { continue }
        $minX = [double]::MaxValue
        $minY = [double]::MaxValue
        $maxX = [double]::MinValue
        $maxY = [double]::MinValue
        foreach ($word in $words) {
            $rect = $word.BoundingRect
            if ($rect.X -lt $minX) { $minX = $rect.X }
            if ($rect.Y -lt $minY) { $minY = $rect.Y }
            if (($rect.X + $rect.Width) -gt $maxX) { $maxX = $rect.X + $rect.Width }
            if (($rect.Y + $rect.Height) -gt $maxY) { $maxY = $rect.Y + $rect.Height }
        }
        $lines += [pscustomobject]@{
            text = $ocrLine.Text
            x    = $minX
            y    = $minY
            w    = $maxX - $minX
            h    = $maxY - $minY
        }
    }

    $payload = [pscustomobject]@{ lines = @($lines); maxDimension = $maxDimension }
    $payload | ConvertTo-Json -Depth 5 -Compress | Out-File -FilePath $OutPath -Encoding utf8
    exit 0
}
catch {
    $message = $_.Exception.Message
    try {
        $errorPayload = [pscustomobject]@{ error = $message }
        $errorPayload | ConvertTo-Json -Depth 5 -Compress | Out-File -FilePath $OutPath -Encoding utf8
    } catch {
        # $OutPath 자체를 쓸 수 없는 경우, 아래 stderr 출력만이라도 남긴다.
    }
    [Console]::Error.WriteLine($message)
    exit 1
}
