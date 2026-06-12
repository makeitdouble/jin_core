param(
    [string]$LmStudioBaseUrl = "http://localhost:1234",
    [string]$AppUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ModelsUrl = "$LmStudioBaseUrl/v1/models"
$RecommendedModel = "google/gemma-3-12b-it"

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

    if ([regex]::IsMatch($content, $pattern)) {
        $content = [regex]::Replace($content, $pattern, $replacement, 1)
    }
    else {
        $content = $content.TrimEnd() + "`r`n`r`n" + $replacement + "`r`n"
    }

    Set-Content -Path $Path -Value $content -Encoding UTF8
}

function Write-JinConfig {
    param([string]$ModelId)

    $configPath = Join-Path $Root "config.py"
    $examplePath = Join-Path $Root "config.example.py"

    if (-not (Test-Path $configPath)) {
        if (-not (Test-Path $examplePath)) {
            Fail-WithMessage "Cannot find config.py or config.example.py."
        }

        Write-Host "config.py is missing. Creating it from config.example.py..."
        Copy-Item -Path $examplePath -Destination $configPath
    }

    Set-PythonConfigValue -Path $configPath -Name "USE_SERVICE_AS_BRAIN" -Value $true
    Set-PythonConfigValue -Path $configPath -Name "TRANSLATION_ENABLED" -Value $false
    Set-PythonConfigValue -Path $configPath -Name "BRAIN_API_BASE" -Value $LmStudioBaseUrl
    Set-PythonConfigValue -Path $configPath -Name "SERVICE_API_BASE" -Value $LmStudioBaseUrl
    Set-PythonConfigValue -Path $configPath -Name "TRANSLATOR_API_BASE" -Value $LmStudioBaseUrl
    Set-PythonConfigValue -Path $configPath -Name "BRAIN_MODEL_UID" -Value $ModelId
    Set-PythonConfigValue -Path $configPath -Name "SERVICE_MODEL_UID" -Value $ModelId
    Set-PythonConfigValue -Path $configPath -Name "TRANSLATOR_MODEL_UID" -Value $ModelId
    Set-PythonConfigValue -Path $configPath -Name "CHAT_ENDPOINT" -Value "/v1/chat/completions"
    Set-PythonConfigValue -Path $configPath -Name "MODELS_ENDPOINT" -Value "/v1/models"
    Set-PythonConfigValue -Path $configPath -Name "NATIVE_MODELS_ENDPOINT" -Value "/api/v0/models"
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

Set-Location $Root

Write-Host "JIN one-click launcher"
Write-Host "LM Studio API: $ModelsUrl"

Write-Step "Checking LM Studio Local Server..."

try {
    $modelsResponse = Invoke-RestMethod -Method Get -Uri $ModelsUrl -TimeoutSec 5
}
catch {
    Fail-WithMessage "LM Studio is not running.`r`nOpen LM Studio, start Local Server, then run this script again."
}

$modelIds = @(Get-ModelIds -Response $modelsResponse)

if ($modelIds.Count -eq 0) {
    Fail-WithMessage "No models returned by LM Studio.`r`nRecommended default: $RecommendedModel`r`nPlease download it in LM Studio, then run this script again."
}

Write-Host "Models returned by LM Studio:"
foreach ($modelId in $modelIds) {
    Write-Host "  - $modelId"
}

$selectedModel = Find-GemmaModel -ModelIds $modelIds

if (-not $selectedModel) {
    Fail-WithMessage "No supported Gemma model found.`r`nRecommended default: $RecommendedModel`r`nPlease download it in LM Studio, then run this script again."
}

Write-Host ""
Write-Host "Found model: $selectedModel"
Write-Host "Writing it to config..."
Write-JinConfig -ModelId $selectedModel

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
