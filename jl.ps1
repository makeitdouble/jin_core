param(
    [string]$LmStudioBaseUrl = "http://localhost:1234",
    [string]$AppUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigPath = Join-Path $Root "config.py"
$ConfigExamplePath = Join-Path $Root "config.example.py"
$LauncherDir = Join-Path $Root ".jin_launcher"
$StdOutPath = Join-Path $LauncherDir "backend.stdout.log"
$StdErrPath = Join-Path $LauncherDir "backend.stderr.log"
$LauncherMutex = $null
$LauncherMutexName = "Global\JINCoreLauncher"
$script:BackendProcess = $null
$script:BackendOwned = $false
$script:BrowserOpened = $false
$script:SwitchJob = $null
$script:SwitchRole = ""
$script:SwitchModel = ""
$script:SwitchContext = 0
$script:PendingContextApply = $null
$script:ContextMode = $false
$script:ContextRole = ""
$script:ContextModel = ""
$script:ContextOptions = @()
$script:ContextIndex = 0
$script:AsyncKeyDown = @{}
$script:KeyRepeatState = @{}
$script:DashboardDirty = $true
$script:PrevChars = $null
$script:PrevCols = $null
$script:PrevW = 0
$script:PrevH = 0
$script:StdOutPosition = 0L
$script:StdErrPosition = 0L
$script:Events = New-Object System.Collections.ArrayList
$script:RuntimeMessage = "INITIALIZING COGNITIVE RUNTIME"
$script:BrainTemperature = "?"
$script:ServiceTemperature = "?"
$script:RuntimeLogsEnabled = "?"
$script:BootMode = $true
$script:BootStarted = $false

[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try { [Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false) } catch {}

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class JinConsoleVT {
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern IntPtr GetStdHandle(int nStdHandle);
    [DllImport("kernel32.dll")]
    public static extern bool GetConsoleMode(IntPtr hConsoleHandle, out uint lpMode);
    [DllImport("kernel32.dll")]
    public static extern bool SetConsoleMode(IntPtr hConsoleHandle, uint dwMode);
    [DllImport("kernel32.dll")]
    public static extern bool FlushConsoleInputBuffer(IntPtr hConsoleInput);
    [DllImport("kernel32.dll")]
    public static extern IntPtr GetConsoleWindow();
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]
    public static extern short GetAsyncKeyState(int vKey);
}
"@

$h = [JinConsoleVT]::GetStdHandle(-11)
[uint32]$consoleMode = 0
if ([JinConsoleVT]::GetConsoleMode($h, [ref]$consoleMode)) {
    [void][JinConsoleVT]::SetConsoleMode($h, ($consoleMode -bor 0x0004))
}

# Keep ConHost from entering QuickEdit selection mode and swallowing navigation
# keys. Some Windows PowerShell 5.1 hosts also report KeyAvailable=false for
# arrow keys, so the launcher has a focused-window Win32 fallback below.
$inputHandle = [JinConsoleVT]::GetStdHandle(-10)
[uint32]$inputMode = 0
if ([JinConsoleVT]::GetConsoleMode($inputHandle, [ref]$inputMode)) {
    $inputMode = ($inputMode -bor 0x0080) -band (-bnot 0x0040)
    [void][JinConsoleVT]::SetConsoleMode($inputHandle, $inputMode)
}
# Clear stale key events once at startup. Do NOT flush on every input poll:
# doing so makes held/navigation keys feel sticky in Windows PowerShell 5.1.
try { [void][JinConsoleVT]::FlushConsoleInputBuffer($inputHandle) } catch {}

$esc = [char]27
$ansi = @(
    "$esc[38;2;8;15;18m",      # 0 almost black teal
    "$esc[38;2;27;72;78m",     # 1 dim teal
    "$esc[38;2;36;112;120m",   # 2 teal
    "$esc[38;2;47;175;185m",   # 3 cyan
    "$esc[38;2;105;238;241m",  # 4 bright cyan
    "$esc[38;2;61;111;170m",   # 5 blue
    "$esc[38;2;218;151;65m",   # 6 amber
    "$esc[38;2;108;126;132m",  # 7 gray
    "$esc[38;2;191;210;213m",  # 8 light
    "$esc[38;2;216;83;83m",    # 9 red
    "$esc[38;2;86;191;133m"    # 10 green
)
$reset = "$esc[0m"
$hideCursor = "$esc[?25l"
$showCursor = "$esc[?25h"
$clear = "$esc[2J$esc[H"

function Start-BootScreen {
    if ($script:BootStarted) { return }
    $script:BootStarted = $true
    try { Clear-Host } catch {}
    Write-Host ""
    Write-Host "  [ JIN CORE ENGINE // LAUNCHER ]" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  starting JIN..." -ForegroundColor DarkCyan
    Write-Host ""
}

function Write-BootLine {
    param(
        [string]$Label,
        [string]$Text,
        [ValidateSet("WORK", "OK", "WARN", "ERROR")]
        [string]$State = "WORK"
    )

    if (-not $script:BootMode) { return }
    Start-BootScreen

    $color = switch ($State) {
        "OK"    { "Green" }
        "WARN"  { "DarkYellow" }
        "ERROR" { "Red" }
        default { "Cyan" }
    }
    $glyph = switch ($State) {
        "OK"    { "+" }
        "WARN"  { "!" }
        "ERROR" { "x" }
        default { ">" }
    }

    Write-Host -NoNewline ("  {0,-8}" -f $Label) -ForegroundColor DarkCyan
    Write-Host -NoNewline (" $glyph ") -ForegroundColor $color
    Write-Host $Text -ForegroundColor $color
}

function Add-Event {
    param(
        [string]$Text,
        [byte]$Color = 7
    )

    if ([string]::IsNullOrWhiteSpace($Text)) { return }
    [void]$script:Events.Add([pscustomobject]@{
        Text = $Text.Trim()
        Color = $Color
    })
    while ($script:Events.Count -gt 80) {
        $script:Events.RemoveAt(0)
    }
    $script:DashboardDirty = $true
}

function Fail-WithMessage {
    param([string]$Message)
    throw $Message
}

function Import-DotEnv {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) { return }

    foreach ($line in [System.IO.File]::ReadAllLines($Path)) {
        $candidate = $line.Trim()
        if ($candidate.Length -eq 0 -or $candidate.StartsWith("#")) { continue }
        if ($candidate.StartsWith("export ", [System.StringComparison]::OrdinalIgnoreCase)) {
            $candidate = $candidate.Substring(7).TrimStart()
        }

        $separatorIndex = $candidate.IndexOf("=")
        if ($separatorIndex -le 0) { continue }

        $name = $candidate.Substring(0, $separatorIndex).Trim()
        $value = $candidate.Substring($separatorIndex + 1).Trim()
        if ($name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { continue }

        if ($value.Length -ge 2 -and (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        )) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        if ($null -eq [Environment]::GetEnvironmentVariable($name, "Process")) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Normalize-BaseUrl {
    param([string]$BaseUrl)
    if ($null -eq $BaseUrl) { return "" }
    return $BaseUrl.Trim().TrimEnd("/")
}

function Ensure-JinConfig {
    if (Test-Path -LiteralPath $ConfigPath) { return }
    if (-not (Test-Path -LiteralPath $ConfigExamplePath)) {
        Fail-WithMessage "Cannot find config.py or config.example.py."
    }
    Copy-Item -LiteralPath $ConfigExamplePath -Destination $ConfigPath
    Add-Event "CONFIG  created config.py from template" 3
}

function Get-PythonConfigValue {
    param([string]$Name)

    if (-not (Test-Path -LiteralPath $ConfigPath)) { return $null }
    $content = Get-Content -Raw -LiteralPath $ConfigPath
    $match = [regex]::Match($content, "(?m)^\s*$Name\s*=\s*(?<value>.*?)(?:\s+#.*)?$")
    if (-not $match.Success) { return $null }

    $rawValue = $match.Groups["value"].Value.Trim()
    if ($rawValue -match '^"(.*)"$') { return $Matches[1] }
    if ($rawValue -match "^'(.*)'$") { return $Matches[1] }
    if ($rawValue -in @("None", '$null')) { return "" }
    return $rawValue
}


function Get-PositiveIntValue {
    param(
        $Object,
        [string[]]$Names
    )

    if ($null -eq $Object) { return 0 }
    foreach ($name in $Names) {
        if ($Object.PSObject.Properties.Name -contains $name) {
            try {
                $value = [long]$Object.$name
                if ($value -gt 0) { return [int]$value }
            }
            catch {}
        }
    }
    return 0
}

function Get-LoadedContextFromModelItem {
    param($Item)

    if ($null -eq $Item) { return 0 }

    if ($Item.PSObject.Properties.Name -contains "loaded_instances") {
        foreach ($instance in @($Item.loaded_instances)) {
            if ($null -eq $instance) { continue }

            $value = Get-PositiveIntValue $instance @(
                "loaded_context_length",
                "context_length",
                "context_window",
                "n_ctx",
                "num_ctx"
            )
            if ($value -gt 0) { return $value }

            if (
                $instance.PSObject.Properties.Name -contains "config" -and
                $null -ne $instance.config
            ) {
                $value = Get-PositiveIntValue $instance.config @(
                    "loaded_context_length",
                    "context_length",
                    "context_window",
                    "n_ctx",
                    "num_ctx"
                )
                if ($value -gt 0) { return $value }
            }
        }
    }

    return 0
}

function Format-ContextTokens {
    param([int]$Value)

    if ($Value -le 0) { return "?" }
    if (($Value % 1048576) -eq 0) {
        return ([int]($Value / 1048576)).ToString() + "M"
    }
    if (($Value % 1024) -eq 0) {
        return ([int]($Value / 1024)).ToString() + "K"
    }
    return [string]$Value
}

function Get-ContextOptions {
    param([int]$MaxContext)

    if ($MaxContext -le 0) { return @() }

    $values = New-Object System.Collections.ArrayList
    $value = 4096
    while ($value -le $MaxContext -and $value -gt 0) {
        [void]$values.Add([int]$value)
        if ($value -gt 1073741823) { break }
        $value = $value * 2
    }

    if ($values.Count -eq 0 -or [int]$values[$values.Count - 1] -ne $MaxContext) {
        [void]$values.Add([int]$MaxContext)
    }

    return @($values | Sort-Object -Unique)
}

function Set-PythonConfigValue {
    param(
        [string]$Name,
        [object]$Value
    )

    $content = Get-Content -Raw -LiteralPath $ConfigPath
    if ($Value -is [bool]) {
        $renderedValue = if ($Value) { "True" } else { "False" }
    }
    elseif ($Value -is [int] -or $Value -is [double]) {
        $renderedValue = [string]$Value
    }
    else {
        $escaped = ([string]$Value).Replace("\", "\\").Replace('"', '\"')
        $renderedValue = '"' + $escaped + '"'
    }

    $pattern = "(?m)^\s*$Name\s*=.*$"
    $replacement = "$Name = $renderedValue"
    $safeReplacement = $replacement.Replace('$', '$$')

    if ([regex]::IsMatch($content, $pattern)) {
        $content = [regex]::Replace($content, $pattern, $safeReplacement, 1)
    }
    else {
        $content = $content.TrimEnd() + "`r`n`r`n" + $replacement + "`r`n"
    }

    Set-Content -LiteralPath $ConfigPath -Value $content -Encoding UTF8
}

function Test-AutoModelValue {
    param([string]$Value)
    $normalized = [string]$Value
    if ([string]::IsNullOrWhiteSpace($normalized)) { return $true }
    return $normalized.Trim() -in @("brain-model", "service-model")
}

function Test-AutoBaseValue {
    param(
        [string]$Name,
        [string]$Value
    )
    if ([string]::IsNullOrWhiteSpace([string]$Value)) { return $true }
    $normalized = (Normalize-BaseUrl $Value).ToLowerInvariant()
    if ($Name -eq "BRAIN_API_BASE") { return $normalized -eq "http://brain-host:1234" }
    if ($Name -eq "SERVICE_API_BASE") { return $normalized -eq "http://service-host:1234" }
    return $false
}

function Get-ModelRecords {
    param($Payload)

    $items = @()
    if ($null -eq $Payload) { return @() }

    if ($Payload.PSObject.Properties.Name -contains "models") {
        $items = @($Payload.models)
    }
    elseif ($Payload.PSObject.Properties.Name -contains "data") {
        $items = @($Payload.data)
    }
    else {
        $items = @($Payload)
    }

    $seen = @{}
    $records = New-Object System.Collections.ArrayList
    foreach ($item in $items) {
        if ($null -eq $item) { continue }

        $id = ""
        $loaded = $false
        $modelType = ""
        $maxContext = 0
        $loadedContext = 0

        if ($item -is [string]) {
            $id = $item.Trim()
        }
        else {
            foreach ($field in @("id", "key", "model", "name")) {
                if ($item.PSObject.Properties.Name -contains $field) {
                    $candidate = [string]$item.$field
                    if (-not [string]::IsNullOrWhiteSpace($candidate)) {
                        $id = $candidate.Trim()
                        break
                    }
                }
            }

            foreach ($field in @("type", "model_type")) {
                if ($item.PSObject.Properties.Name -contains $field) {
                    $modelType = [string]$item.$field
                    if ($modelType) { break }
                }
            }

            $maxContext = Get-PositiveIntValue $item @(
                "max_context_length",
                "max_context_window",
                "max_position_embeddings"
            )

            if ($item.PSObject.Properties.Name -contains "loaded_instances") {
                $loaded = @($item.loaded_instances).Count -gt 0
                if ($loaded) {
                    $loadedContext = Get-LoadedContextFromModelItem $item
                }
            }
            elseif ($item.PSObject.Properties.Name -contains "state") {
                $loaded = ([string]$item.state).ToLowerInvariant() -eq "loaded"
            }

            if ($loaded -and $loadedContext -le 0) {
                $loadedContext = Get-PositiveIntValue $item @(
                    "loaded_context_length",
                    "context_length",
                    "context_window",
                    "n_ctx",
                    "num_ctx"
                )
            }
        }

        if ([string]::IsNullOrWhiteSpace($id)) { continue }
        if ($modelType.ToLowerInvariant() -in @("embedding", "embeddings")) { continue }
        if ($seen.ContainsKey($id)) { continue }
        $seen[$id] = $true

        [void]$records.Add([pscustomobject]@{
            Id = $id
            Loaded = $loaded
            MaxContext = [int]$maxContext
            LoadedContext = [int]$loadedContext
        })
    }

    return @($records | Sort-Object -Property Id)
}

function Get-EndpointState {
    param(
        [string]$Role,
        [string]$BaseUrl,
        [string]$SelectedModel
    )

    $base = Normalize-BaseUrl $BaseUrl
    if ([string]::IsNullOrWhiteSpace($base)) {
        return [pscustomobject]@{
            Role = $Role
            BaseUrl = ""
            Online = $false
            Models = @()
            Selected = $SelectedModel
            Source = ""
            Error = "not configured"
        }
    }

    $errors = New-Object System.Collections.ArrayList
    $nativeCandidates = New-Object System.Collections.ArrayList

    # LM Studio 0.4+ exposes the rich catalog at /api/v1/models. Older 0.3.x
    # installations use /api/v0/models. Both list downloaded models and expose
    # max context metadata. Probe both before falling back to OpenAI /v1/models,
    # which may only expose currently visible/loaded models depending on JIT.
    foreach ($suffix in @("/api/v1/models", "/api/v0/models")) {
        $url = "$base$suffix"
        try {
            $payload = Invoke-RestMethod -Method Get -Uri $url -TimeoutSec 1 -ErrorAction Stop
            $records = @(Get-ModelRecords $payload)
            if ($records.Count -gt 0) {
                [void]$nativeCandidates.Add([pscustomobject]@{
                    Role = $Role
                    BaseUrl = $base
                    Online = $true
                    Models = $records
                    Selected = $SelectedModel
                    Source = $suffix
                    Error = ""
                })
            }
        }
        catch {
            [void]$errors.Add($_.Exception.Message)
        }
    }

    if ($nativeCandidates.Count -gt 0) {
        # Prefer the richest native catalog. This also fixes mixed LM Studio
        # versions where one native generation returns only the loaded model.
        return @($nativeCandidates | Sort-Object @{ Expression = { @($_.Models).Count }; Descending = $true }, @{ Expression = { if ($_.Source -eq "/api/v1/models") { 1 } else { 0 } }; Descending = $true })[0]
    }

    $fallbackSuffix = "/v1/models"
    try {
        $payload = Invoke-RestMethod -Method Get -Uri "$base$fallbackSuffix" -TimeoutSec 1 -ErrorAction Stop
        return [pscustomobject]@{
            Role = $Role
            BaseUrl = $base
            Online = $true
            Models = @(Get-ModelRecords $payload)
            Selected = $SelectedModel
            Source = $fallbackSuffix
            Error = ""
        }
    }
    catch {
        [void]$errors.Add($_.Exception.Message)
    }

    return [pscustomobject]@{
        Role = $Role
        BaseUrl = $base
        Online = $false
        Models = @()
        Selected = $SelectedModel
        Source = ""
        Error = ((@($errors) | Select-Object -First 1) -join "")
    }
}

function Refresh-Runtimes {
    $script:BrainTemperature = [string](Get-PythonConfigValue "BRAIN_TEMPERATURE")
    if ([string]::IsNullOrWhiteSpace($script:BrainTemperature)) { $script:BrainTemperature = "?" }
    $script:ServiceTemperature = [string](Get-PythonConfigValue "SERVICE_TEMPERATURE")
    if ([string]::IsNullOrWhiteSpace($script:ServiceTemperature)) { $script:ServiceTemperature = "?" }
    $script:RuntimeLogsEnabled = [string](Get-PythonConfigValue "ENABLE_RUNTIME_LOGS")
    if ([string]::IsNullOrWhiteSpace($script:RuntimeLogsEnabled)) { $script:RuntimeLogsEnabled = "?" }

    $brainBase = [string](Get-PythonConfigValue "BRAIN_API_BASE")
    if (Test-AutoBaseValue "BRAIN_API_BASE" $brainBase) {
        $candidate = Normalize-BaseUrl $LmStudioBaseUrl
        $probe = Get-EndpointState "brain" $candidate ""
        if ($probe.Online) {
            $brainBase = $candidate
            Set-PythonConfigValue "BRAIN_API_BASE" $brainBase
        }
        elseif ([string]::IsNullOrWhiteSpace($brainBase) -or $brainBase -eq "http://brain-host:1234") {
            $brainBase = $candidate
        }
    }

    $brainSelected = [string](Get-PythonConfigValue "BRAIN_MODEL_UID")
    if (Test-AutoModelValue $brainSelected) { $brainSelected = "" }

    $serviceBase = [string](Get-PythonConfigValue "SERVICE_API_BASE")
    if (Test-AutoBaseValue "SERVICE_API_BASE" $serviceBase) { $serviceBase = "" }
    $serviceSelected = [string](Get-PythonConfigValue "SERVICE_MODEL_UID")
    if (Test-AutoModelValue $serviceSelected) { $serviceSelected = "" }

    if ($script:BootMode) { Write-BootLine "BRAIN" ("probing " + (Normalize-BaseUrl $brainBase)) "WORK" }
    $script:BrainRuntime = Get-EndpointState "brain" $brainBase $brainSelected
    if ($script:BootMode) {
        if ($script:BrainRuntime.Online) {
            Write-BootLine "BRAIN" ((@($script:BrainRuntime.Models).Count).ToString() + " model(s) available") "OK"
        }
        else {
            Write-BootLine "BRAIN" "endpoint unavailable" "WARN"
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($serviceBase)) {
        if ($script:BootMode) { Write-BootLine "SERVICE" ("probing " + (Normalize-BaseUrl $serviceBase)) "WORK" }
        $script:ServiceRuntime = Get-EndpointState "service" $serviceBase $serviceSelected
        $script:ServiceConfigured = $true
        if ($script:BootMode) {
            if ($script:ServiceRuntime.Online) {
                Write-BootLine "SERVICE" ((@($script:ServiceRuntime.Models).Count).ToString() + " model(s) available") "OK"
            }
            else {
                Write-BootLine "SERVICE" "endpoint unavailable" "WARN"
            }
        }
    }
    else {
        $script:ServiceRuntime = [pscustomobject]@{
            Role = "service"
            BaseUrl = ""
            Online = $script:BrainRuntime.Online
            Models = @()
            Selected = $brainSelected
            Source = "brain fallback"
            Error = ""
        }
        $script:ServiceConfigured = $false
        if ($script:BootMode) { Write-BootLine "SERVICE" "using Brain fallback" "OK" }
    }
}

function Test-PythonCommand {
    param(
        [string]$Executable,
        [string[]]$Arguments = @()
    )
    try {
        $versionOutput = & $Executable @Arguments --version 2>&1
        $versionText = (@($versionOutput) -join " ").Trim()
        return ($LASTEXITCODE -eq 0 -and $versionText -match '^Python 3(?:\.|\s|$)')
    }
    catch { return $false }
}

function Get-PythonCommand {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py -and (Test-PythonCommand -Executable $py.Source -Arguments @("-3"))) {
        return @($py.Source, "-3")
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and (Test-PythonCommand -Executable $python.Source)) {
        return @($python.Source)
    }
    Fail-WithMessage "A working Python 3 installation was not found."
}

function Ensure-Dependencies {
    $venvPath = Join-Path $Root ".venv"
    $venvPython = Join-Path $venvPath "Scripts\python.exe"
    $requirementsPath = Join-Path $Root "requirements.txt"
    $markerPath = Join-Path $venvPath ".jin_requirements.sha256"
    $created = $false

    if (-not (Test-Path -LiteralPath $venvPython)) {
        $script:RuntimeMessage = "CREATING PYTHON RUNTIME"
        Write-BootLine "PYTHON" "creating local .venv" "WORK"
        $pythonCommand = @(Get-PythonCommand)
        $pythonExe = $pythonCommand[0]
        $pythonArgs = @()
        if ($pythonCommand.Length -gt 1) {
            $pythonArgs += $pythonCommand[1..($pythonCommand.Length - 1)]
        }
        & $pythonExe @pythonArgs -m venv $venvPath
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython)) {
            Fail-WithMessage "Python failed to create .venv."
        }
        $created = $true
    }

    if (-not (Test-Path -LiteralPath $requirementsPath)) {
        Fail-WithMessage "requirements.txt is missing."
    }

    $hash = (Get-FileHash -LiteralPath $requirementsPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $cachedHash = ""
    if (Test-Path -LiteralPath $markerPath) {
        $cachedHash = (Get-Content -Raw -LiteralPath $markerPath).Trim().ToLowerInvariant()
    }

    # Existing JIN installs already have a populated .venv. The launcher hash marker
    # is launcher metadata, not proof that dependencies are missing. On the first
    # launcher run, adopt the current requirements hash silently instead of doing
    # a needless pip reinstall. Future requirements.txt changes still trigger sync.
    if (-not $created -and [string]::IsNullOrWhiteSpace($cachedHash)) {
        Set-Content -LiteralPath $markerPath -Value $hash -Encoding ASCII
        return [pscustomobject]@{ Python = $venvPython; State = "CACHED" }
    }

    if ($created -or $cachedHash -ne $hash) {
        $script:RuntimeMessage = "SYNCING PYTHON DEPENDENCIES"
        $installLog = Join-Path $LauncherDir "pip-install.log"
        & $venvPython -m pip install --disable-pip-version-check --no-input -r $requirementsPath *> $installLog
        if ($LASTEXITCODE -ne 0) {
            $tail = ""
            if (Test-Path -LiteralPath $installLog) {
                $tail = (@(Get-Content -LiteralPath $installLog -Tail 30) -join "`r`n")
            }
            Fail-WithMessage "Dependency install failed.`r`n$tail"
        }
        Set-Content -LiteralPath $markerPath -Value $hash -Encoding ASCII
        return [pscustomobject]@{ Python = $venvPython; State = "SYNCED" }
    }

    return [pscustomobject]@{ Python = $venvPython; State = "CACHED" }
}

function Test-AppReady {
    try {
        $response = Invoke-WebRequest -Uri "$($AppUrl.TrimEnd('/'))/api/status" -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    }
    catch { return $false }
}

function Test-AppReadyFast {
    # Hot-loop readiness probe. The old HTTP probe could block the whole UI for
    # up to one second every 0.8 s while the backend was starting. A tiny TCP
    # connect is enough here: uvicorn opens the listener when it can accept work.
    $client = $null
    try {
        $uri = [Uri]$AppUrl
        $port = if ($uri.IsDefaultPort) {
            if ($uri.Scheme -eq "https") { 443 } else { 80 }
        }
        else {
            $uri.Port
        }

        $client = New-Object System.Net.Sockets.TcpClient
        $task = $client.ConnectAsync($uri.Host, [int]$port)
        if (-not $task.Wait(20)) { return $false }
        return [bool]$client.Connected
    }
    catch {
        return $false
    }
    finally {
        if ($client) {
            try { $client.Close() } catch {}
        }
    }
}

function Start-JinBackend {
    param([string]$PythonExe)

    if (Test-AppReady) {
        $script:BackendOwned = $false
        return
    }

    if ($script:BackendProcess -and -not $script:BackendProcess.HasExited) { return }

    Remove-Item -LiteralPath $StdOutPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $StdErrPath -Force -ErrorAction SilentlyContinue
    $script:StdOutPosition = 0L
    $script:StdErrPosition = 0L

    $env:JIN_LAUNCHER_TRACE = "1"
    $env:PYTHONUNBUFFERED = "1"

    $startParams = @{
        FilePath = $PythonExe
        ArgumentList = @("-u", (Join-Path $Root "app.py"))
        WorkingDirectory = $Root
        NoNewWindow = $true
        RedirectStandardOutput = $StdOutPath
        RedirectStandardError = $StdErrPath
        PassThru = $true
    }
    $script:BackendProcess = Start-Process @startParams
    $script:BackendOwned = $true
}

function Stop-JinBackend {
    if (-not $script:BackendOwned) { return }
    if ($script:BackendProcess -and -not $script:BackendProcess.HasExited) {
        try { Stop-Process -Id $script:BackendProcess.Id -Force -ErrorAction SilentlyContinue } catch {}
    }
}

function Get-JinPageTitle {
    # Windows PowerShell's web cmdlet can paint its progress UI directly into
    # the dashboard's cursor-addressed console buffer. Suppress that host UI so
    # probing the browser title cannot recolor or overwrite dashboard cells.
    $ProgressPreference = "SilentlyContinue"
    try {
        $response = Invoke-WebRequest -Uri $AppUrl -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        $content = [string]$response.Content
        $match = [regex]::Match($content, '(?is)<title[^>]*>(?<title>.*?)</title>')
        if ($match.Success) {
            $title = [System.Net.WebUtility]::HtmlDecode($match.Groups["title"].Value).Trim()
            if (-not [string]::IsNullOrWhiteSpace($title)) { return $title }
        }
    }
    catch {}

    # Stable fallback for builds where the root page cannot be read yet.
    return "JIN"
}

function Test-JinBrowserTabOpen {
    # Start-Process URL always creates another tab. Before doing that, inspect the
    # accessibility tree of common desktop browsers and look for the JIN page by
    # its real HTML <title>. This survives launcher restarts, unlike BrowserOpened.
    $pageTitle = Get-JinPageTitle
    if ([string]::IsNullOrWhiteSpace($pageTitle)) { return $false }

    try {
        Add-Type -AssemblyName UIAutomationClient -ErrorAction Stop
        Add-Type -AssemblyName UIAutomationTypes -ErrorAction Stop
    }
    catch {
        # UI Automation is a best-effort guard. If it is unavailable, keep the
        # old launcher behaviour rather than blocking browser opening entirely.
        return $false
    }

    $browserProcessNames = @(
        "chrome",
        "msedge",
        "brave",
        "firefox",
        "vivaldi",
        "opera"
    )

    $controlTypeProperty = [System.Windows.Automation.AutomationElement]::ControlTypeProperty
    $tabItemType = [System.Windows.Automation.ControlType]::TabItem
    $tabCondition = New-Object System.Windows.Automation.PropertyCondition -ArgumentList @(
        $controlTypeProperty,
        $tabItemType
    )

    foreach ($processName in $browserProcessNames) {
        foreach ($process in @(Get-Process -Name $processName -ErrorAction SilentlyContinue)) {
            if ($process.MainWindowHandle -eq 0) { continue }

            try {
                $window = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
                if ($null -eq $window) { continue }

                # Fast path: JIN is already the active tab in this browser window.
                $windowName = [string]$window.Current.Name
                if (
                    -not [string]::IsNullOrWhiteSpace($windowName) -and
                    $windowName.IndexOf($pageTitle, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
                ) {
                    return $true
                }

                # Chromium/Firefox expose background tabs as TabItem elements, so
                # this also catches a JIN tab that is open but not currently active.
                $tabs = $window.FindAll(
                    [System.Windows.Automation.TreeScope]::Descendants,
                    $tabCondition
                )
                foreach ($tab in $tabs) {
                    $tabName = [string]$tab.Current.Name
                    if (
                        -not [string]::IsNullOrWhiteSpace($tabName) -and
                        $tabName.IndexOf($pageTitle, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
                    ) {
                        return $true
                    }
                }
            }
            catch {
                # A browser may deny accessibility for one window/process. Keep
                # checking the others instead of failing the launcher.
                continue
            }
        }
    }

    return $false
}

function Open-JinBrowser {
    if ($script:BrowserOpened) { return }

    try {
        if (Test-JinBrowserTabOpen) {
            $script:BrowserOpened = $true
            Add-Event "UI      existing JIN browser tab detected" 10
            return
        }

        Start-Process $AppUrl | Out-Null
        $script:BrowserOpened = $true
    }
    catch {
        Add-Event ("UI      could not open browser // " + $_.Exception.Message) 6
    }
}

function Read-LogDelta {
    param(
        [string]$Path,
        [long]$Position,
        [switch]$ErrorStream
    )

    if (-not (Test-Path -LiteralPath $Path)) { return $Position }

    $newPosition = $Position
    $text = ""
    try {
        $file = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try {
            if ($Position -gt $file.Length) { $Position = 0L }
            [void]$file.Seek($Position, [System.IO.SeekOrigin]::Begin)
            $reader = New-Object System.IO.StreamReader($file)
            try {
                $text = $reader.ReadToEnd()
                $newPosition = $file.Length
            }
            finally { $reader.Dispose() }
        }
        finally { $file.Dispose() }
    }
    catch { return $Position }

    if ([string]::IsNullOrWhiteSpace($text)) { return $newPosition }

    foreach ($rawLine in ($text -split "`r?`n")) {
        $line = $rawLine.Trim()
        if (-not $line) { continue }

        if ($line.StartsWith("JIN_TRACE|")) {
            $parts = $line.Split('|')
            if ($parts.Count -lt 7) { continue }
            $time = $parts[1]
            $direction = $parts[2]
            $phase = $parts[3]
            $target = $parts[4]

            if ($phase -eq ">") {
                $method = $parts[5]
                $pathText = $parts[6]
                $arrow = if ($direction -eq "OUT") { ">>" } else { "> " }
                Add-Event ("$time  $arrow $target  $method $pathText") 2
            }
            elseif ($phase -eq "<" -and $parts.Count -ge 9) {
                $status = $parts[5]
                $method = $parts[6]
                $pathText = $parts[7]
                $elapsed = $parts[8]
                $color = 10
                try {
                    if ([int]$status -ge 400) { $color = 6 }
                    if ([int]$status -ge 500) { $color = 9 }
                }
                catch {}
                $arrow = if ($direction -eq "OUT") { "<<" } else { "< " }
                Add-Event ("$time  $arrow $target  $status $method $pathText  $elapsed") $color
            }
            else {
                Add-Event ("$time  !! $target  " + (($parts | Select-Object -Skip 5) -join " ")) 9
            }
            continue
        }

        if ($ErrorStream -or $line -match '(?i)error|exception|traceback|failed') {
            if ($line.Length -gt 180) { $line = $line.Substring(0, 177) + "..." }
            Add-Event ("ERR     " + $line) 9
        }
    }

    return $newPosition
}

function Get-ModelIndex {
    param(
        $Runtime,
        [string]$ModelId
    )
    $models = @($Runtime.Models)
    for ($i = 0; $i -lt $models.Count; $i++) {
        if ([string]$models[$i].Id -eq $ModelId) { return $i }
    }
    return 0
}

function Clamp-Cursor {
    param(
        [string]$Role,
        $Runtime
    )
    $count = @($Runtime.Models).Count
    if ($count -le 0) {
        $script:CursorByRole[$Role] = 0
        return
    }
    $value = [int]$script:CursorByRole[$Role]
    if ($value -lt 0) { $value = 0 }
    if ($value -ge $count) { $value = $count - 1 }
    $script:CursorByRole[$Role] = $value
}

function Sync-CursorsToSelected {
    $script:CursorByRole["brain"] = Get-ModelIndex $script:BrainRuntime $script:BrainRuntime.Selected
    if ($script:ServiceConfigured) {
        $script:CursorByRole["service"] = Get-ModelIndex $script:ServiceRuntime $script:ServiceRuntime.Selected
    }
    Clamp-Cursor "brain" $script:BrainRuntime
    Clamp-Cursor "service" $script:ServiceRuntime
}


function Get-CursorModel {
    param(
        [string]$Role,
        $Runtime
    )

    $models = @($Runtime.Models)
    if ($models.Count -eq 0) { return $null }

    $index = [int]$script:CursorByRole[$Role]
    if ($index -lt 0) { $index = 0 }
    if ($index -ge $models.Count) { $index = $models.Count - 1 }
    return $models[$index]
}

function Get-NearestContextIndex {
    param(
        [object[]]$Options,
        [int]$Desired
    )

    if ($Options.Count -eq 0) { return 0 }

    $best = 0
    for ($i = 0; $i -lt $Options.Count; $i++) {
        if ([int]$Options[$i] -le $Desired) {
            $best = $i
        }
        else {
            break
        }
    }
    return $best
}

function Open-ContextPicker {
    if ($script:SwitchJob) {
        Add-Event "CONTEXT model switch already in progress" 6
        return
    }

    $role = $script:ActiveRole
    if ($role -eq "service" -and -not $script:ServiceConfigured) {
        Add-Event "CONTEXT Service uses the Brain model window" 7
        return
    }

    $runtime = if ($role -eq "brain") { $script:BrainRuntime } else { $script:ServiceRuntime }
    $model = Get-CursorModel $role $runtime
    if ($null -eq $model) {
        Add-Event ("CONTEXT " + $role.ToUpperInvariant() + " has no model selected") 6
        return
    }

    $maxContext = [int]$model.MaxContext
    if ($maxContext -le 0) {
        Add-Event ("CONTEXT max window is unknown for " + [string]$model.Id) 6
        return
    }

    $options = @(Get-ContextOptions $maxContext)
    if ($options.Count -eq 0) { return }

    $desired = [int]$model.LoadedContext
    if ($desired -le 0) {
        $desired = [Math]::Min(16384, $maxContext)
    }

    $script:ContextMode = $true
    $script:ContextRole = $role
    $script:ContextModel = [string]$model.Id
    $script:ContextOptions = $options
    $script:ContextIndex = Get-NearestContextIndex $options $desired
}

function Close-ContextPicker {
    $script:ContextMode = $false
    $script:ContextRole = ""
    $script:ContextModel = ""
    $script:ContextOptions = @()
    $script:ContextIndex = 0
}

function Move-ContextCursor {
    param([int]$Delta)

    $options = @($script:ContextOptions)
    if ($options.Count -eq 0) { return }

    $next = [int]$script:ContextIndex + $Delta
    if ($next -lt 0) { $next = 0 }
    if ($next -ge $options.Count) { $next = $options.Count - 1 }
    $script:ContextIndex = $next
}

function Format-ContextPickerText {
    $options = @($script:ContextOptions)
    if ($options.Count -eq 0) { return "CTX // unavailable" }

    $index = [int]$script:ContextIndex
    if ($index -lt 0) { $index = 0 }
    if ($index -ge $options.Count) { $index = $options.Count - 1 }

    $visible = 5
    $start = [Math]::Max(0, $index - 2)
    if (($start + $visible) -gt $options.Count) {
        $start = [Math]::Max(0, $options.Count - $visible)
    }
    $end = [Math]::Min($options.Count, $start + $visible)

    $parts = @()
    for ($i = $start; $i -lt $end; $i++) {
        $token = Format-ContextTokens ([int]$options[$i])
        if ($i -eq $index) { $token = "[" + $token + "]" }
        $parts += $token
    }

    $left = if ($index -gt 0) { "<" } else { " " }
    $right = if ($index -lt ($options.Count - 1)) { ">" } else { " " }
    return ("CTX // " + $left + " " + ($parts -join "  ") + " " + $right)
}

function Read-LauncherKeyName {
    param([double]$Now)

    $keyMap = @(
        @{ Code = 0x26; Name = "UpArrow"; Repeat = $true },
        @{ Code = 0x28; Name = "DownArrow"; Repeat = $true },
        @{ Code = 0x25; Name = "LeftArrow"; Repeat = $true },
        @{ Code = 0x27; Name = "RightArrow"; Repeat = $true },
        @{ Code = 0x0D; Name = "Enter"; Repeat = $false },
        @{ Code = 0x09; Name = "Tab"; Repeat = $false },
        @{ Code = 0x43; Name = "C"; Repeat = $false },
        @{ Code = 0x52; Name = "R"; Repeat = $false },
        @{ Code = 0x4F; Name = "O"; Repeat = $false },
        @{ Code = 0x51; Name = "Q"; Repeat = $false },
        @{ Code = 0x1B; Name = "Escape"; Repeat = $false }
    )

    $consoleWindow = [JinConsoleVT]::GetConsoleWindow()
    $foregroundWindow = [JinConsoleVT]::GetForegroundWindow()
    $consoleFocused = (
        $consoleWindow -ne [IntPtr]::Zero -and
        $foregroundWindow -eq $consoleWindow
    )

    if ($consoleFocused) {
        $candidate = ""
        foreach ($entry in $keyMap) {
            $code = [int]$entry.Code
            $stateKey = [string]$code
            $down = (([int][JinConsoleVT]::GetAsyncKeyState($code) -band 0x8000) -ne 0)

            if (-not $script:KeyRepeatState.ContainsKey($stateKey)) {
                $script:KeyRepeatState[$stateKey] = @{ Down = $false; Next = 0.0 }
            }
            $state = $script:KeyRepeatState[$stateKey]
            $wasDown = [bool]$state.Down

            if ($down) {
                if (-not $wasDown) {
                    if ([string]::IsNullOrWhiteSpace($candidate)) { $candidate = [string]$entry.Name }
                    $state.Next = $Now + 0.17
                }
                elseif ([bool]$entry.Repeat -and $Now -ge [double]$state.Next) {
                    if ([string]::IsNullOrWhiteSpace($candidate)) { $candidate = [string]$entry.Name }
                    $state.Next = $Now + 0.045
                }
            }
            else {
                $state.Next = 0.0
            }
            $state.Down = $down
        }
        return $candidate
    }

    try {
        if ([Console]::KeyAvailable) {
            return [Console]::ReadKey($true).Key.ToString()
        }
    }
    catch {}

    try {
        if ($Host.UI.RawUI.KeyAvailable) {
            $readOptions = (
                [System.Management.Automation.Host.ReadKeyOptions]::NoEcho -bor
                [System.Management.Automation.Host.ReadKeyOptions]::IncludeKeyDown
            )
            $rawKey = $Host.UI.RawUI.ReadKey($readOptions)
            foreach ($entry in $keyMap) {
                if ([int]$entry.Code -eq [int]$rawKey.VirtualKeyCode) { return [string]$entry.Name }
            }
        }
    }
    catch {}

    return ""
}

function Test-LauncherConfigReady {
    if ([string]::IsNullOrWhiteSpace([string]$script:BrainRuntime.Selected)) {
        return $false
    }
    if (
        $script:ServiceConfigured -and
        $script:ServiceRuntime.Online -and
        [string]::IsNullOrWhiteSpace([string]$script:ServiceRuntime.Selected)
    ) {
        return $false
    }
    return $true
}

function Start-ModelSwitch {
    param(
        [string]$Role,
        $Runtime,
        [int]$ContextLength = 0
    )

    if ($script:SwitchJob) {
        Add-Event "MODEL   switch already in progress" 6
        return
    }

    $models = @($Runtime.Models)
    if ($models.Count -eq 0) {
        Add-Event (("MODEL   " + $Role.ToUpperInvariant()) + " has no available models") 6
        return
    }

    $index = [int]$script:CursorByRole[$Role]
    if ($index -lt 0 -or $index -ge $models.Count) { return }
    $model = $models[$index]
    $modelId = [string]$model.Id
    $loadedContext = [int]$model.LoadedContext

    if (
        $modelId -eq [string]$Runtime.Selected -and
        [bool]$model.Loaded -and
        (
            $ContextLength -le 0 -or
            $loadedContext -eq $ContextLength
        )
    ) {
        $suffix = ""
        if ($loadedContext -gt 0) {
            $suffix = " @ " + (Format-ContextTokens $loadedContext)
        }
        Add-Event (("MODEL   " + $Role.ToUpperInvariant()) + " already uses " + $modelId + $suffix) 7
        return
    }

    if (Test-AppReady) {
        $script:SwitchRole = $Role
        $script:SwitchModel = $modelId
        $script:SwitchContext = $ContextLength

        $payloadData = @{
            role = $Role
            model = $modelId
            base_url = [string]$Runtime.BaseUrl
        }
        if ($ContextLength -gt 0) {
            $payloadData["load_config"] = @{
                context_length = $ContextLength
            }
        }
        $payload = $payloadData | ConvertTo-Json -Depth 4 -Compress

        $contextSuffix = ""
        if ($ContextLength -gt 0) {
            $contextSuffix = " @ " + (Format-ContextTokens $ContextLength)
        }
        Add-Event (("MODEL   switching " + $Role.ToUpperInvariant()) + " -> " + $modelId + $contextSuffix) 4
        $script:SwitchJob = Start-Job -ScriptBlock {
            param($Url, $Body)
            Invoke-RestMethod -Method Post -Uri "$($Url.TrimEnd('/'))/api/runtime-model/switch" -ContentType "application/json" -Body $Body -TimeoutSec 1000 -ErrorAction Stop | Out-Null
            return "OK"
        } -ArgumentList $AppUrl, $payload
        return
    }

    $field = if ($Role -eq "brain") { "BRAIN_MODEL_UID" } else { "SERVICE_MODEL_UID" }
    Set-PythonConfigValue $field $modelId
    Add-Event (("MODEL   selected " + $Role.ToUpperInvariant()) + " -> " + $modelId) 10

    if ($ContextLength -gt 0) {
        $script:PendingContextApply = [pscustomobject]@{
            Role = $Role
            Model = $modelId
            ContextLength = $ContextLength
        }
        Add-Event (("CONTEXT queued " + $Role.ToUpperInvariant()) + " -> " + (Format-ContextTokens $ContextLength)) 3
    }

    Refresh-Runtimes
    Sync-CursorsToSelected
    if (Test-LauncherConfigReady) {
        Start-JinBackend $script:PythonExe
    }
    elseif ($Role -eq "brain" -and $script:ServiceConfigured -and $script:ServiceRuntime.Online -and [string]::IsNullOrWhiteSpace([string]$script:ServiceRuntime.Selected)) {
        $script:ActiveRole = "service"
        Add-Event "SERVICE choose a model and press ENTER" 6
    }
}

function Poll-ModelSwitch {
    if (-not $script:SwitchJob) { return }
    if ($script:SwitchJob.State -eq "Running" -or $script:SwitchJob.State -eq "NotStarted") { return }

    if ($script:SwitchJob.State -eq "Completed") {
        try {
            [void](Receive-Job $script:SwitchJob -ErrorAction Stop)
            $contextSuffix = ""
            if ($script:SwitchContext -gt 0) {
                $contextSuffix = " @ " + (Format-ContextTokens $script:SwitchContext)
            }
            Add-Event (("MODEL   " + $script:SwitchRole.ToUpperInvariant()) + " active -> " + $script:SwitchModel + $contextSuffix) 10
        }
        catch {
            Add-Event ("MODEL   switch failed // " + $_.Exception.Message) 9
        }
    }
    else {
        $reason = ""
        try { $reason = [string]$script:SwitchJob.ChildJobs[0].JobStateInfo.Reason.Message } catch {}
        if (-not $reason) { $reason = [string]$script:SwitchJob.State }
        Add-Event ("MODEL   switch failed // " + $reason) 9
    }

    Remove-Job $script:SwitchJob -Force -ErrorAction SilentlyContinue
    $script:SwitchJob = $null
    $script:SwitchRole = ""
    $script:SwitchModel = ""
    $script:SwitchContext = 0
    Refresh-Runtimes
    Sync-CursorsToSelected
}

function Put {
    param(
        [char[]]$Chars,
        [byte[]]$Cols,
        [int]$W,
        [int]$H,
        [int]$X,
        [int]$Y,
        [char]$Ch,
        [byte]$Color
    )
    if ($X -ge 0 -and $X -lt $W -and $Y -ge 0 -and $Y -lt $H) {
        $idx = $Y * $W + $X
        $Chars[$idx] = $Ch
        $Cols[$idx] = $Color
    }
}

function Put-Text {
    param(
        [char[]]$Chars,
        [byte[]]$Cols,
        [int]$W,
        [int]$H,
        [int]$X,
        [int]$Y,
        [string]$Text,
        [byte]$Color,
        [int]$MaxWidth = 999
    )
    if ($null -eq $Text) { return }
    $limit = [Math]::Min($Text.Length, $MaxWidth)
    for ($i = 0; $i -lt $limit; $i++) {
        Put $Chars $Cols $W $H ($X + $i) $Y $Text[$i] $Color
    }
}

function Draw-ContextPickerLine {
    param(
        [char[]]$Chars,
        [byte[]]$Cols,
        [int]$W,
        [int]$H,
        [int]$Y
    )

    $options = @($script:ContextOptions)
    if ($options.Count -eq 0) {
        Put-Text $Chars $Cols $W $H 4 $Y "CTX unavailable" 1 54
        return
    }

    $index = [int]$script:ContextIndex
    if ($index -lt 0) { $index = 0 }
    if ($index -ge $options.Count) { $index = $options.Count - 1 }

    $visible = 6
    $start = [Math]::Max(0, $index - 2)
    if (($start + $visible) -gt $options.Count) {
        $start = [Math]::Max(0, $options.Count - $visible)
    }
    $end = [Math]::Min($options.Count, $start + $visible)

    $x = 4
    Put-Text $Chars $Cols $W $H $x $Y "CTX" 2 4
    $x += 5
    if ($start -gt 0) { Put-Text $Chars $Cols $W $H $x $Y "‹" 1 1 }
    $x += 2

    for ($i = $start; $i -lt $end; $i++) {
        $token = Format-ContextTokens ([int]$options[$i])
        $isCurrent = ($i -eq $index)
        if ($isCurrent) { $token = "[" + $token + "]" }
        $color = if ($isCurrent) { [byte]6 } else { [byte]1 }
        Put-Text $Chars $Cols $W $H $x $Y $token $color 8
        $x += $token.Length + 2
    }

    if ($end -lt $options.Count) { Put-Text $Chars $Cols $W $H $x $Y "›" 1 1 }
}

function Draw-RolePanel {
    param(
        [char[]]$Chars,
        [byte[]]$Cols,
        [int]$W,
        [int]$H,
        [int]$Y,
        [string]$Role,
        $Runtime,
        [bool]$Configured,
        [bool]$Active
    )

    $label = $Role.ToUpperInvariant()
    $temperature = if ($Role -eq "brain") { $script:BrainTemperature } else { $script:ServiceTemperature }
    $panelRight = [Math]::Min(57, $W - 34)

    for ($x = 3; $x -le $panelRight; $x++) {
        Put $Chars $Cols $W $H $x $Y '─' 1
    }
    $labelColor = if ($Active) { [byte]4 } else { [byte]2 }
    Put-Text $Chars $Cols $W $H 4 $Y (" " + $label + " ") $labelColor 12

    if (-not $Configured -and $Role -eq "service") {
        Put-Text $Chars $Cols $W $H 4 ($Y + 1) "BRAIN FALLBACK" 1 20
        Put-Text $Chars $Cols $W $H 22 ($Y + 1) ("TEMP " + [string]$temperature) 1 12
        Put-Text $Chars $Cols $W $H 4 ($Y + 2) "uses Brain endpoint, model and context" 1 52
        return
    }

    $models = @($Runtime.Models)
    $cursor = [int]$script:CursorByRole[$Role]
    if ($cursor -lt 0) { $cursor = 0 }
    if ($models.Count -gt 0 -and $cursor -ge $models.Count) { $cursor = $models.Count - 1 }
    $focusModel = if ($models.Count -gt 0) { $models[$cursor] } else { $null }

    $selected = [string]$Runtime.Selected
    $contextModel = $null
    if ($Active -and $null -ne $focusModel) {
        $contextModel = $focusModel
    }
    elseif (-not [string]::IsNullOrWhiteSpace($selected)) {
        foreach ($candidate in $models) {
            if ([string]$candidate.Id -eq $selected) {
                $contextModel = $candidate
                break
            }
        }
    }
    if ($null -eq $contextModel) { $contextModel = $focusModel }

    $status = if ($Runtime.Online) { "ONLINE" } else { "OFFLINE" }
    $statusColor = if ($Runtime.Online) { [byte]10 } else { [byte]9 }

    # Keep status text ASCII-only here. Some Windows console/font combinations
    # render the old bullet glyph as a literal question mark.
    $x = 4
    Put-Text $Chars $Cols $W $H $x ($Y + 1) $status $statusColor 8
    $x += $status.Length + 3
    $tempText = "TEMP " + [string]$temperature
    Put-Text $Chars $Cols $W $H $x ($Y + 1) $tempText 1 12
    $x += $tempText.Length + 3

    if ($null -ne $contextModel) {
        $loadedContext = [int]$contextModel.LoadedContext
        $maxContext = [int]$contextModel.MaxContext
        $loadedText = if ($loadedContext -gt 0) { Format-ContextTokens $loadedContext } else { "--" }
        $maxText = if ($maxContext -gt 0) { Format-ContextTokens $maxContext } else { "--" }
        Put-Text $Chars $Cols $W $H $x ($Y + 1) ("CTX " + $loadedText + "/" + $maxText) 1 18
    }
    elseif ([string]::IsNullOrWhiteSpace($selected)) {
        Put-Text $Chars $Cols $W $H $x ($Y + 1) "CHOOSE MODEL" 6 18
    }

    if (
        $script:ContextMode -and
        $script:ContextRole -eq $Role -and
        $null -ne $focusModel -and
        $script:ContextModel -eq [string]$focusModel.Id
    ) {
        Draw-ContextPickerLine $Chars $Cols $W $H ($Y + 2)
    }
    else {
        $base = [string]$Runtime.BaseUrl
        Put-Text $Chars $Cols $W $H 4 ($Y + 2) "URL" 1 4
        Put-Text $Chars $Cols $W $H 9 ($Y + 2) $base 2 46
    }

    if ($models.Count -eq 0) {
        $emptyText = if ($Runtime.Online) { "no chat models returned" } else { "endpoint unavailable" }
        $emptyColor = if ($Runtime.Online) { [byte]1 } else { [byte]9 }
        Put-Text $Chars $Cols $W $H 6 ($Y + 4) $emptyText $emptyColor 48
        return
    }

    $maxRows = 5
    $start = 0
    if ($models.Count -gt $maxRows) {
        $start = $cursor - 2
        if ($start -lt 0) { $start = 0 }
        $maxStart = $models.Count - $maxRows
        if ($start -gt $maxStart) { $start = $maxStart }
    }

    $end = [Math]::Min($models.Count, $start + $maxRows)
    $row = 0
    for ($i = $start; $i -lt $end; $i++) {
        $model = $models[$i]
        $isCursor = $Active -and $i -eq $cursor
        $isSelected = [string]$model.Id -eq $selected
        $lineY = $Y + 3 + $row

        $prefixColor = if ($isCursor) { [byte]6 } else { [byte]1 }
        $textColor = if ($isSelected) { [byte]4 } elseif ($isCursor) { [byte]8 } else { [byte]1 }

        # Color carries selected/loaded state; no decorative dot/bullet column.
        $prefix = if ($isCursor) { ">" } else { " " }
        Put-Text $Chars $Cols $W $H 4 $lineY $prefix $prefixColor 1
        Put-Text $Chars $Cols $W $H 6 $lineY ([string]$model.Id) $textColor 51
        $row++
    }

    if ($models.Count -gt $maxRows) {
        Put-Text $Chars $Cols $W $H 47 ($Y + 8) ((($cursor + 1).ToString()) + "/" + $models.Count) 1 10
    }
}

function Draw-Avatar {
    param(
        [char[]]$Chars,
        [byte[]]$Cols,
        [int]$W,
        [int]$H,
        [double]$T
    )

    $frameLeft = $W - 31
    $frameRight = $W - 2
    $frameTop = 2
    $frameBottom = 20
    $cx = [int][Math]::Round(($frameLeft + $frameRight) / 2.0)
    $cy = 11

    for ($x = $frameLeft + 1; $x -lt $frameRight; $x++) {
        Put $Chars $Cols $W $H $x $frameTop '─' 1
        Put $Chars $Cols $W $H $x $frameBottom '─' 1
    }
    for ($y = $frameTop + 1; $y -lt $frameBottom; $y++) {
        Put $Chars $Cols $W $H $frameLeft $y '│' 1
        Put $Chars $Cols $W $H $frameRight $y '│' 1
    }
    Put $Chars $Cols $W $H $frameLeft $frameTop '┌' 2
    Put $Chars $Cols $W $H $frameRight $frameTop '┐' 2
    Put $Chars $Cols $W $H $frameLeft $frameBottom '└' 2
    Put $Chars $Cols $W $H $frameRight $frameBottom '┘' 2

    $rings = @(
        @{ rx = 11.5; ry = 7.2; speed =  0.31; dash = 11; gap = 5; color = 2; hot = 4 },
        @{ rx =  9.0; ry = 5.6; speed = -0.43; dash = 8;  gap = 4; color = 2; hot = 3 },
        @{ rx =  6.3; ry = 3.9; speed =  0.59; dash = 6;  gap = 3; color = 1; hot = 3 }
    )

    foreach ($ring in $rings) {
        $phase = $T * $ring.speed
        $n = 0
        for ($deg = 0; $deg -lt 360; $deg += 4) {
            $a = $deg * [Math]::PI / 180.0
            $pattern = ($n + [int]($phase * 16)) % ($ring.dash + $ring.gap)
            if ($pattern -lt $ring.dash) {
                $x = $cx + [int][Math]::Round([Math]::Cos($a) * $ring.rx)
                $y = $cy + [int][Math]::Round([Math]::Sin($a) * $ring.ry)
                $hotPhase = (($deg + $phase * 57.2958) % 360 + 360) % 360
                $color = [byte]$ring.color
                if ($hotPhase -lt 28 -or $hotPhase -gt 348) { $color = [byte]$ring.hot }
                $s = [Math]::Sin($a)
                $c = [Math]::Cos($a)
                $ch = '·'
                if ([Math]::Abs($s) -lt 0.30) { $ch = '│' }
                elseif ([Math]::Abs($c) -lt 0.30) { $ch = '─' }
                elseif (($s * $c) -gt 0) { $ch = '╱' }
                else { $ch = '╲' }
                Put $Chars $Cols $W $H $x $y $ch $color
            }
            $n++
        }
    }

    $orbit = $T * 0.72
    $ox = $cx + [int][Math]::Round([Math]::Cos($orbit) * 11.5)
    $oy = $cy + [int][Math]::Round([Math]::Sin($orbit) * 7.2)
    Put $Chars $Cols $W $H $ox $oy '●' 4

    Put-Text $Chars $Cols $W $H ($cx - 4) ($cy - 1) "╭─────╮" 3 9
    Put-Text $Chars $Cols $W $H ($cx - 4) $cy       "│  ●  │" 4 9
    Put-Text $Chars $Cols $W $H ($cx - 4) ($cy + 1) "╰─────╯" 3 9
    Put-Text $Chars $Cols $W $H ($cx - 2) ($cy + 3) "JIN" 1 5
}

function Render-Dashboard {
    param([double]$T)

    $W = [Math]::Min([Console]::WindowWidth, 92)
    $H = [Math]::Min([Console]::WindowHeight, 55)
    if ($W -lt 92 -or $H -lt 50) { return }

    $chars = New-Object char[] ($W * $H)
    $cols = New-Object byte[] ($W * $H)
    for ($i = 0; $i -lt $chars.Length; $i++) {
        $chars[$i] = [char]' '
        $cols[$i] = [byte]0
    }

    Put-Text $chars $cols $W $H 3 1 "[ JIN CORE ENGINE // LAUNCHER ]" 8 40

    Draw-RolePanel $chars $cols $W $H 3 "brain" $script:BrainRuntime $true ($script:ActiveRole -eq "brain")
    Draw-RolePanel $chars $cols $W $H 14 "service" $script:ServiceRuntime $script:ServiceConfigured ($script:ActiveRole -eq "service")
    $avatarT = [Math]::Floor($T * 4.0) / 4.0
    Draw-Avatar $chars $cols $W $H $avatarT

    for ($x = 3; $x -le 57; $x++) {
        Put $chars $cols $W $H $x 25 '─' 1
    }
    Put-Text $chars $cols $W $H 4 25 " APP " 2 8

    $appStatus = "OFFLINE"
    $appStatusColor = [byte]9
    if ($script:BackendReady) {
        $appStatus = "ONLINE"
        $appStatusColor = [byte]10
    }
    elseif ($script:BackendProcess -and -not $script:BackendProcess.HasExited) {
        $appStatus = "STARTING"
        $appStatusColor = [byte]6
    }

    $logsText = switch -Regex ([string]$script:RuntimeLogsEnabled) {
        '^(?i:true|1|yes|on)$' { "ON"; break }
        '^(?i:false|0|no|off)$' { "OFF"; break }
        default { "?" }
    }

    Put-Text $chars $cols $W $H 4 26 $appStatus $appStatusColor 10
    Put-Text $chars $cols $W $H 15 26 $AppUrl 2 31
    Put-Text $chars $cols $W $H 48 26 ("LOGS " + $logsText) 1 10

    if ($script:SwitchJob) {
        $switchText = "switching " + $script:SwitchRole + " -> " + $script:SwitchModel
        if ($script:SwitchContext -gt 0) { $switchText += " @ " + (Format-ContextTokens $script:SwitchContext) }
        Put-Text $chars $cols $W $H 4 28 "MODEL" 2 8
        Put-Text $chars $cols $W $H 11 28 $switchText 6 46
    }

    for ($x = 2; $x -lt ($W - 2); $x++) {
        Put $chars $cols $W $H $x 33 '─' 1
    }
    Put-Text $chars $cols $W $H 4 33 " RUNTIME I/O " 2 20

    $logRows = 10
    $startEvent = [Math]::Max(0, $script:Events.Count - $logRows)
    $row = 0
    for ($i = $startEvent; $i -lt $script:Events.Count; $i++) {
        $event = $script:Events[$i]
        Put-Text $chars $cols $W $H 4 (34 + $row) ([string]$event.Text) ([byte]$event.Color) ($W - 8)
        $row++
    }

    for ($x = 2; $x -lt ($W - 2); $x++) {
        Put $chars $cols $W $H $x 50 '─' 1
    }
    if ($script:ContextMode) {
        Put-Text $chars $cols $W $H 4 51 "←→ CTX   ENTER APPLY   ESC BACK" 1 ($W - 8)
    }
    else {
        Put-Text $chars $cols $W $H 4 51 "↑↓ MODEL   ←→ ROLE   ENTER APPLY   C CONTEXT   R REFRESH   Q EXIT" 1 ($W - 8)
    }

    $sb = New-Object System.Text.StringBuilder
    $fullRedraw = (
        $null -eq $script:PrevChars -or
        $null -eq $script:PrevCols -or
        $script:PrevW -ne $W -or
        $script:PrevH -ne $H
    )

    if ($fullRedraw) {
        [void]$sb.Append($clear)
        $lastColor = -1
        for ($y = 0; $y -lt $H; $y++) {
            [void]$sb.Append("$esc[$($y + 1);1H")
            for ($x = 0; $x -lt $W; $x++) {
                $idx = $y * $W + $x
                $color = [int]$cols[$idx]
                if ($color -ne $lastColor) {
                    [void]$sb.Append($ansi[$color])
                    $lastColor = $color
                }
                [void]$sb.Append($chars[$idx])
            }
        }
    }
    else {
        for ($y = 0; $y -lt $H; $y++) {
            $x = 0
            while ($x -lt $W) {
                $idx = $y * $W + $x
                $same = (
                    $chars[$idx] -eq $script:PrevChars[$idx] -and
                    $cols[$idx] -eq $script:PrevCols[$idx]
                )
                if ($same) {
                    $x++
                    continue
                }

                $runStart = $x
                [void]$sb.Append("$esc[$($y + 1);$($runStart + 1)H")
                $lastColor = -1
                while ($x -lt $W) {
                    $idx = $y * $W + $x
                    $same = (
                        $chars[$idx] -eq $script:PrevChars[$idx] -and
                        $cols[$idx] -eq $script:PrevCols[$idx]
                    )
                    if ($same) { break }

                    $color = [int]$cols[$idx]
                    if ($color -ne $lastColor) {
                        [void]$sb.Append($ansi[$color])
                        $lastColor = $color
                    }
                    [void]$sb.Append($chars[$idx])
                    $x++
                }
            }
        }
    }

    if ($sb.Length -gt 0) { [Console]::Write($sb.ToString()) }
    $script:PrevChars = [char[]]$chars.Clone()
    $script:PrevCols = [byte[]]$cols.Clone()
    $script:PrevW = $W
    $script:PrevH = $H
}

try {
    $createdNew = $false
    $LauncherMutex = New-Object System.Threading.Mutex($true, $LauncherMutexName, [ref]$createdNew)
    if (-not $createdNew) {
        Write-Host "JIN launcher is already running."
        exit 0
    }

    Set-Location $Root
    Start-BootScreen
    if (-not (Test-Path -LiteralPath $LauncherDir)) {
        [void](New-Item -ItemType Directory -Path $LauncherDir -Force)
    }

    Write-BootLine "CONFIG" "reading config.py" "WORK"
    Import-DotEnv (Join-Path $Root ".env")
    Ensure-JinConfig
    Write-BootLine "CONFIG" "runtime configuration loaded" "OK"

    Write-BootLine "PYTHON" "checking local runtime" "WORK"
    $dependency = Ensure-Dependencies
    $script:PythonExe = [string]$dependency.Python
    $script:DependencyState = [string]$dependency.State
    if ($script:DependencyState -eq "SYNCED") {
        Write-BootLine "PYTHON" "dependencies synchronized" "OK"
    }
    else {
        Write-BootLine "PYTHON" "runtime ready" "OK"
    }

    Refresh-Runtimes
    $script:CursorByRole = @{ brain = 0; service = 0 }
    Sync-CursorsToSelected

    # If Brain is unavailable but the dedicated Service endpoint is alive,
    # focus Service immediately so the cursor is visible where interaction is possible.
    $script:ActiveRole = "brain"
    if (
        (-not $script:BrainRuntime.Online -or @($script:BrainRuntime.Models).Count -eq 0) -and
        $script:ServiceConfigured -and
        $script:ServiceRuntime.Online -and
        @($script:ServiceRuntime.Models).Count -gt 0
    ) {
        $script:ActiveRole = "service"
    }

    if (Test-LauncherConfigReady) {
        Write-BootLine "APP" ("starting " + $AppUrl) "WORK"
        Start-JinBackend $script:PythonExe
        if ($script:BackendOwned) {
            Write-BootLine "APP" "backend process launched" "OK"
        }
        else {
            Write-BootLine "APP" "existing backend detected" "OK"
        }
    }
    elseif ([string]::IsNullOrWhiteSpace([string]$script:BrainRuntime.Selected)) {
        Add-Event "BRAIN   choose a model and press ENTER" 6
    }
    elseif ($script:ServiceConfigured -and $script:ServiceRuntime.Online -and [string]::IsNullOrWhiteSpace([string]$script:ServiceRuntime.Selected)) {
        $script:ActiveRole = "service"
        Add-Event "SERVICE choose a model and press ENTER" 6
    }

    $script:BootMode = $false
    try { [Console]::CursorVisible = $false } catch {}
    [Console]::Write($clear + $hideCursor)

    $sw = [Diagnostics.Stopwatch]::StartNew()
    $lastReadyCheck = 0.0
    $lastLogPoll = 0.0
    $lastSwitchPoll = 0.0
    $lastRenderAt = -1.0
    $lastInputAt = 0.0
    # Full dashboard diffing in Windows PowerShell 5.1 is not cheap. Redraw
    # immediately for input/state changes; animate only when the user is idle.
    $idleAnimationInterval = 0.85
    $idleBeforeAnimation = 0.75
    $script:BackendReady = Test-AppReadyFast
    $script:DashboardDirty = $true
    $quit = $false

    Render-Dashboard 0.0
    $lastRenderAt = 0.0
    $script:DashboardDirty = $false

    while (-not $quit) {
        $now = $sw.Elapsed.TotalSeconds

        if (($now - $lastSwitchPoll) -ge 0.06) {
            $lastSwitchPoll = $now
            Poll-ModelSwitch
        }

        if (($now - $lastLogPoll) -ge 0.12) {
            $lastLogPoll = $now
            $script:StdOutPosition = Read-LogDelta -Path $StdOutPath -Position $script:StdOutPosition
            $script:StdErrPosition = Read-LogDelta -Path $StdErrPath -Position $script:StdErrPosition -ErrorStream
        }

        if (($now - $lastReadyCheck) -ge 0.8) {
            $lastReadyCheck = $now
            $wasReady = $script:BackendReady
            $script:BackendReady = Test-AppReadyFast
            if ($wasReady -ne $script:BackendReady) { $script:DashboardDirty = $true }
            if ($script:BackendReady -and -not $script:BrowserOpened) { Open-JinBrowser }
        }

        if ($script:BackendReady -and $null -ne $script:PendingContextApply -and -not $script:SwitchJob) {
            $pending = $script:PendingContextApply
            $script:PendingContextApply = $null
            $pendingRole = [string]$pending.Role
            $pendingRuntime = if ($pendingRole -eq "brain") { $script:BrainRuntime } else { $script:ServiceRuntime }
            $pendingIndex = Get-ModelIndex $pendingRuntime ([string]$pending.Model)
            $pendingModels = @($pendingRuntime.Models)
            if (
                $pendingModels.Count -gt 0 -and
                $pendingIndex -ge 0 -and
                $pendingIndex -lt $pendingModels.Count -and
                [string]$pendingModels[$pendingIndex].Id -eq [string]$pending.Model
            ) {
                $script:CursorByRole[$pendingRole] = $pendingIndex
                Start-ModelSwitch $pendingRole $pendingRuntime ([int]$pending.ContextLength)
            }
            else {
                Add-Event ("CONTEXT queued model disappeared // " + [string]$pending.Model) 9
            }
            $script:DashboardDirty = $true
        }

        $keyName = Read-LauncherKeyName -Now $now
        if (-not [string]::IsNullOrWhiteSpace($keyName)) {
            $lastInputAt = $now
            if ($script:ContextMode) {
                switch ($keyName) {
                    "LeftArrow" { Move-ContextCursor -1 }
                    "RightArrow" { Move-ContextCursor 1 }
                    "Enter" {
                        $options = @($script:ContextOptions)
                        if ($options.Count -gt 0) {
                            $role = $script:ContextRole
                            $runtime = if ($role -eq "brain") { $script:BrainRuntime } else { $script:ServiceRuntime }
                            $modelId = $script:ContextModel
                            $contextLength = [int]$options[[int]$script:ContextIndex]
                            $index = Get-ModelIndex $runtime $modelId
                            if (@($runtime.Models).Count -gt 0 -and [string]$runtime.Models[$index].Id -eq $modelId) {
                                $script:CursorByRole[$role] = $index
                                $script:ActiveRole = $role
                                Close-ContextPicker
                                Start-ModelSwitch $role $runtime $contextLength
                            }
                            else {
                                Close-ContextPicker
                                Add-Event ("CONTEXT model disappeared // " + $modelId) 9
                            }
                        }
                    }
                    "C" { Close-ContextPicker }
                    "Escape" { Close-ContextPicker }
                }
            }
            else {
                $runtime = if ($script:ActiveRole -eq "brain") { $script:BrainRuntime } else { $script:ServiceRuntime }
                $models = @($runtime.Models)
                switch ($keyName) {
                    "UpArrow" {
                        if ($models.Count -gt 0) { $script:CursorByRole[$script:ActiveRole] = [Math]::Max(0, [int]$script:CursorByRole[$script:ActiveRole] - 1) }
                    }
                    "DownArrow" {
                        if ($models.Count -gt 0) { $script:CursorByRole[$script:ActiveRole] = [Math]::Min($models.Count - 1, [int]$script:CursorByRole[$script:ActiveRole] + 1) }
                    }
                    "LeftArrow" { $script:ActiveRole = "brain" }
                    "RightArrow" { if ($script:ServiceConfigured) { $script:ActiveRole = "service" } }
                    "Tab" {
                        if ($script:ServiceConfigured) { $script:ActiveRole = if ($script:ActiveRole -eq "brain") { "service" } else { "brain" } }
                    }
                    "Enter" {
                        if ($script:ActiveRole -eq "brain") { Start-ModelSwitch "brain" $script:BrainRuntime }
                        elseif ($script:ServiceConfigured) { Start-ModelSwitch "service" $script:ServiceRuntime }
                    }
                    "C" { Open-ContextPicker }
                    "R" {
                        Add-Event "RUNTIME refreshing model catalogs" 1
                        Refresh-Runtimes
                        Sync-CursorsToSelected
                    }
                    "O" {
                        $script:BrowserOpened = $false
                        Open-JinBrowser
                    }
                    "Q" { $quit = $true }
                    "Escape" { $quit = $true }
                }
            }
            $script:DashboardDirty = $true
        }

        if ($script:BackendProcess -and $script:BackendProcess.HasExited -and $script:BackendOwned) {
            Add-Event ("CORE    backend exited // code " + $script:BackendProcess.ExitCode) 9
            $script:BackendOwned = $false
        }

        $idleAnimationDue = (
            ($now - $lastInputAt) -ge $idleBeforeAnimation -and
            ($now - $lastRenderAt) -ge $idleAnimationInterval
        )
        if ($script:DashboardDirty -or $idleAnimationDue) {
            Render-Dashboard $now
            $lastRenderAt = $now
            $script:DashboardDirty = $false
        }

        Start-Sleep -Milliseconds 10
    }

}
catch {
    [Console]::Write($reset + $showCursor + $clear)
    try { [Console]::CursorVisible = $true } catch {}
    Write-Host "JIN LAUNCHER ERROR" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host $_.InvocationInfo.PositionMessage -ForegroundColor DarkRed
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}
finally {
    if ($script:SwitchJob) {
        Stop-Job $script:SwitchJob -ErrorAction SilentlyContinue | Out-Null
        Remove-Job $script:SwitchJob -Force -ErrorAction SilentlyContinue
    }
    Stop-JinBackend
    [Console]::Write($reset + $showCursor + $clear)
    try { [Console]::CursorVisible = $true } catch {}

    if ($LauncherMutex) {
        try { $LauncherMutex.ReleaseMutex() } catch {}
        $LauncherMutex.Dispose()
    }
}
