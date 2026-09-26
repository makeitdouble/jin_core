param(
    [string]$AppUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"
# The dashboard owns the console buffer. PowerShell progress (including module
# auto-loading and HTTP probes) saves/restores cells through the legacy console
# API, losing their ANSI RGB colors. Disable it before any cmdlet can draw it.
$ProgressPreference = "SilentlyContinue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$FinalConfigPath = Join-Path $Root "config.py"
$FirstRunConfigPath = Join-Path $Root ".config.py.first-run"
$ConfigPath = $FinalConfigPath
$ConfigExamplePath = Join-Path $Root "config.example.py"
$LauncherDir = Join-Path $Root ".jin_launcher"
$RuntimeDir = Join-Path $Root ".jin_runtime"
$UvDir = Join-Path $RuntimeDir "uv"
$UvExe = Join-Path $UvDir "uv.exe"
$ManagedPythonDir = Join-Path $RuntimeDir "python"
$UvCacheDir = Join-Path $RuntimeDir "uv-cache"
$ManagedPythonVersion = "3.12"
$UvVersion = "0.12.19"
$LlamaBuild = "b11112"
$LlamaCudaVersion = "12.4"
$LlamaDir = Join-Path $RuntimeDir "llama"
$LlamaServerExe = Join-Path $LlamaDir "llama-server.exe"
$LlamaRuntimeMarker = Join-Path $LlamaDir ".jin_llama_runtime"
$LlamaMainAsset = "llama-$LlamaBuild-bin-win-cuda-$LlamaCudaVersion-x64.zip"
$LlamaCudaAsset = "cudart-llama-bin-win-cuda-$LlamaCudaVersion-x64.zip"
$LlamaMainSha256 = "f43f62912ef90878f4a1612066c6390fb0bd3d39c4060749e959ca2fdd316316"
$LlamaCudaSha256 = "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6"
$EmbeddedModelsDir = Join-Path $RuntimeDir "models"
$DefaultEmbeddedModelRepo = "Open4bits/gemma-4-E4B-it-GGUF"
$DefaultEmbeddedModelFile = "gemma-4-e4b-it-q4_k_m.gguf"
$DefaultEmbeddedModelPath = Join-Path $EmbeddedModelsDir $DefaultEmbeddedModelFile
$DefaultEmbeddedModelMarker = Join-Path $EmbeddedModelsDir ".jin_default_model"
$DefaultEmbeddedModelUrl = "https://huggingface.co/Open4bits/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-e4b-it-q4_k_m.gguf?download=true"
$DefaultEmbeddedModelSha256 = "41a1a73fdbe350283d4b8a9984e4efa56a4d2ec5a585c7151aa02eff6e7d5da4"
$DefaultEmbeddedModelLabel = "Gemma 4 E4B Instruct Q4_K_M"
$EmbeddedBrainHost = "127.0.0.1"
$EmbeddedBrainPort = 12345
$EmbeddedBrainBaseUrl = "http://$EmbeddedBrainHost`:$EmbeddedBrainPort"
$EmbeddedBrainModelId = "gemma-4-e4b-it"
$EmbeddedBrainDefaultContext = 16384
$EmbeddedBrainMaxContext = 32768
$EmbeddedBrainContextPath = Join-Path $LauncherDir "brain_context.txt"
$script:EmbeddedBrainContext = $EmbeddedBrainDefaultContext
if (Test-Path -LiteralPath $EmbeddedBrainContextPath) {
    try {
        $savedEmbeddedContext = [int](Get-Content -Raw -LiteralPath $EmbeddedBrainContextPath)
        if ($savedEmbeddedContext -in @(4096, 8192, 16384, 32768)) {
            $script:EmbeddedBrainContext = $savedEmbeddedContext
        }
    }
    catch {}
}
$LlamaStdOutPath = Join-Path $LauncherDir "brain.stdout.log"
$LlamaStdErrPath = Join-Path $LauncherDir "brain.stderr.log"
$StdOutPath = Join-Path $LauncherDir "backend.stdout.log"
$StdErrPath = Join-Path $LauncherDir "backend.stderr.log"
$LauncherMutex = $null

# Lock only this JIN installation. A single global mutex made a launcher from
# another folder silently kill clean-room / first-run tests.
$rootMutexBytes = [System.Text.Encoding]::UTF8.GetBytes(
    ([System.IO.Path]::GetFullPath($Root)).TrimEnd('\').ToLowerInvariant()
)
$rootMutexHasher = [System.Security.Cryptography.SHA256]::Create()
try {
    $rootMutexHash = [System.BitConverter]::ToString(
        $rootMutexHasher.ComputeHash($rootMutexBytes)
    ).Replace("-", "").Substring(0, 16)
}
finally {
    $rootMutexHasher.Dispose()
}
$LauncherMutexName = "Global\JINCoreLauncher_$rootMutexHash"

$script:BackendProcess = $null
$script:BackendOwned = $false
$script:LlamaProcess = $null
$script:LlamaOwned = $false
$script:BrainIsEmbedded = $true
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
$script:BootTasks = [ordered]@{}
$script:BootDownload = $null
$script:ConfigExistedAtLaunch = $false
$script:LauncherInitializing = $false
$script:BootTopPadding = 2
$script:BootPrevText = @()
$script:BootPrevColor = @()
$script:BootPrevWidth = 0

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
    [DllImport("user32.dll", SetLastError=true)]
    private static extern int GetWindowLong(IntPtr hWnd, int nIndex);
    [DllImport("user32.dll", SetLastError=true)]
    private static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);
    [DllImport("user32.dll", SetLastError=true)]
    private static extern bool SetWindowPos(
        IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);

    public static void DisableResize() {
        IntPtr hWnd = GetConsoleWindow();
        if (hWnd == IntPtr.Zero) return;

        const int GWL_STYLE = -16;
        const int WS_SIZEBOX = 0x00040000;
        const int WS_MAXIMIZEBOX = 0x00010000;
        const uint SWP_NOSIZE = 0x0001;
        const uint SWP_NOMOVE = 0x0002;
        const uint SWP_NOZORDER = 0x0004;
        const uint SWP_FRAMECHANGED = 0x0020;

        int style = GetWindowLong(hWnd, GWL_STYLE);
        style &= ~WS_SIZEBOX;
        style &= ~WS_MAXIMIZEBOX;
        SetWindowLong(hWnd, GWL_STYLE, style);
        SetWindowPos(hWnd, IntPtr.Zero, 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED);
    }
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

# The launcher UI is designed around a fixed 92x55 canvas. Remove the sizing
# frame and maximize button after the BAT has applied that console geometry so
# accidental drags cannot corrupt the dashboard layout.
try { [JinConsoleVT]::DisableResize() } catch {}

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

function Initialize-BootTasks {
    if ($script:BootTasks.Count -gt 0) { return }

    foreach ($spec in @(
        [pscustomobject]@{ Key = "CONFIG"; Group = "1. CONFIG"; Title = "Load JIN configuration"; State = "PENDING"; Text = "waiting" }
        [pscustomobject]@{ Key = "PYTHON"; Group = "1. CONFIG"; Title = "Prepare private Python runtime"; State = "PENDING"; Text = "waiting" }
        [pscustomobject]@{ Key = "LLAMA"; Group = "2. SETUP"; Title = "Install llama.cpp runtime"; State = "PENDING"; Text = "waiting" }
        [pscustomobject]@{ Key = "MODEL"; Group = "2. SETUP"; Title = "Install Gemma 4 E4B model"; State = "PENDING"; Text = "waiting" }
        [pscustomobject]@{ Key = "BRAIN"; Group = "3. BRAIN"; Title = "Start local Gemma brain"; State = "PENDING"; Text = "waiting" }
        [pscustomobject]@{ Key = "SERVICE"; Group = "3. BRAIN"; Title = "Check optional Service"; State = "PENDING"; Text = "waiting" }
        [pscustomobject]@{ Key = "APP"; Group = "4. APP"; Title = "Start JIN backend"; State = "PENDING"; Text = "waiting" }
    )) {
        $script:BootTasks[$spec.Key] = [pscustomobject]@{
            Key = $spec.Key
            Group = $spec.Group
            Title = $spec.Title
            State = $spec.State
            Text = $spec.Text
        }
    }
}

function Get-BootTaskVisual {
    param([string]$State)

    switch ($State) {
        "OK"    { return [pscustomobject]@{ Marker = "[x]"; Color = 10 } }
        "WARN"  { return [pscustomobject]@{ Marker = "[!]"; Color = 6 } }
        "ERROR" { return [pscustomobject]@{ Marker = "[x]"; Color = 9 } }
        "WORK"  { return [pscustomobject]@{ Marker = "[>]"; Color = 4 } }
        default  { return [pscustomobject]@{ Marker = "[ ]"; Color = 7 } }
    }
}

function Get-BootSectionDoneCount {
    param([string]$Group)

    $items = @($script:BootTasks.Values | Where-Object { $_.Group -eq $Group -and ($_.Key -ne 'SERVICE' -or $script:ServiceConfigured) })
    if ($items.Count -eq 0) { return "0/0" }
    $done = @($items | Where-Object { $_.State -eq "OK" }).Count
    return "$done/$($items.Count)"
}

function Format-BootDownloadText {
    param(
        [string]$DisplayName,
        [long]$Downloaded,
        [long]$Total,
        [double]$BytesPerSecond = 0,
        [int]$BarWidth = 22
    )

    $downloadedText = Format-DownloadBytes $Downloaded
    $rateText = Format-DownloadRate $BytesPerSecond

    if ($Total -gt 0) {
        $percent = [Math]::Max(0, [Math]::Min(100, [Math]::Floor(($Downloaded * 100.0) / $Total)))
        $filled = [int][Math]::Floor(($percent * $BarWidth) / 100.0)
        $bar = ("#" * $filled) + ("-" * ($BarWidth - $filled))
        $sizeText = "$downloadedText / $(Format-DownloadBytes $Total)"
        return [pscustomobject]@{
            Title = $DisplayName
            Progress = ("[{0}] {1,3}%  {2,-11}  {3}" -f $bar, $percent, $rateText, $sizeText)
        }
    }

    $bar = ("-" * $BarWidth)
    return [pscustomobject]@{
        Title = $DisplayName
        Progress = ("[{0}]  --%  {1,-11}  {2}" -f $bar, $rateText, $downloadedText)
    }
}

function Get-BootHintLines {
    $lines = New-Object System.Collections.Generic.List[string]

    if ($script:BootDownload -ne $null) {
        [void]$lines.Add('Please wait. JIN is downloading and verifying the required local runtime.')
    }
    elseif ($script:BootTasks.Contains('BRAIN') -and $script:BootTasks['BRAIN'].State -eq 'WORK') {
        [void]$lines.Add('Starting the downloaded Gemma model locally. No external model app is required.')
    }

    return ,$lines.ToArray()
}

function Render-BootScreen {
    if (-not $script:BootMode) { return }
    Start-BootScreen
    Initialize-BootTasks

    $width = [Math]::Max(92, [Console]::WindowWidth)
    $usable = $width - 2
    $lines = New-Object System.Collections.Generic.List[object]
    $groups = @('1. CONFIG', '2. SETUP', '3. BRAIN', '4. APP')

    for ($i = 0; $i -lt $script:BootTopPadding; $i++) {
        [void]$lines.Add([pscustomobject]@{ Text = ''; Color = 8 })
    }
    [void]$lines.Add([pscustomobject]@{ Text = '  [ JIN CORE ENGINE // LAUNCHER ]'; Color = 8 })
    [void]$lines.Add([pscustomobject]@{ Text = ''; Color = 8 })
    [void]$lines.Add([pscustomobject]@{ Text = '  FIRST-RUN CHECKLIST'; Color = 4 })
    [void]$lines.Add([pscustomobject]@{ Text = ''; Color = 8 })

    foreach ($group in $groups) {
        $countText = Get-BootSectionDoneCount $group
        [void]$lines.Add([pscustomobject]@{ Text = ('  ' + $group + '   [' + $countText + ']'); Color = 3 })
        foreach ($task in @($script:BootTasks.Values | Where-Object { $_.Group -eq $group })) {
            if ($task.Key -eq 'SERVICE' -and -not $script:ServiceConfigured) { continue }
            $visual = Get-BootTaskVisual $task.State
            $title = $task.Title
            $text = $task.Text
            $maxText = [Math]::Max(12, $usable - 8 - $title.Length - 3)
            if ($text.Length -gt $maxText) {
                $text = $text.Substring(0, [Math]::Max(1, $maxText - 1)) + '…'
            }
            $dots = '.' * [Math]::Max(2, $usable - 8 - $title.Length - $text.Length)
            $line = ('  {0} {1} {2} {3}' -f $visual.Marker, $title, $dots, $text)
            [void]$lines.Add([pscustomobject]@{ Text = $line; Color = $visual.Color })
        }
        [void]$lines.Add([pscustomobject]@{ Text = ''; Color = 8 })
    }

    if ($script:BootDownload -ne $null) {
        $dl = Format-BootDownloadText -DisplayName $script:BootDownload.DisplayName -Downloaded $script:BootDownload.Downloaded -Total $script:BootDownload.Total -BytesPerSecond $script:BootDownload.BytesPerSecond
        [void]$lines.Add([pscustomobject]@{ Text = '  ACTIVE DOWNLOAD'; Color = 6 })
        [void]$lines.Add([pscustomobject]@{ Text = ('    ' + $dl.Title); Color = 8 })
        [void]$lines.Add([pscustomobject]@{ Text = ('    ' + $dl.Progress); Color = 6 })
        [void]$lines.Add([pscustomobject]@{ Text = ''; Color = 8 })
    }

    foreach ($hint in @(Get-BootHintLines)) {
        [void]$lines.Add([pscustomobject]@{ Text = ('  ' + $hint); Color = 7 })
    }

    # Boot progress can update several times per second. Never clear/repaint the
    # whole console here: on Windows that produces a very visible flash. Build
    # the desired frame, compare it with the previous one and write only rows
    # that actually changed. During a download this normally updates one row.
    $currentText = New-Object System.Collections.Generic.List[string]
    $currentColor = New-Object System.Collections.Generic.List[int]
    foreach ($entry in $lines) {
        $lineText = [string]$entry.Text
        if ($lineText.Length -gt $usable) { $lineText = $lineText.Substring(0, $usable) }
        [void]$currentText.Add($lineText.PadRight($usable))
        [void]$currentColor.Add([int]$entry.Color)
    }

    $previousCount = @($script:BootPrevText).Count
    $renderCount = [Math]::Max($currentText.Count, $previousCount)
    $frame = New-Object System.Text.StringBuilder
    [void]$frame.Append($hideCursor)

    for ($i = 0; $i -lt $renderCount; $i++) {
        $newText = if ($i -lt $currentText.Count) { $currentText[$i] } else { ''.PadRight($usable) }
        $newColor = if ($i -lt $currentColor.Count) { $currentColor[$i] } else { 8 }
        $oldText = if ($i -lt $previousCount) { [string]$script:BootPrevText[$i] } else { $null }
        $oldColor = if ($i -lt @($script:BootPrevColor).Count) { [int]$script:BootPrevColor[$i] } else { -1 }

        if ($script:BootPrevWidth -ne $usable -or $newText -ne $oldText -or $newColor -ne $oldColor) {
            $row = $i + 1
            [void]$frame.Append("$esc[$row;1H")
            [void]$frame.Append("$esc[2K")
            [void]$frame.Append($ansi[$newColor])
            [void]$frame.Append($newText)
            [void]$frame.Append($reset)
        }
    }

    if ($frame.Length -gt $hideCursor.Length) {
        [Console]::Write($frame.ToString())
    }

    $script:BootPrevText = @($currentText.ToArray())
    $script:BootPrevColor = @($currentColor.ToArray())
    $script:BootPrevWidth = $usable
}

function Start-BootScreen {
    if ($script:BootStarted) { return }
    $script:BootStarted = $true
    try { [Console]::CursorVisible = $false } catch {}
    try { [Console]::Clear() } catch { try { Clear-Host } catch {} }
    $script:BootPrevText = @()
    $script:BootPrevColor = @()
    $script:BootPrevWidth = 0
    [Console]::Write($hideCursor)
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
    Initialize-BootTasks

    if (-not $script:BootTasks.Contains($Label)) {
        $script:BootTasks[$Label] = [pscustomobject]@{
            Key = $Label
            Group = '4. APP'
            Title = $Label
            State = 'PENDING'
            Text = 'waiting'
        }
    }

    $task = $script:BootTasks[$Label]
    $task.State = $State
    $task.Text = $Text
    Render-BootScreen
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
    Add-Event "CONFIG  prepared configuration from template" 3
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

function Test-ExplicitBrainConfiguration {
    if (-not $script:ConfigExistedAtLaunch) { return $false }

    $brainBase = [string](Get-PythonConfigValue "BRAIN_API_BASE")

    # An explicit Brain URL is enough to opt out of the embedded bootstrap.
    # BRAIN_MODEL_UID may be empty: in that case the launcher discovers the
    # catalog from this endpoint and lets the user choose a model.
    if ([string]::IsNullOrWhiteSpace($brainBase)) { return $false }
    if (Test-AutoBaseValue "BRAIN_API_BASE" $brainBase) { return $false }

    # A config written by JIN's own embedded bootstrap is still embedded mode.
    if ((Normalize-BaseUrl $brainBase).ToLowerInvariant() -eq $EmbeddedBrainBaseUrl.ToLowerInvariant()) {
        return $false
    }

    return $true
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
    $candidates = New-Object System.Collections.ArrayList

    # Prefer rich provider-native catalogs when available. LM Studio's
    # /api/v1/models contains all downloaded models plus their type, load state
    # and context metadata. /v1/models may expose only the currently visible
    # models and can therefore accidentally surface an embedding model alone.
    foreach ($suffix in @("/api/v1/models", "/api/v0/models", "/v1/models")) {
        try {
            $payload = Invoke-RestMethod -Method Get -Uri "$base$suffix" -TimeoutSec 2 -ErrorAction Stop
            $records = @(Get-ModelRecords $payload)
            if ($records.Count -gt 0) {
                [void]$candidates.Add([pscustomobject]@{
                    Suffix = $suffix
                    Records = $records
                    Priority = if ($suffix -eq "/api/v1/models") { 3 } elseif ($suffix -eq "/api/v0/models") { 2 } else { 1 }
                })
            }
        }
        catch {
            [void]$errors.Add(("$suffix // " + $_.Exception.Message))
        }
    }

    if ($candidates.Count -gt 0) {
        # Richest catalog wins; native API wins ties.
        $best = @(
            $candidates |
                Sort-Object `
                    @{ Expression = { @($_.Records).Count }; Descending = $true }, `
                    @{ Expression = { [int]$_.Priority }; Descending = $true }
        )[0]

        return [pscustomobject]@{
            Role = $Role
            BaseUrl = $base
            Online = $true
            Models = @($best.Records)
            Selected = $SelectedModel
            Source = [string]$best.Suffix
            Error = ""
        }
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

    if ($script:BrainIsEmbedded) {
        # Fresh/default install: JIN owns the local Brain runtime.
        $brainBase = $EmbeddedBrainBaseUrl
        $brainSelected = $EmbeddedBrainModelId
        Set-PythonConfigValue "BRAIN_API_BASE" $brainBase
        Set-PythonConfigValue "BRAIN_MODEL_UID" $brainSelected
    }
    else {
        # Existing explicit config is authoritative. Never replace it with the
        # embedded bootstrap endpoint/model.
        $brainBase = [string](Get-PythonConfigValue "BRAIN_API_BASE")
        $brainSelected = [string](Get-PythonConfigValue "BRAIN_MODEL_UID")
    }

    $serviceBase = [string](Get-PythonConfigValue "SERVICE_API_BASE")
    if (Test-AutoBaseValue "SERVICE_API_BASE" $serviceBase) { $serviceBase = "" }
    $serviceSelected = [string](Get-PythonConfigValue "SERVICE_MODEL_UID")
    if (Test-AutoModelValue $serviceSelected) { $serviceSelected = "" }

    if ($script:BootMode) {
        $probeText = if ($script:BrainIsEmbedded) { "checking local Gemma brain" } else { "checking configured Brain" }
        Write-BootLine "BRAIN" $probeText "WORK"
    }

    $script:BrainRuntime = Get-EndpointState "brain" $brainBase $brainSelected
    if ($script:BrainIsEmbedded -and $script:BrainRuntime.Online) {
        # llama-server already has the single embedded model loaded. Expose a
        # stable model record so the dashboard shows Brain, not endpoint plumbing.
        $script:BrainRuntime.Models = @(
            [pscustomobject]@{
                Id = $EmbeddedBrainModelId
                Loaded = $true
                MaxContext = [int]$EmbeddedBrainMaxContext
                LoadedContext = [int]$script:EmbeddedBrainContext
            }
        )
        $script:BrainRuntime.Selected = $EmbeddedBrainModelId
        $script:BrainRuntime.Source = "embedded llama.cpp"
    }

    if ($script:BootMode) {
        if ($script:BrainRuntime.Online) {
            if ($script:BrainIsEmbedded) {
                Write-BootLine "BRAIN" ("Gemma 4 E4B ready @ " + (Format-ContextTokens $script:EmbeddedBrainContext)) "OK"
            }
            else {
                if ([string]::IsNullOrWhiteSpace($brainSelected)) {
                    Write-BootLine "BRAIN" ((@($script:BrainRuntime.Models).Count).ToString() + " model(s) loaded from configured URL") "OK"
                }
                else {
                    Write-BootLine "BRAIN" ("configured Brain ready // " + $brainSelected) "OK"
                }
            }
        }
        else {
            $errorText = if ($script:BrainIsEmbedded) { "local Gemma brain unavailable" } else { "configured Brain endpoint unavailable" }
            Write-BootLine "BRAIN" $errorText "ERROR"
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($serviceBase)) {
        $script:ServiceRuntime = Get-EndpointState "service" $serviceBase $serviceSelected
        $script:ServiceConfigured = $true
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
    }
}

function Test-PythonCommand {
    param([string]$Executable)
    if ([string]::IsNullOrWhiteSpace($Executable) -or -not (Test-Path -LiteralPath $Executable)) {
        return $false
    }
    try {
        $versionOutput = & $Executable --version 2>&1
        $versionText = (@($versionOutput) -join " ").Trim()
        return ($LASTEXITCODE -eq 0 -and $versionText -match '^Python 3(?:\.|\s|$)')
    }
    catch { return $false }
}

function Get-UvWindowsAsset {
    $arch = [string]$env:PROCESSOR_ARCHITEW6432
    if ([string]::IsNullOrWhiteSpace($arch)) {
        $arch = [string]$env:PROCESSOR_ARCHITECTURE
    }

    switch ($arch.ToUpperInvariant()) {
        "AMD64" { return "uv-x86_64-pc-windows-msvc.zip" }
        "ARM64" { return "uv-aarch64-pc-windows-msvc.zip" }
        "X86" { return "uv-i686-pc-windows-msvc.zip" }
        default { Fail-WithMessage "Unsupported Windows architecture for JIN bootstrap: $arch" }
    }
}

function Set-UvRuntimeEnvironment {
    # Keep the complete Python toolchain private to the JIN folder. Nothing is
    # registered in Windows and no user/system Python is consulted.
    $env:UV_PYTHON_INSTALL_DIR = $ManagedPythonDir
    $env:UV_PYTHON_BIN_DIR = (Join-Path $RuntimeDir "python-bin")
    $env:UV_CACHE_DIR = $UvCacheDir
    $env:UV_PYTHON_NO_REGISTRY = "1"
    $env:UV_NO_CONFIG = "1"
    $env:UV_MANAGED_PYTHON = "1"
}

function Test-UvExecutable {
    if (-not (Test-Path -LiteralPath $UvExe)) { return $false }
    try {
        $versionOutput = & $UvExe --version 2>&1
        $versionText = (@($versionOutput) -join " ").Trim()
        return ($LASTEXITCODE -eq 0 -and $versionText -match '^uv\s+')
    }
    catch { return $false }
}

function Ensure-UvBootstrap {
    Set-UvRuntimeEnvironment
    if (Test-UvExecutable) { return $UvExe }

    $script:RuntimeMessage = "PREPARING PYTHON BOOTSTRAP"
    Write-BootLine "PYTHON" "preparing private runtime bootstrap" "WORK"

    if (-not (Test-Path -LiteralPath $UvDir)) {
        [void](New-Item -ItemType Directory -Path $UvDir -Force)
    }
    if (-not (Test-Path -LiteralPath $LauncherDir)) {
        [void](New-Item -ItemType Directory -Path $LauncherDir -Force)
    }

    $asset = Get-UvWindowsAsset
    $baseUrl = "https://releases.astral.sh/github/uv/releases/download/$UvVersion"
    $archiveUrl = "$baseUrl/$asset"
    $checksumUrl = "$archiveUrl.sha256"
    $archivePath = Join-Path $LauncherDir "uv-bootstrap.zip"
    $checksumPath = Join-Path $LauncherDir "uv-bootstrap.sha256"
    $extractDir = Join-Path $LauncherDir "uv-bootstrap-extract"

    try {
        if (Test-Path -LiteralPath $archivePath) { Remove-Item -LiteralPath $archivePath -Force }
        if (Test-Path -LiteralPath $checksumPath) { Remove-Item -LiteralPath $checksumPath -Force }
        if (Test-Path -LiteralPath $extractDir) { Remove-Item -LiteralPath $extractDir -Recurse -Force }

        $oldProtocol = [Net.ServicePointManager]::SecurityProtocol
        try {
            [Net.ServicePointManager]::SecurityProtocol = $oldProtocol -bor [Net.SecurityProtocolType]::Tls12
            Download-FileWithProgress -Url $archiveUrl -Destination $archivePath -DisplayName "uv bootstrap"
            Download-FileWithProgress -Url $checksumUrl -Destination $checksumPath -DisplayName "uv checksum"
        }
        finally {
            [Net.ServicePointManager]::SecurityProtocol = $oldProtocol
        }

        $checksumText = (Get-Content -Raw -LiteralPath $checksumPath).Trim()
        if ($checksumText -notmatch '(?i)^([0-9a-f]{64})\s+') {
            throw "Invalid uv checksum response."
        }
        $expectedHash = $Matches[1].ToLowerInvariant()
        $actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash) {
            throw "uv bootstrap checksum mismatch."
        }

        Expand-Archive -LiteralPath $archivePath -DestinationPath $extractDir -Force
        $downloadedUv = Get-ChildItem -LiteralPath $extractDir -Filter "uv.exe" -File -Recurse | Select-Object -First 1
        if ($null -eq $downloadedUv) {
            throw "uv.exe was not found in the downloaded archive."
        }

        Copy-Item -LiteralPath $downloadedUv.FullName -Destination $UvExe -Force
        if (-not (Test-UvExecutable)) {
            throw "Downloaded uv.exe failed to start."
        }
    }
    catch {
        Fail-WithMessage ("Unable to prepare the private JIN Python runtime.`r`n" + $_.Exception.Message)
    }
    finally {
        if (Test-Path -LiteralPath $archivePath) { Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue }
        if (Test-Path -LiteralPath $checksumPath) { Remove-Item -LiteralPath $checksumPath -Force -ErrorAction SilentlyContinue }
        if (Test-Path -LiteralPath $extractDir) { Remove-Item -LiteralPath $extractDir -Recurse -Force -ErrorAction SilentlyContinue }
    }

    Write-BootLine "PYTHON" "runtime bootstrap ready" "OK"
    return $UvExe
}

function Get-WindowsArchitecture {
    $arch = [string]$env:PROCESSOR_ARCHITEW6432
    if ([string]::IsNullOrWhiteSpace($arch)) {
        $arch = [string]$env:PROCESSOR_ARCHITECTURE
    }
    return $arch.ToUpperInvariant()
}

function Test-LlamaServerExecutable {
    if (-not (Test-Path -LiteralPath $LlamaServerExe)) { return $false }
    if (-not (Test-Path -LiteralPath $LauncherDir)) {
        [void](New-Item -ItemType Directory -Path $LauncherDir -Force)
    }

    $stdoutPath = Join-Path $LauncherDir "llama-runtime-check.stdout"
    $stderrPath = Join-Path $LauncherDir "llama-runtime-check.stderr"
    Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue

    try {
        $process = Start-Process -FilePath $LlamaServerExe -ArgumentList @("--version") `
            -WorkingDirectory $LlamaDir -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
        if ($process.ExitCode -ne 0) { return $false }

        $output = @()
        if (Test-Path -LiteralPath $stdoutPath) { $output += @(Get-Content -LiteralPath $stdoutPath) }
        if (Test-Path -LiteralPath $stderrPath) { $output += @(Get-Content -LiteralPath $stderrPath) }
        $text = ($output -join "`n").Trim()
        return (-not [string]::IsNullOrWhiteSpace($text))
    }
    catch {
        return $false
    }
    finally {
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    }
}

function Test-LlamaRuntime {
    if (-not (Test-LlamaServerExecutable)) { return $false }
    if (-not (Test-Path -LiteralPath $LlamaRuntimeMarker)) { return $false }

    try {
        $marker = (Get-Content -Raw -LiteralPath $LlamaRuntimeMarker).Trim()
        return ($marker -eq $LlamaBuild)
    }
    catch {
        return $false
    }
}

function Copy-DirectoryContents {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (-not (Test-Path -LiteralPath $Destination)) {
        [void](New-Item -ItemType Directory -Path $Destination -Force)
    }
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force
    }
}

function Download-VerifiedArchive {
    param(
        [string]$Url,
        [string]$Destination,
        [string]$ExpectedSha256,
        [string]$DisplayName
    )

    Download-FileWithProgress -Url $Url -Destination $Destination -DisplayName $DisplayName
    $actualHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "SHA-256 mismatch for $(Split-Path -Leaf $Destination)."
    }
}

function Ensure-LlamaRuntime {
    if (Test-LlamaRuntime) {
        return [pscustomobject]@{
            Server = $LlamaServerExe
            Build = $LlamaBuild
            State = "CACHED"
        }
    }

    if ((Get-WindowsArchitecture) -ne "AMD64") {
        Fail-WithMessage "Embedded llama.cpp bootstrap currently supports Windows x64 only."
    }

    $script:RuntimeMessage = "PREPARING EMBEDDED LLAMA RUNTIME"
    Write-BootLine "LLAMA" "preparing embedded runtime" "WORK"

    if (-not (Test-Path -LiteralPath $LauncherDir)) {
        [void](New-Item -ItemType Directory -Path $LauncherDir -Force)
    }

    $baseUrl = "https://github.com/ggml-org/llama.cpp/releases/download/$LlamaBuild"
    $mainUrl = "$baseUrl/$LlamaMainAsset"
    $cudaUrl = "$baseUrl/$LlamaCudaAsset"
    $mainArchive = Join-Path $LauncherDir "llama-runtime.zip"
    $cudaArchive = Join-Path $LauncherDir "llama-cudart.zip"
    $mainExtract = Join-Path $LauncherDir "llama-runtime-extract"
    $cudaExtract = Join-Path $LauncherDir "llama-cudart-extract"

    try {
        foreach ($path in @($mainArchive, $cudaArchive)) {
            if (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Force
            }
        }
        foreach ($path in @($mainExtract, $cudaExtract)) {
            if (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Recurse -Force
            }
        }

        $oldProtocol = [Net.ServicePointManager]::SecurityProtocol
        try {
            [Net.ServicePointManager]::SecurityProtocol = $oldProtocol -bor [Net.SecurityProtocolType]::Tls12
            Download-VerifiedArchive -Url $mainUrl -Destination $mainArchive -ExpectedSha256 $LlamaMainSha256 -DisplayName "llama.cpp $LlamaBuild CUDA $LlamaCudaVersion"
            Download-VerifiedArchive -Url $cudaUrl -Destination $cudaArchive -ExpectedSha256 $LlamaCudaSha256 -DisplayName "CUDA $LlamaCudaVersion runtime DLLs"
        }
        finally {
            [Net.ServicePointManager]::SecurityProtocol = $oldProtocol
        }

        Expand-Archive -LiteralPath $mainArchive -DestinationPath $mainExtract -Force
        Expand-Archive -LiteralPath $cudaArchive -DestinationPath $cudaExtract -Force

        $downloadedServer = Get-ChildItem -LiteralPath $mainExtract -Filter "llama-server.exe" -File -Recurse | Select-Object -First 1
        if ($null -eq $downloadedServer) {
            throw "llama-server.exe was not found in the llama.cpp archive."
        }

        $cudaDll = Get-ChildItem -LiteralPath $cudaExtract -Filter "*.dll" -File -Recurse | Select-Object -First 1
        if ($null -eq $cudaDll) {
            throw "CUDA runtime DLLs were not found in the llama.cpp CUDA archive."
        }

        if (Test-Path -LiteralPath $LlamaDir) {
            Remove-Item -LiteralPath $LlamaDir -Recurse -Force
        }
        [void](New-Item -ItemType Directory -Path $LlamaDir -Force)

        Copy-DirectoryContents -Source $downloadedServer.Directory.FullName -Destination $LlamaDir
        Copy-DirectoryContents -Source $cudaDll.Directory.FullName -Destination $LlamaDir

        Set-Content -LiteralPath $LlamaRuntimeMarker -Value $LlamaBuild -Encoding ASCII
        if (-not (Test-LlamaServerExecutable)) {
            throw "Downloaded llama-server.exe failed to start."
        }
    }
    catch {
        if (Test-Path -LiteralPath $LlamaDir) {
            Remove-Item -LiteralPath $LlamaDir -Recurse -Force -ErrorAction SilentlyContinue
        }
        Fail-WithMessage ("Unable to prepare the embedded llama.cpp runtime.`r`n" + $_.Exception.Message)
    }
    finally {
        foreach ($path in @($mainArchive, $cudaArchive)) {
            if (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
            }
        }
        foreach ($path in @($mainExtract, $cudaExtract)) {
            if (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }

    return [pscustomobject]@{
        Server = $LlamaServerExe
        Build = $LlamaBuild
        State = "INSTALLED"
    }
}

function Format-DownloadBytes {
    param([long]$Bytes)

    if ($Bytes -lt 0) { return "?" }
    if ($Bytes -ge 1GB) { return ("{0:0.00} GB" -f ($Bytes / 1GB)) }
    if ($Bytes -ge 1MB) { return ("{0:0.0} MB" -f ($Bytes / 1MB)) }
    if ($Bytes -ge 1KB) { return ("{0:0.0} KB" -f ($Bytes / 1KB)) }
    return ("$Bytes B")
}

function Format-DownloadRate {
    param([double]$BytesPerSecond)

    if ($BytesPerSecond -le 0) { return "--" }
    return ((Format-DownloadBytes ([long]$BytesPerSecond)) + "/s")
}

function Write-DownloadProgress {
    param(
        [string]$DisplayName,
        [long]$Downloaded,
        [long]$Total,
        [double]$BytesPerSecond = 0
    )

    if (-not $script:BootMode) { return }
    $script:BootDownload = [pscustomobject]@{
        DisplayName = $DisplayName
        Downloaded = $Downloaded
        Total = $Total
        BytesPerSecond = $BytesPerSecond
    }
    Render-BootScreen
}

function Download-FileWithProgress {
    param(
        [string]$Url,
        [string]$Destination,
        [string]$DisplayName
    )

    $partPath = "$Destination.part"
    $existingLength = 0L
    if (Test-Path -LiteralPath $partPath) {
        $existingLength = [long](Get-Item -LiteralPath $partPath).Length
    }

    $request = [System.Net.HttpWebRequest]::Create($Url)
    $request.Method = "GET"
    $request.AllowAutoRedirect = $true
    $request.UserAgent = "JIN-Core-Launcher/1.0"
    $request.Timeout = 300000
    $request.ReadWriteTimeout = 300000
    if ($existingLength -gt 0) {
        $request.AddRange($existingLength)
    }

    $response = $null
    $inputStream = $null
    $outputStream = $null
    $progressStarted = $false
    try {
        try {
            $response = [System.Net.HttpWebResponse]$request.GetResponse()
        }
        catch [System.Net.WebException] {
            $webResponse = $_.Exception.Response
            if ($null -ne $webResponse) {
                try {
                    $statusCode = [int]$webResponse.StatusCode
                    $statusText = [string]$webResponse.StatusDescription
                    throw "$DisplayName download failed: HTTP $statusCode $statusText"
                }
                finally {
                    $webResponse.Dispose()
                }
            }
            throw "$DisplayName download failed: $($_.Exception.Message)"
        }

        $append = ($existingLength -gt 0 -and [int]$response.StatusCode -eq 206)
        if (-not $append) {
            $existingLength = 0L
        }

        $remainingLength = [long]$response.ContentLength
        $totalLength = if ($remainingLength -gt 0) {
            $existingLength + $remainingLength
        }
        else {
            0L
        }

        $fileMode = if ($append) {
            [System.IO.FileMode]::Append
        }
        else {
            [System.IO.FileMode]::Create
        }

        $destinationDir = Split-Path -Parent $Destination
        if (-not [string]::IsNullOrWhiteSpace($destinationDir) -and -not (Test-Path -LiteralPath $destinationDir)) {
            [void](New-Item -ItemType Directory -Path $destinationDir -Force)
        }

        $outputStream = New-Object System.IO.FileStream(
            $partPath,
            $fileMode,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None,
            1048576,
            [System.IO.FileOptions]::SequentialScan
        )
        $inputStream = $response.GetResponseStream()
        $buffer = New-Object byte[] 1048576
        $downloaded = $existingLength
        $sampleBytes = $downloaded
        $sampleWatch = [System.Diagnostics.Stopwatch]::StartNew()
        $lastRate = 0.0
        $progressStarted = $true
        Write-DownloadProgress -DisplayName $DisplayName -Downloaded $downloaded -Total $totalLength -BytesPerSecond 0

        while (($read = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $outputStream.Write($buffer, 0, $read)
            $downloaded += $read

            if ($sampleWatch.ElapsedMilliseconds -ge 300) {
                $seconds = $sampleWatch.Elapsed.TotalSeconds
                if ($seconds -gt 0) {
                    $lastRate = ($downloaded - $sampleBytes) / $seconds
                }
                Write-DownloadProgress -DisplayName $DisplayName -Downloaded $downloaded -Total $totalLength -BytesPerSecond $lastRate
                $sampleBytes = $downloaded
                $sampleWatch.Restart()
            }
        }

        $outputStream.Flush()
        if ($sampleWatch.Elapsed.TotalSeconds -gt 0 -and $downloaded -gt $sampleBytes) {
            $lastRate = ($downloaded - $sampleBytes) / $sampleWatch.Elapsed.TotalSeconds
        }
        Write-DownloadProgress -DisplayName $DisplayName -Downloaded $downloaded -Total $totalLength -BytesPerSecond $lastRate
        $script:BootDownload = $null
        Render-BootScreen
        $progressStarted = $false
    }
    finally {
        if ($null -ne $inputStream) { $inputStream.Dispose() }
        if ($null -ne $outputStream) { $outputStream.Dispose() }
        if ($null -ne $response) { $response.Dispose() }
        if ($progressStarted) {
            $script:BootDownload = $null
            Render-BootScreen
        }
    }

    Move-Item -LiteralPath $partPath -Destination $Destination -Force
}

function Write-DefaultModelMarker {
    param([long]$Size)

    $marker = @(
        $DefaultEmbeddedModelFile,
        $DefaultEmbeddedModelSha256.ToLowerInvariant(),
        [string]$Size
    ) -join "`n"
    Set-Content -LiteralPath $DefaultEmbeddedModelMarker -Value $marker -Encoding ASCII
}

function Test-DefaultEmbeddedModel {
    if (-not (Test-Path -LiteralPath $DefaultEmbeddedModelPath)) { return $false }

    if (Test-Path -LiteralPath $DefaultEmbeddedModelMarker) {
        try {
            $lines = @(Get-Content -LiteralPath $DefaultEmbeddedModelMarker)
            if ($lines.Count -ge 3) {
                $expectedSize = 0L
                $sizeOk = [long]::TryParse([string]$lines[2], [ref]$expectedSize)
                $actualSize = [long](Get-Item -LiteralPath $DefaultEmbeddedModelPath).Length
                if (
                    [string]$lines[0] -eq $DefaultEmbeddedModelFile -and
                    ([string]$lines[1]).Trim().ToLowerInvariant() -eq $DefaultEmbeddedModelSha256.ToLowerInvariant() -and
                    $sizeOk -and $expectedSize -gt 0 -and $actualSize -eq $expectedSize
                ) {
                    return $true
                }
            }
        }
        catch {}
    }

    # A model copied in by the user, or left after an older bootstrap, is
    # accepted only after a one-time integrity check. Future launches use the
    # marker + file size and do not hash a multi-gigabyte file every time.
    try {
        $actualHash = (Get-FileHash -LiteralPath $DefaultEmbeddedModelPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -eq $DefaultEmbeddedModelSha256.ToLowerInvariant()) {
            $size = [long](Get-Item -LiteralPath $DefaultEmbeddedModelPath).Length
            Write-DefaultModelMarker -Size $size
            return $true
        }
    }
    catch {}

    return $false
}

function Ensure-DefaultEmbeddedModel {
    if (Test-DefaultEmbeddedModel) {
        return [pscustomobject]@{
            Path = $DefaultEmbeddedModelPath
            Repo = $DefaultEmbeddedModelRepo
            File = $DefaultEmbeddedModelFile
            State = "CACHED"
        }
    }

    $script:RuntimeMessage = "DOWNLOADING EMBEDDED DEFAULT MODEL"
    if (-not (Test-Path -LiteralPath $EmbeddedModelsDir)) {
        [void](New-Item -ItemType Directory -Path $EmbeddedModelsDir -Force)
    }

    if (Test-Path -LiteralPath $DefaultEmbeddedModelPath) {
        Remove-Item -LiteralPath $DefaultEmbeddedModelPath -Force
    }
    if (Test-Path -LiteralPath $DefaultEmbeddedModelMarker) {
        Remove-Item -LiteralPath $DefaultEmbeddedModelMarker -Force
    }

    try {
        $oldProtocol = [Net.ServicePointManager]::SecurityProtocol
        try {
            [Net.ServicePointManager]::SecurityProtocol = $oldProtocol -bor [Net.SecurityProtocolType]::Tls12
            Download-FileWithProgress `
                -Url $DefaultEmbeddedModelUrl `
                -Destination $DefaultEmbeddedModelPath `
                -DisplayName $DefaultEmbeddedModelLabel
        }
        finally {
            [Net.ServicePointManager]::SecurityProtocol = $oldProtocol
        }

        Write-BootLine "MODEL" "verifying embedded default model" "WORK"
        $actualHash = (Get-FileHash -LiteralPath $DefaultEmbeddedModelPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $DefaultEmbeddedModelSha256.ToLowerInvariant()) {
            throw "Default model SHA-256 mismatch."
        }

        $size = [long](Get-Item -LiteralPath $DefaultEmbeddedModelPath).Length
        Write-DefaultModelMarker -Size $size
    }
    catch {
        if (Test-Path -LiteralPath $DefaultEmbeddedModelPath) {
            Remove-Item -LiteralPath $DefaultEmbeddedModelPath -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $DefaultEmbeddedModelMarker) {
            Remove-Item -LiteralPath $DefaultEmbeddedModelMarker -Force -ErrorAction SilentlyContinue
        }
        Fail-WithMessage ("Unable to prepare the embedded default model.`r`n" + $_.Exception.Message)
    }

    return [pscustomobject]@{
        Path = $DefaultEmbeddedModelPath
        Repo = $DefaultEmbeddedModelRepo
        File = $DefaultEmbeddedModelFile
        State = "DOWNLOADED"
    }
}

function Test-EmbeddedBrainReady {
    try {
        $response = Invoke-WebRequest -Uri "$EmbeddedBrainBaseUrl/health" -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
        return ([int]$response.StatusCode -eq 200)
    }
    catch {
        return $false
    }
}

function Test-TcpPort {
    param(
        [Parameter(Mandatory = $true)]
        [string]$HostName,
        [Parameter(Mandatory = $true)]
        [int]$Port,
        [int]$TimeoutMs = 80
    )

    $client = $null
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $task = $client.ConnectAsync($HostName, $Port)
        if (-not $task.Wait($TimeoutMs)) {
            return $false
        }
        return [bool]$client.Connected
    }
    catch {
        return $false
    }
    finally {
        if ($null -ne $client) {
            try { $client.Close() } catch {}
            try { $client.Dispose() } catch {}
        }
    }
}

function Get-EmbeddedBrainErrorTail {
    if (-not (Test-Path -LiteralPath $LlamaStdErrPath)) { return "" }
    try {
        $lines = @(Get-Content -LiteralPath $LlamaStdErrPath -Tail 10 -ErrorAction Stop)
        return (($lines -join " // ").Trim())
    }
    catch {
        return ""
    }
}

function Start-EmbeddedBrain {
    if (-not (Test-Path -LiteralPath $LlamaServerExe)) {
        Fail-WithMessage "Embedded llama-server.exe is missing."
    }
    if (-not (Test-Path -LiteralPath $DefaultEmbeddedModelPath)) {
        Fail-WithMessage "Embedded Gemma model is missing."
    }

    Set-PythonConfigValue "BRAIN_API_BASE" $EmbeddedBrainBaseUrl
    Set-PythonConfigValue "BRAIN_MODEL_UID" $EmbeddedBrainModelId

    if (Test-EmbeddedBrainReady) {
        $script:LlamaOwned = $false
        return [pscustomobject]@{ State = "EXISTING"; BaseUrl = $EmbeddedBrainBaseUrl; Model = $EmbeddedBrainModelId }
    }

    if ($script:LlamaProcess -and -not $script:LlamaProcess.HasExited) {
        # A process is already loading. Continue into the readiness wait below.
    }
    else {
        # Do not silently attach to an unrelated service that happens to own the
        # embedded Brain port.
        if (Test-TcpPort -HostName $EmbeddedBrainHost -Port $EmbeddedBrainPort) {
            Fail-WithMessage "JIN embedded Brain port $EmbeddedBrainPort is already in use."
        }

        Remove-Item -LiteralPath $LlamaStdOutPath, $LlamaStdErrPath -Force -ErrorAction SilentlyContinue

        $brainArgs = @(
            "--model", ('"{0}"' -f $DefaultEmbeddedModelPath),
            "--alias", $EmbeddedBrainModelId,
            "--host", $EmbeddedBrainHost,
            "--port", [string]$EmbeddedBrainPort,
            "--ctx-size", [string]$script:EmbeddedBrainContext,
            "--n-gpu-layers", "999"
        )

        $startParams = @{
            FilePath = $LlamaServerExe
            ArgumentList = $brainArgs
            WorkingDirectory = $LlamaDir
            NoNewWindow = $true
            RedirectStandardOutput = $LlamaStdOutPath
            RedirectStandardError = $LlamaStdErrPath
            PassThru = $true
        }

        Write-BootLine "BRAIN" "starting Gemma 4 E4B locally" "WORK"
        $script:LlamaProcess = Start-Process @startParams
        $script:LlamaOwned = $true
    }

    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $lastShownSecond = -1
    while ($watch.Elapsed.TotalSeconds -lt 180) {
        if (Test-EmbeddedBrainReady) {
            return [pscustomobject]@{ State = "STARTED"; BaseUrl = $EmbeddedBrainBaseUrl; Model = $EmbeddedBrainModelId }
        }

        if ($script:LlamaProcess -and $script:LlamaProcess.HasExited) {
            $tail = Get-EmbeddedBrainErrorTail
            $suffix = if ([string]::IsNullOrWhiteSpace($tail)) { "" } else { "`r`n$tail" }
            Fail-WithMessage ("Embedded Gemma Brain failed to start. Exit code $($script:LlamaProcess.ExitCode)." + $suffix)
        }

        $second = [int][Math]::Floor($watch.Elapsed.TotalSeconds)
        if ($second -ne $lastShownSecond) {
            $lastShownSecond = $second
            Write-BootLine "BRAIN" ("loading Gemma 4 E4B // " + $second + "s") "WORK"
        }
        Start-Sleep -Milliseconds 400
    }

    $tail = Get-EmbeddedBrainErrorTail
    $suffix = if ([string]::IsNullOrWhiteSpace($tail)) { "" } else { "`r`n$tail" }
    Fail-WithMessage ("Embedded Gemma Brain did not become ready within 180 seconds." + $suffix)
}

function Stop-EmbeddedBrain {
    param([switch]$IncludeAttached)

    $processId = 0
    if ($script:LlamaProcess -and -not $script:LlamaProcess.HasExited) {
        $processId = [int]$script:LlamaProcess.Id
    }
    elseif ($IncludeAttached) {
        # Recover a stale launcher-owned llama-server after a launcher restart/crash.
        # Match both our dedicated port and our embedded model so we do not kill an
        # unrelated llama-server instance.
        try {
            $expectedModel = [System.IO.Path]::GetFullPath($DefaultEmbeddedModelPath).ToLowerInvariant()
            foreach ($proc in @(Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" -ErrorAction Stop)) {
                $cmd = [string]$proc.CommandLine
                if ([string]::IsNullOrWhiteSpace($cmd)) { continue }
                $cmdLower = $cmd.ToLowerInvariant()
                if (
                    $cmdLower.Contains("--port $EmbeddedBrainPort") -and
                    $cmdLower.Contains($expectedModel)
                ) {
                    $processId = [int]$proc.ProcessId
                    break
                }
            }
        }
        catch {}
    }

    if ($IncludeAttached -and $processId -le 0 -and (Test-EmbeddedBrainReady)) {
        throw "Unable to identify the embedded llama-server process for context reload."
    }

    if ($processId -gt 0) {
        try { Stop-Process -Id $processId -Force -ErrorAction Stop } catch {
            throw ("Unable to stop embedded llama-server // " + $_.Exception.Message)
        }
        $watch = [System.Diagnostics.Stopwatch]::StartNew()
        while ($watch.Elapsed.TotalSeconds -lt 10 -and (Test-TcpPort -HostName $EmbeddedBrainHost -Port $EmbeddedBrainPort)) {
            Start-Sleep -Milliseconds 100
        }
        if (Test-TcpPort -HostName $EmbeddedBrainHost -Port $EmbeddedBrainPort) {
            throw "Embedded llama-server did not release its port for context reload."
        }
    }

    $script:LlamaProcess = $null
    $script:LlamaOwned = $false
}

function Ensure-Dependencies {
    $venvPath = Join-Path $Root ".venv"
    $venvPython = Join-Path $venvPath "Scripts\python.exe"
    $requirementsPath = Join-Path $Root "requirements.txt"
    $markerPath = Join-Path $venvPath ".jin_requirements.sha256"
    $created = $false

    if (-not (Test-Path -LiteralPath $requirementsPath)) {
        Fail-WithMessage "requirements.txt is missing."
    }

    # Keep a valid existing environment to avoid needless migration work for
    # current users. Broken/partial environments are replaced automatically.
    if ((Test-Path -LiteralPath $venvPython) -and -not (Test-PythonCommand -Executable $venvPython)) {
        Write-BootLine "PYTHON" "existing runtime is broken; rebuilding" "WARN"
        Remove-Item -LiteralPath $venvPath -Recurse -Force
    }

    if (-not (Test-Path -LiteralPath $venvPython)) {
        if (Test-Path -LiteralPath $venvPath) {
            Remove-Item -LiteralPath $venvPath -Recurse -Force
        }
        $script:RuntimeMessage = "CREATING PRIVATE PYTHON RUNTIME"
        Write-BootLine "PYTHON" "creating private Python $ManagedPythonVersion runtime" "WORK"
        $uv = Ensure-UvBootstrap
        Set-UvRuntimeEnvironment

        # uv writes normal venv/bootstrap status directly to the console. Keep
        # the launcher UI authoritative: capture native output to a log and
        # decide success only from the process exit code.
        $venvLog = Join-Path $LauncherDir "python-runtime.log"
        $venvStdOut = "$venvLog.stdout"
        $venvStdErr = "$venvLog.stderr"
        Remove-Item -LiteralPath $venvStdOut, $venvStdErr -Force -ErrorAction SilentlyContinue
        $venvArgs = @(
            "venv",
            "--python", $ManagedPythonVersion,
            "--managed-python",
            ('"{0}"' -f $venvPath)
        )
        $venvProcess = Start-Process -FilePath $uv -ArgumentList $venvArgs -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $venvStdOut -RedirectStandardError $venvStdErr
        $venvExitCode = $venvProcess.ExitCode
        $venvLines = @()
        if (Test-Path -LiteralPath $venvStdOut) { $venvLines += @(Get-Content -LiteralPath $venvStdOut) }
        if (Test-Path -LiteralPath $venvStdErr) { $venvLines += @(Get-Content -LiteralPath $venvStdErr) }
        Set-Content -LiteralPath $venvLog -Value $venvLines -Encoding UTF8
        Remove-Item -LiteralPath $venvStdOut, $venvStdErr -Force -ErrorAction SilentlyContinue

        if ($venvExitCode -ne 0 -or -not (Test-PythonCommand -Executable $venvPython)) {
            if (Test-Path -LiteralPath $venvPath) {
                Remove-Item -LiteralPath $venvPath -Recurse -Force -ErrorAction SilentlyContinue
            }
            Fail-WithMessage "JIN failed to create its private Python runtime. See .jin_launcher\python-runtime.log."
        }
        Render-BootScreen
        $created = $true
    }

    $hash = (Get-FileHash -LiteralPath $requirementsPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $cachedHash = ""
    if (Test-Path -LiteralPath $markerPath) {
        $cachedHash = (Get-Content -Raw -LiteralPath $markerPath).Trim().ToLowerInvariant()
    }

    if ($created -or $cachedHash -ne $hash) {
        $script:RuntimeMessage = "SYNCING PYTHON DEPENDENCIES"
        $installLog = Join-Path $LauncherDir "python-dependencies.log"
        $uv = Ensure-UvBootstrap
        Set-UvRuntimeEnvironment

        # Windows PowerShell 5.1 can promote redirected native stderr to a
        # PowerShell error record. uv writes normal progress to stderr, so run it
        # as a native process and decide success strictly from its exit code.
        $installStdOut = "$installLog.stdout"
        $installStdErr = "$installLog.stderr"
        Remove-Item -LiteralPath $installStdOut, $installStdErr -Force -ErrorAction SilentlyContinue
        $syncArgs = @(
            "pip", "sync", "--python",
            ('"{0}"' -f $venvPython),
            ('"{0}"' -f $requirementsPath)
        )
        $syncProcess = Start-Process -FilePath $uv -ArgumentList $syncArgs -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $installStdOut -RedirectStandardError $installStdErr
        $syncExitCode = $syncProcess.ExitCode
        $installLines = @()
        if (Test-Path -LiteralPath $installStdOut) { $installLines += @(Get-Content -LiteralPath $installStdOut) }
        if (Test-Path -LiteralPath $installStdErr) { $installLines += @(Get-Content -LiteralPath $installStdErr) }
        Set-Content -LiteralPath $installLog -Value $installLines -Encoding UTF8
        Remove-Item -LiteralPath $installStdOut, $installStdErr -Force -ErrorAction SilentlyContinue

        if ($syncExitCode -ne 0) {
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
    if (-not $script:BrainRuntime.Online) {
        return $false
    }
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

    if ($Role -eq "brain" -and $script:BrainIsEmbedded) {
        if ($ContextLength -le 0) {
            Add-Event ("BRAIN   " + $EmbeddedBrainModelId + " is already active @ " + (Format-ContextTokens $script:EmbeddedBrainContext)) 7
            return
        }

        if ($ContextLength -notin @(4096, 8192, 16384, 32768)) {
            Add-Event ("CONTEXT unsupported embedded Brain window // " + (Format-ContextTokens $ContextLength)) 9
            return
        }

        if ($ContextLength -eq [int]$script:EmbeddedBrainContext) {
            Add-Event ("CONTEXT embedded Brain already uses " + (Format-ContextTokens $ContextLength)) 7
            return
        }

        $previousContext = [int]$script:EmbeddedBrainContext
        Add-Event ("CONTEXT restarting embedded Brain // " + (Format-ContextTokens $previousContext) + " -> " + (Format-ContextTokens $ContextLength)) 4
        try {
            Stop-EmbeddedBrain -IncludeAttached
            $script:EmbeddedBrainContext = $ContextLength
            [void](Start-EmbeddedBrain)
            [System.IO.Directory]::CreateDirectory($LauncherDir) | Out-Null
            [System.IO.File]::WriteAllText($EmbeddedBrainContextPath, [string]$ContextLength, (New-Object System.Text.UTF8Encoding($false)))
            Refresh-Runtimes
            Sync-CursorsToSelected
            Add-Event ("CONTEXT embedded Brain active @ " + (Format-ContextTokens $ContextLength)) 10
        }
        catch {
            $errorText = $_.Exception.Message
            $script:EmbeddedBrainContext = $previousContext
            try {
                [void](Start-EmbeddedBrain)
                [System.IO.Directory]::CreateDirectory($LauncherDir) | Out-Null
                [System.IO.File]::WriteAllText($EmbeddedBrainContextPath, [string]$previousContext, (New-Object System.Text.UTF8Encoding($false)))
                Refresh-Runtimes
                Sync-CursorsToSelected
            }
            catch {}
            Add-Event ("CONTEXT embedded Brain restart failed // " + $errorText) 9
        }
        return
    }

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
        Put-Text $Chars $Cols $W $H 4 ($Y + 2) "uses Brain model and context" 1 52
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

    $runtimeStarting = ([string]$Runtime.Source -eq "starting")
    $status = if ($Runtime.Online) { "ONLINE" } elseif ($runtimeStarting) { "STARTING" } else { "OFFLINE" }
    $statusColor = if ($Runtime.Online) { [byte]10 } elseif ($runtimeStarting) { [byte]6 } else { [byte]9 }

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
        if ($Role -eq "brain" -and $script:BrainIsEmbedded) {
            Put-Text $Chars $Cols $W $H 4 ($Y + 2) "LOCAL" 1 6
            Put-Text $Chars $Cols $W $H 11 ($Y + 2) "embedded llama.cpp" 2 44
        }
        else {
            $base = [string]$Runtime.BaseUrl
            Put-Text $Chars $Cols $W $H 4 ($Y + 2) "URL" 1 4
            Put-Text $Chars $Cols $W $H 9 ($Y + 2) $base 2 46
        }
    }

    if ($models.Count -eq 0) {
        if ($runtimeStarting) {
            $emptyText = if ($Role -eq "brain" -and $script:BrainIsEmbedded) { "loading embedded brain..." } else { "checking configured endpoint..." }
            $emptyColor = [byte]6
        }
        else {
            $emptyText = if ($Runtime.Online) { "no chat models returned" } elseif ($Role -eq "brain" -and $script:BrainIsEmbedded) { "local brain unavailable" } else { "endpoint unavailable" }
            $emptyColor = if ($Runtime.Online) { [byte]1 } else { [byte]9 }
        }
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
    elseif ($script:LauncherInitializing -or ($script:BackendProcess -and -not $script:BackendProcess.HasExited)) {
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
        Write-Host ""
        Write-Host "JIN launcher for this installation is already running." -ForegroundColor DarkYellow
        Write-Host ""
        Read-Host "Press Enter to close"
        exit 0
    }

    Set-Location $Root

    # There are exactly two startup modes and config.py is the only switch:
    #   1) config.py exists at process start -> NEVER show first-run; render the
    #      normal dashboard immediately.
    #   2) config.py is absent -> run the complete first-run setup. Build its
    #      config in a temporary file and publish config.py only after setup has
    #      succeeded, so an interrupted first run can never masquerade as done.
    $script:ConfigExistedAtLaunch = Test-Path -LiteralPath $FinalConfigPath
    $script:BootMode = -not $script:ConfigExistedAtLaunch
    if ($script:BootMode) {
        $ConfigPath = $FirstRunConfigPath
        Remove-Item -LiteralPath $FirstRunConfigPath -Force -ErrorAction SilentlyContinue
        Start-BootScreen
    }
    else {
        $ConfigPath = $FinalConfigPath
    }

    if (-not (Test-Path -LiteralPath $LauncherDir)) {
        [void](New-Item -ItemType Directory -Path $LauncherDir -Force)
    }

    Write-BootLine "CONFIG" "reading configuration" "WORK"
    Import-DotEnv (Join-Path $Root ".env")
    Ensure-JinConfig
    $script:BrainIsEmbedded = -not (Test-ExplicitBrainConfiguration)
    if ($script:BrainIsEmbedded) {
        Write-BootLine "CONFIG" "runtime configuration loaded // embedded Brain" "OK"
    }
    else {
        Write-BootLine "CONFIG" "existing Brain configuration detected" "OK"
    }

    # Existing installation: paint the real dashboard before any potentially
    # slow runtime/model/backend checks. This is intentionally NOT a first-run
    # screen; config.py existing means the user sees the main UI immediately.
    if ($script:ConfigExistedAtLaunch) {
        # The main dashboard is shown immediately for an existing installation,
        # but runtime probes/model startup have not happened yet. Keep this
        # transient state visually distinct from a real endpoint failure.
        $script:LauncherInitializing = $true
        $initialBrainBase = Normalize-BaseUrl ([string](Get-PythonConfigValue "BRAIN_API_BASE"))
        $initialBrainSelected = [string](Get-PythonConfigValue "BRAIN_MODEL_UID")
        $initialServiceBase = Normalize-BaseUrl ([string](Get-PythonConfigValue "SERVICE_API_BASE"))
        $initialServiceSelected = [string](Get-PythonConfigValue "SERVICE_MODEL_UID")

        $script:BrainRuntime = [pscustomobject]@{
            Role = "brain"
            BaseUrl = $initialBrainBase
            Online = $false
            Models = @()
            Selected = $initialBrainSelected
            Source = "starting"
            Error = ""
        }
        $script:ServiceConfigured = -not [string]::IsNullOrWhiteSpace($initialServiceBase)
        $initialServiceSource = if ($script:ServiceConfigured) { "starting" } else { "brain fallback" }
        $script:ServiceRuntime = [pscustomobject]@{
            Role = "service"
            BaseUrl = $initialServiceBase
            Online = $false
            Models = @()
            Selected = $initialServiceSelected
            Source = $initialServiceSource
            Error = ""
        }
        $script:CursorByRole = @{ brain = 0; service = 0 }
        $script:ActiveRole = "brain"
        $script:BackendReady = $false
        Add-Event "RUNTIME starting configured installation" 1
        Render-Dashboard 0.0
    }

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

    if ($script:BrainIsEmbedded) {
        Write-BootLine "LLAMA" "checking embedded runtime" "WORK"
        $llamaRuntime = Ensure-LlamaRuntime
        $script:LlamaServerExe = [string]$llamaRuntime.Server
        $script:LlamaRuntimeBuild = [string]$llamaRuntime.Build
        if ([string]$llamaRuntime.State -eq "INSTALLED") {
            Write-BootLine "LLAMA" ("embedded runtime " + $script:LlamaRuntimeBuild + " installed") "OK"
        }
        else {
            Write-BootLine "LLAMA" ("embedded runtime " + $script:LlamaRuntimeBuild + " ready") "OK"
        }

        Write-BootLine "MODEL" "checking embedded default model" "WORK"
        $embeddedModel = Ensure-DefaultEmbeddedModel
        $script:EmbeddedModelPath = [string]$embeddedModel.Path
        $script:EmbeddedModelRepo = [string]$embeddedModel.Repo
        if ([string]$embeddedModel.State -eq "DOWNLOADED") {
            Write-BootLine "MODEL" ("embedded default ready // " + $DefaultEmbeddedModelLabel) "OK"
        }
        else {
            Write-BootLine "MODEL" ("embedded default cached // " + $DefaultEmbeddedModelLabel) "OK"
        }

        Write-BootLine "BRAIN" "starting downloaded Gemma model" "WORK"
        $embeddedBrain = Start-EmbeddedBrain
        Write-BootLine "BRAIN" ("Gemma 4 E4B ready @ " + (Format-ContextTokens $script:EmbeddedBrainContext)) "OK"

        Add-Event "CONFIG  local runtime configuration ready" 10
        Add-Event "SETUP   embedded llama.cpp runtime ready" 10
        Add-Event ("BRAIN   " + $EmbeddedBrainModelId + " ready @ " + (Format-ContextTokens $script:EmbeddedBrainContext)) 10
    }
    else {
        Write-BootLine "LLAMA" "skipped // existing Brain config" "OK"
        Write-BootLine "MODEL" "skipped // existing Brain config" "OK"
        Add-Event "CONFIG  existing Brain configuration preserved" 10
    }

    # First-run is considered complete only now: Python/runtime/model/Brain
    # preparation above has succeeded. Publish config.py atomically at the end,
    # never at the beginning of setup.
    if (-not $script:ConfigExistedAtLaunch) {
        if (-not (Test-Path -LiteralPath $FirstRunConfigPath)) {
            Fail-WithMessage "First-run configuration was not prepared."
        }
        Move-Item -LiteralPath $FirstRunConfigPath -Destination $FinalConfigPath -Force
        $ConfigPath = $FinalConfigPath
        Write-BootLine "CONFIG" "config.py created // first-run complete" "OK"
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
        Add-Event "BRAIN   local Gemma model is not ready" 9
    }
    elseif ($script:ServiceConfigured -and $script:ServiceRuntime.Online -and [string]::IsNullOrWhiteSpace([string]$script:ServiceRuntime.Selected)) {
        $script:ActiveRole = "service"
        Add-Event "SERVICE choose a model and press ENTER" 6
    }

    # Initial dependency/runtime probes are complete. From here on the normal
    # ONLINE/OFFLINE logic is authoritative; a launched backend process still
    # renders as STARTING until its health check succeeds.
    $script:LauncherInitializing = $false

    $hadBootScreen = $script:BootMode
    $script:BootMode = $false
    try { [Console]::CursorVisible = $false } catch {}
    if ($hadBootScreen) {
        [Console]::Write($clear + $hideCursor)
    }
    else {
        [Console]::Write($hideCursor)
    }

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
    if (-not $script:ConfigExistedAtLaunch -and (Test-Path -LiteralPath $FirstRunConfigPath)) {
        Remove-Item -LiteralPath $FirstRunConfigPath -Force -ErrorAction SilentlyContinue
    }
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
    Stop-EmbeddedBrain
    [Console]::Write($reset + $showCursor + $clear)
    try { [Console]::CursorVisible = $true } catch {}

    if ($LauncherMutex) {
        try { $LauncherMutex.ReleaseMutex() } catch {}
        $LauncherMutex.Dispose()
    }
}
