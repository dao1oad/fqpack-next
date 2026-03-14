[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TaskName = 'fqnext-supervisord-restart',
    [string]$ServiceName = 'fqnext-supervisord',
    [int]$Port = 10011,
    [string]$StatusPath = 'D:\fqpack\supervisord\artifacts\admin-bridge\restart-status.json',
    [string]$TaskScriptRoot = 'D:\fqpack\supervisord\scripts'
)

$ErrorActionPreference = 'Stop'

function Test-IsElevatedSession {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-CurrentUserSid {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    return $identity.User.Value
}

function Test-TaskAceGrantsReadAndExecute {
    param(
        [Parameter(Mandatory = $true)][string]$SecurityDescriptor,
        [Parameter(Mandatory = $true)][string]$UserSid
    )

    $aceMatches = [regex]::Matches(
        $SecurityDescriptor,
        '\((?<type>[^;]+);(?<flags>[^;]*);(?<rights>[^;]*);(?<object>[^;]*);(?<inherit>[^;]*);(?<sid>[^)]+)\)'
    )

    foreach ($aceMatch in $aceMatches) {
        if ($aceMatch.Groups['type'].Value -ne 'A') {
            continue
        }

        if ($aceMatch.Groups['sid'].Value -ne $UserSid) {
            continue
        }

        $rights = $aceMatch.Groups['rights'].Value
        if (
            $rights -match 'FA' -or
            $rights -match 'GA' -or
            (($rights -match 'FR') -and ($rights -match 'FX')) -or
            (($rights -match 'GR') -and ($rights -match 'GX'))
        ) {
            return $true
        }
    }

    return $false
}

function Grant-TaskReadAndExecuteAccess {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$UserSid
    )

    $schedule = New-Object -ComObject 'Schedule.Service'
    $schedule.Connect()
    $rootFolder = $schedule.GetFolder('\')
    $task = $rootFolder.GetTask($TaskName)
    $securityDescriptor = $task.GetSecurityDescriptor(7)
    $readAndExecuteAce = "(A;;FRFX;;;$UserSid)"

    if (Test-TaskAceGrantsReadAndExecute -SecurityDescriptor $securityDescriptor -UserSid $UserSid) {
        return
    }

    $daclIndex = $securityDescriptor.IndexOf('D:')
    if ($daclIndex -lt 0) {
        throw "Task '$TaskName' security descriptor does not contain a DACL: $securityDescriptor"
    }

    $saclIndex = $securityDescriptor.IndexOf('S:', $daclIndex + 2)
    if ($saclIndex -ge 0) {
        $updatedSecurityDescriptor = $securityDescriptor.Insert($saclIndex, $readAndExecuteAce)
    }
    else {
        $updatedSecurityDescriptor = $securityDescriptor + $readAndExecuteAce
    }

    $task.SetSecurityDescriptor($updatedSecurityDescriptor, 0)
}

$sourceTaskScriptPath = Join-Path $PSScriptRoot 'run_fqnext_supervisord_restart_task.ps1'
if (-not (Test-Path $sourceTaskScriptPath)) {
    throw "Task runner script not found: $sourceTaskScriptPath"
}

$resolvedTaskScriptRoot = [System.IO.Path]::GetFullPath($TaskScriptRoot)
$taskScriptPath = Join-Path $resolvedTaskScriptRoot 'run_fqnext_supervisord_restart_task.ps1'

if ($PSCmdlet.ShouldProcess($taskScriptPath, "Copy from $sourceTaskScriptPath")) {
    New-Item -ItemType Directory -Force -Path $resolvedTaskScriptRoot | Out-Null
    Copy-Item -Path $sourceTaskScriptPath -Destination $taskScriptPath -Force
}

$powershellExe = Join-Path $PSHOME 'powershell.exe'
$arguments = @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-File', ('"{0}"' -f $taskScriptPath),
    '-ServiceName', ('"{0}"' -f $ServiceName),
    '-Port', $Port.ToString(),
    '-StatusPath', ('"{0}"' -f $StatusPath)
) -join ' '

$action = New-ScheduledTaskAction -Execute $powershellExe -Argument $arguments
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

if ($PSCmdlet.ShouldProcess($TaskName, 'Register fqnext supervisor restart task')) {
    if (-not (Test-IsElevatedSession)) {
        throw 'Registering the fqnext supervisor restart task requires an elevated PowerShell session (Run as Administrator).'
    }

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Principal $principal `
        -Settings $settings `
        -Description 'Restart fqnext-supervisord and verify its XML-RPC port is reachable.' `
        -Force | Out-Null

    Grant-TaskReadAndExecuteAccess -TaskName $TaskName -UserSid (Get-CurrentUserSid)
}

Write-Host "[freshquant] restart task ready: $TaskName"
