param(
    [string]$LmStudioBaseUrl = "http://localhost:1234",
    [string]$AppUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RecommendedModel = "google/gemma-3-12b-it"
$LauncherMutex = $null
$LauncherMutexName = "Global\JINCoreLauncher"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message"
}

function Fail-WithMessage {
    param([string]$Message)
    Write-Host ""
    Write-Host $Message
    exit 1
}

function Normalize-BaseUrl {
    param([string]$BaseUrl)

    if ($null -eq $BaseUrl) {
        return ""
    }

    return $BaseUrl.Trim().TrimEnd("/")
}

function Add-UniqueBaseUrl {
    param(
        [System.Collections.Generic.List[string]]$BaseUrls,
        [string]$BaseUrl
    )

    $normalized = Normalize-BaseUrl -BaseUrl $BaseUrl

    if ($normalized.Length -eq 0) {
        return
    }

    foreach ($existing in $BaseUrls) {
        if (
            [string]::Equals(
                $existing,
                $normalized,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        ) {
            return
        }
    }

    $BaseUrls.Add($normalized)
}

function Get-ModelIds {
    param($Response)

    $ids = New-Object System.Collections.Generic.List[string]

    if ($null -eq $Response) {
        return $ids
    }

    $items = @()

    if ($Response.PSObject.Properties.Name -contains "data") {
        $items = @($Response.data)
    }
    else {
        $items = @($Response)
    }

    foreach ($item in $items) {
        if ($null -eq $item) {
            continue
        }

        if ($item -is [string]) {
            if ($item.Trim().Length -gt 0) {
                $ids.Add($item.Trim())
            }
            continue
        }

        if ($item.PSObject.Properties.Name -contains "id") {
            $id = [string]$item.id
            if ($id.Trim().Length -gt 0) {
                $ids.Add($id.Trim())
            }
        }
    }

    return $ids
}

function Find-GemmaModel {
    param([string[]]$ModelIds)

    $preferredPatterns = @(
        "gemma-4",
        "gemma-3-27b",
        "gemma-3-12b",
        "gemma-3",
        "gemma"
    )

    foreach ($pattern in $preferredPatterns) {
        foreach ($modelId in $ModelIds) {
            if ($modelId.ToLowerInvariant().Contains($pattern)) {
                return $modelId
            }
        }
    }

    return $null
}

function Set-PythonConfigValue {
    param(
        [string]$Path,
        [string]$Name,
        [object]$Value
    )

    $content = Get-Content -Raw -Path $Path

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

    $pattern = "(?m)^$Name\s*=.*$"
    $replacement = "$Name = $renderedValue"
    $safeReplacement = $replacement.Replace('$', '$$')

    if ([regex]::IsMatch($content, $pattern)) {
        $content = [regex]::Replace($content, $pattern, $safeReplacement, 1)
    }
    else {
        $content = $content.TrimEnd() + "`r`n`r`n" + $replacement + "`r`n"
    }

    Set-Content -Path $Path -Value $content -Encoding UTF8
}

function Get-PythonConfigValue {
    param(
        [string]$Path,
        [string]$Name
    )

    if (-not (Test-Path $Path)) {
        return $null
    }

    $content = Get-Content -Raw -Path $Path
    $match = [regex]::Match(
        $content,
        "(?m)^\s*$Name\s*=\s*(?<value>.*?)(?:\s+#.*)?$"
    )

    if (-not $match.Success) {
        return $null
    }

    $rawValue = $match.Groups["value"].Value.Trim()

    if ($rawValue -match '^"(.*)"$') {
        return $Matches[1]
    }

    if ($rawValue -match "^'(.*)'$") {
        return $Matches[1]
    }

    if ($rawValue -in @("None", '$null')) {
        return ""
    }

    return $rawValue
}

function Test-AutoModelConfigValue {
    param(
        [string]$Name,
        [string]$Value
    )

    if ($null -eq $Value -or $Value.Trim().Length -eq 0) {
        return $true
    }

    $templateValues = @{
        "BRAIN_MODEL_UID" = "brain-model"
        "SERVICE_MODEL_UID" = "service-model"
        "TRANSLATOR_MODEL_UID" = "translator-model"
    }

    return (
        $templateValues.ContainsKey($Name) -and
        [string]::Equals(
            $Value,
            $templateValues[$Name],
            [System.StringComparison]::Ordinal
        )
    )
}

function Test-AutoProviderBaseValue {
    param(
        [string]$Name,
        [string]$Value
    )

    if ($null -eq $Value -or $Value.Trim().Length -eq 0) {
        return $true
    }

    $templateValues = @{
        "BRAIN_API_BASE" = "http://brain-host:1234"
        "SERVICE_API_BASE" = "http://service-host:1234"
        "TRANSLATOR_API_BASE" = "http://translator-host:1234"
    }

    return (
        $templateValues.ContainsKey($Name) -and
        [string]::Equals(
            $Value,
            $templateValues[$Name],
            [System.StringComparison]::OrdinalIgnoreCase
        )
    )
}

function Ensure-JinConfig {
    $configPath = Join-Path $Root "config.py"
    $examplePath = Join-Path $Root "config.example.py"

    if (Test-Path $configPath) {
        return $configPath
    }

    if (-not (Test-Path $examplePath)) {
        Fail-WithMessage "Cannot find config.py or config.example.py."
    }

    Write-Host "config.py is missing. Creating it from config.example.py..."
    Copy-Item -Path $examplePath -Destination $configPath

    return $configPath
}

function Get-ConfiguredBaseUrlCandidates {
    param([string]$ConfigPath)

    $baseUrls = New-Object System.Collections.Generic.List[string]
    $baseNames = @(
        "SERVICE_API_BASE",
        "BRAIN_API_BASE",
        "TRANSLATOR_API_BASE"
    )

    foreach ($name in $baseNames) {
        $value = Get-PythonConfigValue -Path $ConfigPath -Name $name

        if (Test-AutoProviderBaseValue -Name $name -Value $value) {
            continue
        }

        Add-UniqueBaseUrl -BaseUrls $baseUrls -BaseUrl $value
    }

    return $baseUrls
}

function Get-LmStudioModels {
    param([string[]]$BaseUrls)

    $checkedUrls = New-Object System.Collections.Generic.List[string]

    foreach ($baseUrl in $BaseUrls) {
        $normalizedBaseUrl = Normalize-BaseUrl -BaseUrl $baseUrl

        if ($normalizedBaseUrl.Length -eq 0) {
            continue
        }

        $modelsUrl = "$normalizedBaseUrl/v1/models"
        $checkedUrls.Add($modelsUrl)

        Write-Host "Checking LM Studio API: $modelsUrl"

        try {
            $modelsResponse = Invoke-RestMethod -Method Get -Uri $modelsUrl -TimeoutSec 5
            $modelIds = @(Get-ModelIds -Response $modelsResponse)

            return [pscustomobject]@{
                BaseUrl = $normalizedBaseUrl
                ModelsUrl = $modelsUrl
                ModelIds = $modelIds
            }
        }
        catch {
            Write-Host "No response from $modelsUrl"
        }
    }

    $checkedText = (
        $checkedUrls -join "`r`n"
    )

    Fail-WithMessage "LM Studio is not running.`r`nOpen LM Studio, start Local Server, then run this script again.`r`nChecked endpoints:`r`n$checkedText"
}

function Update-ProviderBaseConfig {
    param(
        [string]$ConfigPath,
        [string]$Name,
        [string]$ActiveBaseUrl
    )

    $currentValue = Get-PythonConfigValue -Path $ConfigPath -Name $Name

    if (Test-AutoProviderBaseValue -Name $Name -Value $currentValue) {
        Write-Host "$Name is empty/default. Setting it to $ActiveBaseUrl."
        Set-PythonConfigValue -Path $ConfigPath -Name $Name -Value $ActiveBaseUrl
        return
    }

    Write-Host "$Name already set. Keeping: $currentValue"
}

function Update-ModelConfig {
    param(
        [string]$ConfigPath,
        [string]$Name,
        [string]$SuggestedModel
    )

    $currentValue = Get-PythonConfigValue -Path $ConfigPath -Name $Name

    if (Test-AutoModelConfigValue -Name $Name -Value $currentValue) {
        if (-not $SuggestedModel) {
            Fail-WithMessage "No supported Gemma model found.`r`nRecommended default: $RecommendedModel`r`nPlease download it in LM Studio, then run this script again."
        }

        Write-Host "$Name is empty/default. Writing model: $SuggestedModel"
        Set-PythonConfigValue -Path $ConfigPath -Name $Name -Value $SuggestedModel
        return
    }

    Write-Host "$Name already set by user. Keeping: $currentValue"
}

function Write-JinConfig {
    param(
        [string]$ConfigPath,
        [string]$ActiveBaseUrl,
        [string[]]$ModelIds
    )

    $suggestedModel = Find-GemmaModel -ModelIds $ModelIds

    if ($suggestedModel) {
        Write-Host "Found supported Gemma model: $suggestedModel"
    }
    else {
        Write-Host "No supported Gemma model found in LM Studio."
        Write-Host "Recommended default: $RecommendedModel"
    }

    Update-ProviderBaseConfig -ConfigPath $configPath -Name "BRAIN_API_BASE" -ActiveBaseUrl $ActiveBaseUrl
    Update-ProviderBaseConfig -ConfigPath $configPath -Name "SERVICE_API_BASE" -ActiveBaseUrl $ActiveBaseUrl
    Update-ProviderBaseConfig -ConfigPath $configPath -Name "TRANSLATOR_API_BASE" -ActiveBaseUrl $ActiveBaseUrl

    Update-ModelConfig -ConfigPath $configPath -Name "BRAIN_MODEL_UID" -SuggestedModel $suggestedModel
    Update-ModelConfig -ConfigPath $configPath -Name "SERVICE_MODEL_UID" -SuggestedModel $suggestedModel
    Update-ModelConfig -ConfigPath $configPath -Name "TRANSLATOR_MODEL_UID" -SuggestedModel $suggestedModel
}

function Get-PythonCommand {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @($python.Source)
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @($py.Source, "-3")
    }

    Fail-WithMessage "Python was not found. Install Python 3, then run this script again."
}

try {
    $createdNew = $false
    $LauncherMutex = New-Object System.Threading.Mutex($true, $LauncherMutexName, [ref]$createdNew)

    if (-not $createdNew) {
        Write-Host "JIN launcher is already running."
        Write-Host "Use the existing launcher window instead of starting a second copy."
        exit 0
    }

    Set-Location $Root

    Write-Host "JIN one-click launcher"

    Write-Step "Checking LM Studio Local Server..."

    $configPath = Ensure-JinConfig
    $baseUrlCandidates = New-Object System.Collections.Generic.List[string]

    if ($PSBoundParameters.ContainsKey("LmStudioBaseUrl")) {
        Add-UniqueBaseUrl -BaseUrls $baseUrlCandidates -BaseUrl $LmStudioBaseUrl
    }

    $configuredBaseUrls = Get-ConfiguredBaseUrlCandidates -ConfigPath $configPath

    foreach ($baseUrl in $configuredBaseUrls) {
        Add-UniqueBaseUrl -BaseUrls $baseUrlCandidates -BaseUrl $baseUrl
    }

    Add-UniqueBaseUrl -BaseUrls $baseUrlCandidates -BaseUrl $LmStudioBaseUrl

    $lmStudio = Get-LmStudioModels -BaseUrls $baseUrlCandidates
    $LmStudioBaseUrl = $lmStudio.BaseUrl
    $modelIds = @($lmStudio.ModelIds)

    Write-Host "Using LM Studio API: $($lmStudio.ModelsUrl)"

    if ($modelIds.Count -eq 0) {
        Fail-WithMessage "No models returned by LM Studio.`r`nRecommended default: $RecommendedModel`r`nPlease download it in LM Studio, then run this script again."
    }

    Write-Host "Models returned by LM Studio:"
    foreach ($modelId in $modelIds) {
        Write-Host "  - $modelId"
    }

    Write-Host ""
    Write-Host "Checking local config model IDs..."
    Write-JinConfig -ConfigPath $configPath -ActiveBaseUrl $LmStudioBaseUrl -ModelIds $modelIds

    $venvPath = Join-Path $Root ".venv"
    $venvPython = Join-Path $venvPath "Scripts\python.exe"

    if (-not (Test-Path $venvPython)) {
        Write-Step "Creating .venv..."
        $pythonCommand = Get-PythonCommand
        $pythonExe = $pythonCommand[0]
        $pythonArgs = @()

        if ($pythonCommand.Length -gt 1) {
            $pythonArgs += $pythonCommand[1..($pythonCommand.Length - 1)]
        }

        & $pythonExe @pythonArgs -m venv $venvPath
    }
    else {
        Write-Step ".venv already exists."
    }

    if (-not (Test-Path $venvPython)) {
        Fail-WithMessage "Virtual environment was not created correctly."
    }

    Write-Step "Installing requirements..."
    & $venvPython -m pip install -r (Join-Path $Root "requirements.txt")

    Write-Step "Starting JIN backend..."
    Write-Host "Backend URL: $AppUrl"
    Write-Host "Opening browser shortly. Keep this window open while using JIN."

    $browserJob = Start-Job -ScriptBlock {
        param([string]$Url)

        for ($i = 0; $i -lt 30; $i++) {
            try {
                $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 1
                if ($response.StatusCode -lt 500) {
                    break
                }
            }
            catch {
                Start-Sleep -Seconds 1
            }
        }

        Start-Process $Url
    } -ArgumentList $AppUrl

    try {
        & $venvPython (Join-Path $Root "app.py")
    }
    finally {
        if ($browserJob.State -eq "Running") {
            Stop-Job $browserJob | Out-Null
        }

        Remove-Job $browserJob -Force -ErrorAction SilentlyContinue
    }
}
finally {
    if ($LauncherMutex) {
        try {
            $LauncherMutex.ReleaseMutex()
        }
        catch {
        }

        $LauncherMutex.Dispose()
    }
}
