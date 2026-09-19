param(
    [Parameter(Mandatory = $true)][string]$InputPath,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [Parameter(Mandatory = $true)][ValidateSet('word', 'powerpoint', 'excel')][string]$App
)

# Word/PowerPoint/Excel 을 COM 으로 띄워 문서를 PDF 로 내보낸다.
# 원본은 읽기 전용으로만 열고, 어떤 경우에도 finally 에서 앱을 종료한다.

$ErrorActionPreference = 'Stop'
$processNames = @{ word = 'WINWORD'; powerpoint = 'POWERPNT'; excel = 'EXCEL' }
$application = $null
$document = $null
$ownsApplication = $false
$exitCode = 1

function Get-OfficePids([string]$name) {
    @(Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
}

try {
    # COM 은 현재 작업 폴더를 기준으로 상대 경로를 풀지 않으므로 절대 경로로 바꾼다.
    $inputFile = (Resolve-Path -LiteralPath $InputPath).Path
    $outputFile = [System.IO.Path]::GetFullPath($OutputPath)

    # New-Object 가 새 프로세스를 만들었는지 프로세스 목록 차이로 알아낸다.
    # Word/Excel 은 항상 새 인스턴스를 만들지만 PowerPoint 는 이미 떠 있는 인스턴스에 붙는다.
    # 그 경우 사용자의 PowerPoint 를 Quit 하면 안 되므로 $ownsApplication 으로 구분한다.
    $before = Get-OfficePids $processNames[$App]
    switch ($App) {
        'word' { $application = New-Object -ComObject Word.Application }
        'powerpoint' { $application = New-Object -ComObject PowerPoint.Application }
        'excel' { $application = New-Object -ComObject Excel.Application }
    }
    $launched = @(Get-OfficePids $processNames[$App] | Where-Object { $before -notcontains $_ })
    $ownsApplication = $launched.Count -gt 0
    if ($ownsApplication) {
        # Python 이 타임아웃으로 이 스크립트를 죽일 때 이 PID 로 Office 를 정리한다.
        [Console]::Out.WriteLine("OFFICE_PID=$($launched[0])")
        [Console]::Out.Flush()
    }

    switch ($App) {
        'word' {
            $application.Visible = $false
            $application.DisplayAlerts = 0          # wdAlertsNone
            # Open(FileName, ConfirmConversions, ReadOnly)
            $document = $application.Documents.Open($inputFile, $false, $true)
            $document.ExportAsFixedFormat($outputFile, 17)   # wdExportFormatPDF
        }
        'powerpoint' {
            # PowerPoint 는 Visible=$false 설정이 예외를 내므로 WithWindow=$false 로 창만 숨긴다.
            $previousAlerts = $application.DisplayAlerts
            $application.DisplayAlerts = 1          # ppAlertsNone
            # Open(FileName, ReadOnly, Untitled, WithWindow)
            $document = $application.Presentations.Open($inputFile, $true, $false, $false)
            $document.SaveAs($outputFile, 32)                # ppSaveAsPDF
        }
        'excel' {
            $application.Visible = $false
            $application.DisplayAlerts = $false
            # Open(FileName, UpdateLinks, ReadOnly)
            $document = $application.Workbooks.Open($inputFile, 0, $true)
            $document.ExportAsFixedFormat(0, $outputFile)    # xlTypePDF
        }
    }

    if (-not (Test-Path -LiteralPath $outputFile)) {
        throw "PDF was not created: $outputFile"
    }
    $exitCode = 0
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    $exitCode = 1
}
finally {
    if ($null -ne $document) {
        try {
            switch ($App) {
                'word' { $document.Close(0) }        # wdDoNotSaveChanges
                'powerpoint' { $document.Close() }
                'excel' { $document.Close($false) }
            }
        } catch {}
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($document)
    }
    if ($null -ne $application) {
        if ($ownsApplication) {
            try { $application.Quit() } catch {}
        } elseif ($App -eq 'powerpoint' -and $null -ne $previousAlerts) {
            # 사용자의 PowerPoint 에 붙었던 경우: 종료하지 않고 바꾼 설정만 되돌린다.
            try { $application.DisplayAlerts = $previousAlerts } catch {}
        }
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($application)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

exit $exitCode
