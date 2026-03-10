[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ServiceName = 'fq-symphony-orchestrator',
    [string]$ServiceRoot = 'D:\fqpack\runtime\symphony-service',
    [string]$OpenAISymphonyRoot = 'D:\fqpack\tools\openai-symphony\elixir',
    [string]$ServiceUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
    [string]$ServicePassword,
    [int]$Port = 40123,
    [string]$NssmPath
)

$ErrorActionPreference = 'Stop'

function Resolve-NssmPath {
    param([string]$ExplicitPath)

    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        if (Test-Path $ExplicitPath) {
            return $ExplicitPath
        }

        throw "NSSM path not found: $ExplicitPath"
    }

    $command = Get-Command nssm -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $fallbacks = @(
        'D:\fqpack\tools\nssm\nssm.exe',
        (Join-Path $env:ProgramFiles 'nssm\nssm.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'nssm\nssm.exe')
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

    foreach ($candidate in $fallbacks) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    return $null
}

$nssm = Resolve-NssmPath -ExplicitPath $NssmPath
if (-not $nssm) {
    throw 'nssm not found. Install NSSM first or pass -NssmPath.'
}

$syncScript = Join-Path $PSScriptRoot 'sync_freshquant_symphony_service.ps1'
$startScript = Join-Path (Join-Path $ServiceRoot 'scripts') 'start_freshquant_symphony.ps1'
$stdoutLog = Join-Path (Join-Path $ServiceRoot 'logs') 'stdout.log'
$stderrLog = Join-Path (Join-Path $ServiceRoot 'logs') 'stderr.log'

if (-not $ServicePassword) {
    throw "ServicePassword is required when installing a Windows service under the current account ($ServiceUser)."
}

& $syncScript -ServiceRoot $ServiceRoot

$powershellExe = Join-Path $PSHOME 'powershell.exe'
$appParameters = "-ExecutionPolicy Bypass -File `"$startScript`" -ServiceRoot `"$ServiceRoot`" -OpenAISymphonyRoot `"$OpenAISymphonyRoot`" -Port $Port"

if ($PSCmdlet.ShouldProcess($ServiceName, 'Install or update NSSM service')) {
    & $nssm install $ServiceName $powershellExe $appParameters | Out-Null
    & $nssm set $ServiceName AppDirectory $OpenAISymphonyRoot | Out-Null
    & $nssm set $ServiceName Start SERVICE_DELAYED_AUTO_START | Out-Null
    & $nssm set $ServiceName AppStdout $stdoutLog | Out-Null
    & $nssm set $ServiceName AppStderr $stderrLog | Out-Null
    & $nssm set $ServiceName AppExit Default Restart | Out-Null
    & $nssm set $ServiceName AppRestartDelay 5000 | Out-Null
    & $nssm set $ServiceName ObjectName $ServiceUser $ServicePassword | Out-Null
}

Write-Host "[freshquant] installed service $ServiceName"
Write-Host "[freshquant] use Restart-Service $ServiceName after template updates"
