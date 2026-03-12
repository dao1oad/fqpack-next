[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ServiceName = 'fq-symphony-orchestrator',
    [string]$ServiceRoot = 'D:\fqpack\runtime\symphony-service',
    [string]$OpenAISymphonyRoot = 'D:\fqpack\tools\dao1oad-symphony\elixir',
    [string]$ServiceUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
    [string]$ServicePassword,
    [int]$Port = 40123,
    [string]$NssmPath
)

$ErrorActionPreference = 'Stop'

function Test-IsElevatedSession {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-LimitBlankPasswordUse {
    $lsa = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Lsa'
    return [int]$lsa.LimitBlankPasswordUse
}

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

function Get-EnvValue {
    param([string]$Name)

    foreach ($scope in 'Process', 'User', 'Machine') {
        $value = [Environment]::GetEnvironmentVariable($Name, $scope)
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value
        }
    }

    return $null
}

function Resolve-OpenAISymphonyRoot {
    param([string]$RequestedPath)

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

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path $candidate)) {
            return [System.IO.Path]::GetFullPath($candidate).TrimEnd('\')
        }
    }

    $message = ($candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique) -join ', '
    throw "OpenAI Symphony elixir root not found. Checked: $message"
}

function Set-ServiceLogonAccount {
    param(
        [string]$ServiceName,
        [string]$ServiceUser,
        [string]$ServicePassword
    )

    if ($ServicePassword -eq '') {
        $commandLine = "sc.exe config `"$ServiceName`" obj= `"$ServiceUser`" password= `"`""
        $output = & cmd.exe /c $commandLine 2>&1
    }
    else {
        $output = & sc.exe config $ServiceName obj= $ServiceUser password= $ServicePassword 2>&1
    }

    if ($LASTEXITCODE -ne 0) {
        $message = ($output | Out-String).Trim()
        throw "Failed to configure service logon account: $message"
    }
}

$nssm = Resolve-NssmPath -ExplicitPath $NssmPath
if (-not $nssm) {
    throw 'nssm not found. Install NSSM first or pass -NssmPath.'
}

$syncScript = Join-Path $PSScriptRoot 'sync_freshquant_symphony_service.ps1'
$startScript = Join-Path (Join-Path $ServiceRoot 'scripts') 'start_freshquant_symphony.ps1'
$stdoutLog = Join-Path (Join-Path $ServiceRoot 'logs') 'stdout.log'
$stderrLog = Join-Path (Join-Path $ServiceRoot 'logs') 'stderr.log'

$OpenAISymphonyRoot = Resolve-OpenAISymphonyRoot -RequestedPath $OpenAISymphonyRoot

$blankPasswordAllowed = (Get-LimitBlankPasswordUse) -eq 0

if ($null -eq $ServicePassword) {
    if (-not $blankPasswordAllowed) {
        throw "ServicePassword is required when installing a Windows service under the current account ($ServiceUser)."
    }

    $ServicePassword = ''
}
elseif ([string]::IsNullOrWhiteSpace($ServicePassword)) {
    if (-not $blankPasswordAllowed) {
        throw "Blank passwords are blocked by the current LimitBlankPasswordUse policy for account $ServiceUser."
    }

    $ServicePassword = ''
}

if (-not (Test-IsElevatedSession)) {
    throw 'Installing or updating the Symphony Windows service requires an elevated PowerShell session (Run as Administrator).'
}

& $syncScript -ServiceRoot $ServiceRoot

$powershellExe = Join-Path $PSHOME 'powershell.exe'
$appParameters = "-ExecutionPolicy Bypass -File `"$startScript`" -ServiceRoot `"$ServiceRoot`" -OpenAISymphonyRoot `"$OpenAISymphonyRoot`" -Port $Port"
$serviceExists = $null -ne (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)

if ($PSCmdlet.ShouldProcess($ServiceName, 'Install or update NSSM service')) {
    if (-not $serviceExists) {
        & $nssm install $ServiceName $powershellExe $appParameters | Out-Null
    }

    & $nssm set $ServiceName Application $powershellExe | Out-Null
    & $nssm set $ServiceName AppParameters $appParameters | Out-Null
    & $nssm set $ServiceName AppDirectory $OpenAISymphonyRoot | Out-Null
    & $nssm set $ServiceName Start SERVICE_DELAYED_AUTO_START | Out-Null
    & $nssm set $ServiceName AppStdout $stdoutLog | Out-Null
    & $nssm set $ServiceName AppStderr $stderrLog | Out-Null
    & $nssm set $ServiceName AppExit Default Restart | Out-Null
    & $nssm set $ServiceName AppRestartDelay 5000 | Out-Null
    Set-ServiceLogonAccount -ServiceName $ServiceName -ServiceUser $ServiceUser -ServicePassword $ServicePassword
}

Write-Host "[freshquant] installed service $ServiceName"
Write-Host "[freshquant] use Restart-Service $ServiceName after template updates"
