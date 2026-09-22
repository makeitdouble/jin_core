param([string]$SourcePath = (Join-Path $PSScriptRoot '..\jl.ps1'))
$ErrorActionPreference = 'Stop'
$source = Get-Content -Raw -LiteralPath $SourcePath
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$null, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
# Load real preferences/probes without starting servers or reading user config.
$preferences = $source.Substring($source.IndexOf('$ErrorActionPreference'),
    $source.IndexOf('$Root =') - $source.IndexOf('$ErrorActionPreference'))
$functions = $ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -in @('Test-AppReady', 'Get-JinPageTitle')
}, $false) | ForEach-Object { $_.Extent.Text }
$scenario = @'
$AppUrl = 'http://test.invalid'
function Invoke-WebRequest {
    param($Uri, [switch]$UseBasicParsing, $TimeoutSec, $ErrorAction)
    Write-Progress -Activity 'HTTP probe' -Status 'Receiving response'
    Write-Progress -Activity 'HTTP probe' -Completed
    [pscustomobject]@{StatusCode=200; Content='<title>JIN &amp; Core</title>'}
}
# Progress outside the title probe, e.g. module preparation.
Write-Progress -Activity 'Preparing modules for first use' -Status 'Loading'
Write-Progress -Activity 'Preparing modules for first use' -Completed
if (-not (Test-AppReady)) { throw 'Readiness response changed' }
if ((Get-JinPageTitle) -ne 'JIN & Core') { throw 'Title response changed' }
function Invoke-WebRequest {
    Write-Progress -Activity 'HTTP probe' -Status 'Failing'
    throw 'offline'
}
if (Test-AppReady) { throw 'Offline endpoint reported ready' }
if ((Get-JinPageTitle) -ne 'JIN') { throw 'Title fallback changed' }
'@
foreach ($control in @($true, $false)) {
    $ps = [powershell]::Create()
    try {
        $settings = if ($control) { '$ProgressPreference = "Continue"' } else { $preferences }
        [void]$ps.AddScript($settings + "`n" + ($functions -join "`n") + "`n" + $scenario)
        [void]$ps.Invoke()
        if ($ps.HadErrors) { throw ($ps.Streams.Error | Out-String) }
        $count = $ps.Streams.Progress.Count
        if ($control -and $count -eq 0) { throw 'Control failed to emit progress' }
        if (-not $control -and $count -ne 0) { throw "Launcher leaked $count progress records to the host" }
        Write-Output "control=$control progress_records=$count"
    }
    finally { $ps.Dispose() }
}
Write-Output 'PASS: startup, readiness, title and fallback paths preserve console ownership'
