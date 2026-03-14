[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ServiceName = 'fqnext-supervisord',
    [string]$SupervisordExe = 'D:\fqpack\supervisord\supervisord.exe',
    [string]$ConfigPath = 'D:\fqpack\config\supervisord.fqnext.conf',
    [string]$ServiceUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
    [string]$ServicePassword,
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

function Set-ServiceLogonAccount {
    param(
        [string]$ResolvedServiceName,
        [string]$ResolvedServiceUser,
        [string]$ResolvedServicePassword
    )

    if ($ResolvedServicePassword -eq '') {
        $commandLine = "sc.exe config `"$ResolvedServiceName`" obj= `"$ResolvedServiceUser`" password= `"`""
        $output = & cmd.exe /c $commandLine 2>&1
    }
    else {
        $output = & sc.exe config $ResolvedServiceName obj= $ResolvedServiceUser password= $ResolvedServicePassword 2>&1
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

if (-not (Test-Path $SupervisordExe)) {
    throw "supervisord.exe not found: $SupervisordExe"
}

if (-not (Test-Path $ConfigPath)) {
    throw "Supervisor config not found: $ConfigPath"
}

$blankPasswordAllowed = (Get-LimitBlankPasswordUse) -eq 0
if ($null -eq $ServicePassword) {
    if (-not $blankPasswordAllowed) {
        throw "ServicePassword is required when installing $ServiceName under account $ServiceUser."
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
    throw 'Installing or updating fqnext-supervisord requires an elevated PowerShell session (Run as Administrator).'
}

$serviceExists = $null -ne (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)
$supervisordRoot = Split-Path -Parent $SupervisordExe
$stdoutLog = 'D:\fqdata\log\fqnext_supervisord_service_stdout.log'
$stderrLog = 'D:\fqdata\log\fqnext_supervisord_service_stderr.log'
$appParameters = "/c `"$ConfigPath`""

if ($PSCmdlet.ShouldProcess($ServiceName, 'Install or update fqnext-supervisord service')) {
    if (-not $serviceExists) {
        & $nssm install $ServiceName $SupervisordExe $appParameters | Out-Null
    }

    & $nssm set $ServiceName Application $SupervisordExe | Out-Null
    & $nssm set $ServiceName AppParameters $appParameters | Out-Null
    & $nssm set $ServiceName AppDirectory $supervisordRoot | Out-Null
    & $nssm set $ServiceName Start SERVICE_DELAYED_AUTO_START | Out-Null
    & $nssm set $ServiceName AppStdout $stdoutLog | Out-Null
    & $nssm set $ServiceName AppStderr $stderrLog | Out-Null
    & $nssm set $ServiceName AppExit Default Restart | Out-Null
    & $nssm set $ServiceName AppRestartDelay 5000 | Out-Null
    Set-ServiceLogonAccount -ResolvedServiceName $ServiceName -ResolvedServiceUser $ServiceUser -ResolvedServicePassword $ServicePassword
}

Write-Host "[freshquant] installed service $ServiceName"
Write-Host "[freshquant] service entrypoint: $SupervisordExe /c $ConfigPath"
