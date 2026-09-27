param([string]$SourcePath = (Join-Path $PSScriptRoot '..\jl.ps1'))
$ErrorActionPreference = 'Stop'
$source = Get-Content -Raw -LiteralPath $SourcePath
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$null, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
# Exercise the actual startup and Enter path with external effects replaced.
$names = @('Initialize-PythonRuntime', 'Start-JinBackend', 'Start-ModelSwitch',
    'Test-LauncherConfigReady', 'Refresh-Runtimes', 'Normalize-BaseUrl',
    'Test-AutoBaseValue', 'Test-AutoModelValue', 'Sync-CursorsToSelected',
    'Get-ModelIndex', 'Clamp-Cursor')
$ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -in $names
}, $false) | ForEach-Object { . ([scriptblock]::Create($_.Extent.Text)) }
$start = $source.IndexOf('    Write-BootLine "CONFIG" "reading configuration"')
$end = $source.IndexOf('    $sw = [Diagnostics.Stopwatch]::StartNew()', $start)
$startup = [scriptblock]::Create($source.Substring($start, $end - $start))
function Import-DotEnv {}
function Ensure-JinConfig {}
function Write-BootLine {}
function Add-Event { param($Text, $Color) [void]$script:Calls.Add($Text) }
function Render-Dashboard { [void]$script:Calls.Add('render') }
function Test-AppReady { return $script:AppAlreadyReady }
function Test-ExplicitBrainConfiguration { return (-not $script:EmbeddedTest) }
function Get-PythonConfigValue { param($Name) return $script:Config[$Name] }
function Set-PythonConfigValue { param($Name, $Value) $script:Config[$Name] = $Value }
function Ensure-Dependencies {
    [void]$script:Calls.Add('dependencies')
    if (-not $script:EmbeddedTest -and -not $script:Config.BRAIN_MODEL_UID) {
        throw 'Python preparation blocked model selection'
    }
    if ($script:FailDependencies) { throw 'dependency failure' }
    return [pscustomobject]@{Python='test-python'; State='CACHED'}
}
function Get-EndpointState {
    param($Role, $BaseUrl, $SelectedModel)
    [void]$script:Calls.Add('probe')
    return [pscustomobject]@{Role=$Role; BaseUrl=$BaseUrl; Online=$true;
        Selected=$SelectedModel; Source='test'; Error=''; Models=@(
            [pscustomobject]@{Id='model-a'; Loaded=$false; LoadedContext=0},
            [pscustomobject]@{Id='model-b'; Loaded=$false; LoadedContext=0})}
}
function Ensure-LlamaRuntime { return [pscustomobject]@{Server='test'; Build='test'; State='CACHED'} }
function Ensure-DefaultEmbeddedModel { return [pscustomobject]@{Path='test'; Repo='test'; State='CACHED'} }
function Start-EmbeddedBrain { [void]$script:Calls.Add('embedded') }
function Format-ContextTokens { param($Value) return "$Value" }
function Remove-Item {} # Backend log cleanup must not touch the real installation.
function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $NoNewWindow,
        $RedirectStandardOutput, $RedirectStandardError, $PassThru)
    if ($FilePath -ne 'test-python') { throw 'Backend launched without prepared Python' }
    [void]$script:Calls.Add('backend')
    return [pscustomobject]@{HasExited=$false}
}
function Assert { param($Condition, $Message) if (-not $Condition) { throw $Message } }

foreach ($scenario in @('fresh', 'resume-empty', 'configured', 'embedded', 'failure', 'attached')) {
    $script:Calls = New-Object System.Collections.ArrayList
    $script:EmbeddedTest = $scenario -eq 'embedded'
    $script:FailDependencies = $scenario -eq 'failure'
    $script:AppAlreadyReady = $scenario -eq 'attached'
    $script:PythonExe = ''
    $script:BackendProcess = $null
    $script:BackendOwned = $false
    $script:SwitchJob = $null
    $script:PendingContextApply = $null
    $script:BootMode = $false
    $script:ConfigExistedAtLaunch = $true
    $script:FirstRunLmStudio = $scenario -in @('fresh', 'failure')
    $script:Config = @{BRAIN_API_BASE='http://test'; BRAIN_MODEL_UID=''; SERVICE_API_BASE=''; SERVICE_MODEL_UID=''}
    if ($scenario -in @('configured', 'attached')) { $script:Config.BRAIN_MODEL_UID = 'model-a' }
    $script:FirstRunLmStudioRuntime = Get-EndpointState 'brain' 'http://test' ''
    $script:Calls.Clear()
    $Root = 'test-root'
    $EmbeddedBrainBaseUrl = 'http://embedded'
    $EmbeddedBrainModelId = 'embedded-model'
    $StdOutPath = 'unused.stdout'
    $StdErrPath = 'unused.stderr'
    . $startup
    if ($scenario -in @('fresh', 'resume-empty', 'failure')) {
        Assert (-not $script:Calls.Contains('dependencies')) "$scenario prepared Python before input"
        Assert (-not $script:Calls.Contains('backend')) "$scenario started backend before input"
        Assert ($script:Calls.Contains('BRAIN   choose a model and press ENTER')) 'Missing picker prompt'
        Assert (-not $script:LauncherInitializing) 'Picker still marked initializing'
        if ($scenario -eq 'fresh') { Assert (-not $script:Calls.Contains('probe')) 'Repeated initial catalog probe' }
        # Down + Enter selects the second model through the production handler.
        $script:CursorByRole.brain = 1
        try { Start-ModelSwitch 'brain' $script:BrainRuntime }
        catch { if (-not $script:FailDependencies -or $_.Exception.Message -ne 'dependency failure') { throw } }
        Assert ($script:Config.BRAIN_MODEL_UID -eq 'model-b') 'Enter did not save selected model'
        Assert ($script:Calls.Contains('dependencies')) 'Enter did not prepare Python'
        Assert (-not $script:LauncherInitializing) 'Preparation left initializing flag stuck'
        if ($script:FailDependencies) {
            Assert (-not $script:Calls.Contains('backend')) 'Backend started after failed preparation'
            continue
        }
    }
    if ($scenario -eq 'attached') {
        Assert (-not $script:Calls.Contains('dependencies')) 'Attached backend unnecessarily prepared Python'
        continue
    }
    Assert ($script:Calls.Contains('backend')) "$scenario did not launch backend"
    Assert ($script:Calls.IndexOf('dependencies') -lt $script:Calls.IndexOf('backend')) 'Backend preceded dependencies'
    Assert (@($script:Calls | Where-Object { $_ -eq 'dependencies' }).Count -eq 1) 'Duplicate preparation'
    if ($script:EmbeddedTest) {
        Assert ($script:Calls.IndexOf('dependencies') -lt $script:Calls.IndexOf('embedded')) 'Embedded setup order changed'
    }
}
Write-Output 'PASS: immediate picker, Enter, resumed config, configured/embedded startup, attachment and failure'
