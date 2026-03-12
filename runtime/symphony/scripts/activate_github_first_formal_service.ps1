[CmdletBinding()]
param(
    [string]$ServiceName = 'fq-symphony-orchestrator',
    [string]$ServiceRoot = 'D:\fqpack\runtime\symphony-service',
    [string]$Port = '40123',
    [string]$Repository = 'dao1oad/fqpack-next',
    [string]$FreshQuantRuntimeSourceRoot = 'D:\fqpack\worktrees\fqpack-next-github-governance\runtime\symphony',
    [string]$SymphonySourceRoot = 'D:\fqpack\worktrees\dao1oad-symphony-github\elixir',
    [string]$OpenAISymphonyRoot = 'D:\fqpack\tools\dao1oad-symphony\elixir',
    [string]$NssmPath = 'D:\fqpack\tools\nssm\nssm.exe',
    [string]$ServicePassword,
    [switch]$StopTemporaryGithubInstance = $true
)

$ErrorActionPreference = 'Stop'

function Test-IsElevatedSession {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-EnvValue {
    param([Parameter(Mandatory = $true)][string]$Name)

    foreach ($scope in 'Process', 'User', 'Machine') {
        $value = [Environment]::GetEnvironmentVariable($Name, $scope)
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value
        }
    }

    return $null
}

function Resolve-GitHubToken {
    $token = Get-EnvValue -Name 'GH_TOKEN'
    if (-not [string]::IsNullOrWhiteSpace($token)) {
        return $token
    }

    $token = Get-EnvValue -Name 'GITHUB_TOKEN'
    if (-not [string]::IsNullOrWhiteSpace($token)) {
        return $token
    }

    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if ($gh) {
        $resolved = (& $gh.Source auth token 2>$null)
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($resolved)) {
            return $resolved.Trim()
        }
    }

    throw 'Unable to resolve GitHub token from GH_TOKEN/GITHUB_TOKEN or gh auth token.'
}

function Assert-PathExists {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not (Test-Path $Path)) {
        throw "$Label not found: $Path"
    }
}

function Set-MachineEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$Token,
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][string]$OpenAISymphonyRoot
    )

    [Environment]::SetEnvironmentVariable('GH_TOKEN', $Token, 'Machine')
    [Environment]::SetEnvironmentVariable('GITHUB_TOKEN', $Token, 'Machine')
    [Environment]::SetEnvironmentVariable('FRESHQUANT_GITHUB_REPO', $Repository, 'Machine')
    [Environment]::SetEnvironmentVariable('GITHUB_REPOSITORY', $Repository, 'Machine')
    [Environment]::SetEnvironmentVariable('FRESHQUANT_OPENAI_SYMPHONY_ROOT', $OpenAISymphonyRoot, 'Machine')
    [Environment]::SetEnvironmentVariable('OPENAI_SYMPHONY_ROOT', $OpenAISymphonyRoot, 'Machine')

    [Environment]::SetEnvironmentVariable('GH_TOKEN', $Token, 'Process')
    [Environment]::SetEnvironmentVariable('GITHUB_TOKEN', $Token, 'Process')
    [Environment]::SetEnvironmentVariable('FRESHQUANT_GITHUB_REPO', $Repository, 'Process')
    [Environment]::SetEnvironmentVariable('GITHUB_REPOSITORY', $Repository, 'Process')
    [Environment]::SetEnvironmentVariable('FRESHQUANT_OPENAI_SYMPHONY_ROOT', $OpenAISymphonyRoot, 'Process')
    [Environment]::SetEnvironmentVariable('OPENAI_SYMPHONY_ROOT', $OpenAISymphonyRoot, 'Process')
}

function Sync-SymphonySource {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    $null = New-Item -ItemType Directory -Force -Path $Destination
    & robocopy $Source $Destination /E /R:2 /W:1 /XD .git _build deps .elixir_ls log
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed with exit code $LASTEXITCODE"
    }
}

function Stop-TemporaryInstance {
    $targets = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -like '*symphony-service-github*'
    }

    foreach ($target in $targets) {
        try {
            Stop-Process -Id $target.ProcessId -Force -ErrorAction Stop
        }
        catch {
            Write-Warning "Failed to stop temporary GitHub instance PID=$($target.ProcessId): $($_.Exception.Message)"
        }
    }
}

if (-not (Test-IsElevatedSession)) {
    throw 'Run this script in an elevated PowerShell session (Run as Administrator).'
}

Assert-PathExists -Path $FreshQuantRuntimeSourceRoot -Label 'FreshQuant runtime source root'
Assert-PathExists -Path $SymphonySourceRoot -Label 'Symphony source root'
Assert-PathExists -Path $NssmPath -Label 'NSSM'

$reinstallScriptPath = Join-Path $FreshQuantRuntimeSourceRoot 'scripts\reinstall_freshquant_symphony_service.ps1'
Assert-PathExists -Path $reinstallScriptPath -Label 'Reinstall script'

$token = Resolve-GitHubToken
Set-MachineEnvironment -Token $token -Repository $Repository -OpenAISymphonyRoot $OpenAISymphonyRoot

Write-Host '[freshquant] syncing dao1oad-symphony runtime'
Sync-SymphonySource -Source $SymphonySourceRoot -Destination $OpenAISymphonyRoot

if ($StopTemporaryGithubInstance) {
    Write-Host '[freshquant] stopping temporary symphony-service-github processes'
    Stop-TemporaryInstance
}

$reinstallArgs = @(
    '-ExecutionPolicy', 'Bypass',
    '-File', $reinstallScriptPath,
    '-ServiceName', $ServiceName,
    '-ServiceRoot', $ServiceRoot,
    '-OpenAISymphonyRoot', $OpenAISymphonyRoot,
    '-Port', $Port
)

if (-not [string]::IsNullOrWhiteSpace($ServicePassword)) {
    $reinstallArgs += @('-ServicePassword', $ServicePassword)
}

Write-Host '[freshquant] reinstalling formal Symphony service'
& powershell.exe @reinstallArgs
if ($LASTEXITCODE -ne 0) {
    throw "Reinstall script failed with exit code $LASTEXITCODE"
}

Write-Host '[freshquant] reading service AppParameters'
& $NssmPath get $ServiceName AppParameters

Write-Host '[freshquant] formal service health'
$state = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/v1/state"
$state.Content
