[CmdletBinding()]
param(
    [string]$ServiceRoot = 'D:\fqpack\runtime\symphony-service',
    [string]$OpenAISymphonyRoot = 'D:\fqpack\tools\openai-symphony\elixir',
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
$runnerPath = Join-Path $scriptsRoot 'freshquant_runner.exs'
$stdoutLog = Join-Path $logsRoot 'stdout.log'
$stderrLog = Join-Path $logsRoot 'stderr.log'
$traceLog = Join-Path $logsRoot 'app-server.trace.log'
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

if (-not (Test-Path $runnerPath)) {
    throw "Runner file not found: $runnerPath"
}

if (-not (Test-Path $OpenAISymphonyRoot)) {
    throw "OpenAI Symphony elixir root not found: $OpenAISymphonyRoot"
}

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
Add-PathPrefix -Directories @($elixirBin, $erlangBin)

$proxyVars = @('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'LINEAR_API_KEY')
foreach ($name in $proxyVars) {
    $value = Get-EnvValue -Name $name
    if ($value) {
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

[Environment]::SetEnvironmentVariable('SYMPHONY_WORKFLOW_PATH', $workflowPath, 'Process')
[Environment]::SetEnvironmentVariable('SYMPHONY_SERVICE_PORT', $Port.ToString(), 'Process')
[Environment]::SetEnvironmentVariable('SYMPHONY_SERVICE_ROOT', $ServiceRoot, 'Process')
[Environment]::SetEnvironmentVariable('SYMP_APP_SERVER_TRACE', $traceLog, 'Process')
[Environment]::SetEnvironmentVariable('SYMPHONY_LOG_FILE', $stdoutLog, 'Process')
[Environment]::SetEnvironmentVariable('ERLANG_HOME', (Split-Path -Parent $erlangBin), 'Process')
[Environment]::SetEnvironmentVariable('ELIXIR_HOME', (Split-Path -Parent $elixirBin), 'Process')

Write-Host "[freshquant] starting symphony"
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
