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

New-Item -ItemType Directory -Force -Path $logsRoot | Out-Null

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

Write-Host "[freshquant] starting symphony"
Write-Host "[freshquant] workflow: $workflowPath"
Write-Host "[freshquant] runner:   $runnerPath"
Write-Host "[freshquant] port:     $Port"

Push-Location $OpenAISymphonyRoot
try {
    & $mixPath run --no-start $runnerPath 2>> $stderrLog | Tee-Object -FilePath $stdoutLog -Append
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
