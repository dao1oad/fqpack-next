[CmdletBinding()]
param(
    [string]$ServiceRoot = 'D:\fqpack\runtime\symphony-service',
    [string]$OpenAISymphonyRoot = 'D:\fqpack\tools\dao1oad-symphony\elixir',
    [int]$Port = 40123
)

$ErrorActionPreference = 'Stop'

function Get-EnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    foreach ($scope in 'Process', 'User', 'Machine') {
        $value = [Environment]::GetEnvironmentVariable($Name, $scope)
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value
        }
    }

    return $null
}

function Resolve-CommandPath {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Candidates
    )

    foreach ($candidate in $Candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    return $null
}

function Resolve-OpenAISymphonyRoot {
    param(
        [string]$RequestedPath
    )

    $candidates = @()

    foreach ($name in 'FRESHQUANT_OPENAI_SYMPHONY_ROOT', 'OPENAI_SYMPHONY_ROOT') {
        $value = Get-EnvValue -Name $name
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            $candidates += $value
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
        $candidates += $RequestedPath
    }

    $candidates += @(
        'D:\fqpack\tools\dao1oad-symphony\elixir',
        'D:\fqpack\tools\openai-symphony\elixir'
    )

    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path $candidate)) {
            return [System.IO.Path]::GetFullPath($candidate).TrimEnd('\')
        }
    }

    $message = ($candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique) -join ', '
    throw "OpenAI Symphony elixir root not found. Checked: $message"
}

function Add-PathPrefix {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Directories
    )

    $existingPath = [Environment]::GetEnvironmentVariable('PATH', 'Process')
    $pathEntries = @()
    if (-not [string]::IsNullOrWhiteSpace($existingPath)) {
        $pathEntries = $existingPath.Split(';') | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    }

    $newEntries = @()
    foreach ($directory in $Directories) {
        if (-not [string]::IsNullOrWhiteSpace($directory) -and (Test-Path $directory)) {
            $normalized = [System.IO.Path]::GetFullPath($directory).TrimEnd('\')
            if ($pathEntries -notcontains $normalized -and $newEntries -notcontains $normalized) {
                $newEntries += $normalized
            }
        }
    }

    if ($newEntries.Count -gt 0) {
        [Environment]::SetEnvironmentVariable('PATH', (($newEntries + $pathEntries) -join ';'), 'Process')
    }
}

$configRoot = Join-Path $ServiceRoot 'config'
$scriptsRoot = Join-Path $ServiceRoot 'scripts'
$logsRoot = Join-Path $ServiceRoot 'logs'
$workflowPath = Join-Path $configRoot 'WORKFLOW.freshquant.md'
$workflowValidator = Join-Path $scriptsRoot 'assert_freshquant_workflow_prompt.ps1'
$mergingPromptPath = Join-Path $configRoot 'prompts\merging.md'
$mergingPromptValidator = Join-Path $scriptsRoot 'assert_freshquant_merging_prompt.ps1'
$globalStewardshipPromptPath = Join-Path $configRoot 'prompts\global_stewardship.md'
$globalStewardshipPromptValidator = Join-Path $scriptsRoot 'assert_freshquant_global_stewardship_prompt.ps1'
$runnerPath = Join-Path $scriptsRoot 'freshquant_runner.exs'
$stdoutLog = Join-Path $logsRoot 'stdout.log'
$stderrLog = Join-Path $logsRoot 'stderr.log'
$traceLog = Join-Path $logsRoot 'app-server.trace.log'
$gitBashBin = Join-Path ${env:ProgramFiles} 'Git\bin'
$codexShimBin = Join-Path $env:APPDATA 'npm'
$mixPath = Resolve-CommandPath @(
    (Join-Path $env:USERPROFILE 'AppData\Local\mise\installs\elixir\1.19.5-otp-28\bin\mix.bat'),
    'C:\Users\Administrator\AppData\Local\mise\installs\elixir\1.19.5-otp-28\bin\mix.bat'
)
$erlPath = Resolve-CommandPath @(
    (Join-Path $env:USERPROFILE 'AppData\Local\mise\installs\erlang\28.4\bin\erl.exe'),
    (Join-Path $env:USERPROFILE 'AppData\Local\mise\installs\erlang\28.4\erts-16.3\bin\erl.exe'),
    'C:\Users\Administrator\AppData\Local\mise\installs\erlang\28.4\bin\erl.exe',
    'C:\Users\Administrator\AppData\Local\mise\installs\erlang\28.4\erts-16.3\bin\erl.exe'
)

if (-not (Test-Path $workflowPath)) {
    throw "Workflow file not found: $workflowPath"
}

if (-not (Test-Path $workflowValidator)) {
    throw "Workflow validator not found: $workflowValidator"
}

if (-not (Test-Path $mergingPromptPath)) {
    throw "Merging prompt file not found: $mergingPromptPath"
}

if (-not (Test-Path $mergingPromptValidator)) {
    throw "Merging prompt validator not found: $mergingPromptValidator"
}

if (-not (Test-Path $globalStewardshipPromptPath)) {
    throw "Global Stewardship prompt file not found: $globalStewardshipPromptPath"
}

if (-not (Test-Path $globalStewardshipPromptValidator)) {
    throw "Global Stewardship prompt validator not found: $globalStewardshipPromptValidator"
}

if (-not (Test-Path $runnerPath)) {
    throw "Runner file not found: $runnerPath"
}

& $workflowValidator -WorkflowPath $workflowPath
& $mergingPromptValidator -PromptPath $mergingPromptPath
& $globalStewardshipPromptValidator -PromptPath $globalStewardshipPromptPath

$OpenAISymphonyRoot = Resolve-OpenAISymphonyRoot -RequestedPath $OpenAISymphonyRoot

if (-not $mixPath) {
    $mixCommand = Get-Command mix.bat -ErrorAction SilentlyContinue
    if ($mixCommand) {
        $mixPath = $mixCommand.Source
    }
}

if (-not $mixPath) {
    throw 'mix.bat not found. Install Elixir via mise and ensure mix.bat is available.'
}

if (-not $erlPath) {
    $erlCommand = Get-Command erl.exe -ErrorAction SilentlyContinue
    if ($erlCommand) {
        $erlPath = $erlCommand.Source
    }
}

if (-not $erlPath) {
    throw 'erl.exe not found. Install Erlang via mise and ensure erl.exe is available.'
}

New-Item -ItemType Directory -Force -Path $logsRoot | Out-Null

$elixirBin = Split-Path -Parent $mixPath
$erlangBin = Split-Path -Parent $erlPath
Add-PathPrefix -Directories @($gitBashBin, $codexShimBin, $elixirBin, $erlangBin)

$passthroughVars = @('GITHUB_TOKEN', 'GH_TOKEN', 'FRESHQUANT_GITHUB_REPO', 'GITHUB_REPOSITORY')
foreach ($name in $passthroughVars) {
    $value = Get-EnvValue -Name $name
    if ($value) {
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

$proxyEnvNames = @("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy")
foreach ($name in $proxyEnvNames) {
    [Environment]::SetEnvironmentVariable($name, '', 'Process')
}

[Environment]::SetEnvironmentVariable('SYMPHONY_WORKFLOW_PATH', $workflowPath, 'Process')
[Environment]::SetEnvironmentVariable('SYMPHONY_SERVICE_PORT', $Port.ToString(), 'Process')
[Environment]::SetEnvironmentVariable('SYMPHONY_SERVICE_ROOT', $ServiceRoot, 'Process')
[Environment]::SetEnvironmentVariable('SYMP_APP_SERVER_TRACE', $traceLog, 'Process')
[Environment]::SetEnvironmentVariable('SYMPHONY_LOG_FILE', $stdoutLog, 'Process')
[Environment]::SetEnvironmentVariable('ERLANG_HOME', (Split-Path -Parent $erlangBin), 'Process')
[Environment]::SetEnvironmentVariable('ELIXIR_HOME', (Split-Path -Parent $elixirBin), 'Process')

Write-Host "[freshquant] starting symphony"
Write-Host "[freshquant] source:   $OpenAISymphonyRoot"
Write-Host "[freshquant] workflow: $workflowPath"
Write-Host "[freshquant] runner:   $runnerPath"
Write-Host "[freshquant] port:     $Port"

Push-Location $OpenAISymphonyRoot
try {
    & $mixPath run --no-start $runnerPath
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
