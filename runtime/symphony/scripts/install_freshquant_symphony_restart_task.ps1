[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TaskName = 'fq-symphony-orchestrator-restart',
    [string]$ServiceName = 'fq-symphony-orchestrator',
    [string]$ServiceRoot = 'D:\fqpack\runtime\symphony-service',
    [int]$Port = 40123,
    [string]$StatusPath
)

$ErrorActionPreference = 'Stop'

function Test-IsElevatedSession {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Resolve-StatusPath {
    param(
        [string]$ExplicitPath,
        [string]$ResolvedServiceRoot
    )

    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        return [System.IO.Path]::GetFullPath($ExplicitPath)
    }

    return Join-Path $ResolvedServiceRoot 'artifacts\admin-bridge\restart-status.json'
}

function Get-CurrentUserSid {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    return $identity.User.Value
}

function Grant-TaskReadAndExecuteAccess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TaskName,
        [Parameter(Mandatory = $true)]
        [string]$UserSid
    )

    $schedule = New-Object -ComObject 'Schedule.Service'
    $schedule.Connect()
    $rootFolder = $schedule.GetFolder('\')
    $task = $rootFolder.GetTask($TaskName)
    $securityDescriptor = $task.GetSecurityDescriptor(7)
    $escapedUserSid = [regex]::Escape($UserSid)
    $readAndExecuteAce = "(A;;FRFX;;;$UserSid)"

    if ($securityDescriptor -match "\(A;;[A-Z]+;;;$escapedUserSid\)") {
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

$resolvedServiceRoot = [System.IO.Path]::GetFullPath($ServiceRoot).TrimEnd('\')
$syncScriptPath = Join-Path $PSScriptRoot 'sync_freshquant_symphony_service.ps1'
$taskScriptPath = Join-Path $resolvedServiceRoot 'scripts\run_freshquant_symphony_restart_task.ps1'
$resolvedStatusPath = Resolve-StatusPath -ExplicitPath $StatusPath -ResolvedServiceRoot $resolvedServiceRoot
$statusDirectory = Split-Path -Parent $resolvedStatusPath

if (-not (Test-Path $syncScriptPath)) {
    throw "Sync script not found: $syncScriptPath"
}

if (-not [string]::IsNullOrWhiteSpace($statusDirectory)) {
    New-Item -ItemType Directory -Force -Path $statusDirectory | Out-Null
}

& $syncScriptPath -ServiceRoot $resolvedServiceRoot -WhatIf:$WhatIfPreference

if (-not (Test-Path $taskScriptPath)) {
    if ($WhatIfPreference) {
        Write-Warning "Restart task script is not present yet at $taskScriptPath. This is expected when sync runs under -WhatIf."
    }
    else {
        throw "Restart task script not found after sync: $taskScriptPath"
    }
}

$powershellExe = Join-Path $PSHOME 'powershell.exe'
$arguments = @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-File', ('"{0}"' -f $taskScriptPath),
    '-ServiceName', ('"{0}"' -f $ServiceName),
    '-ServiceRoot', ('"{0}"' -f $resolvedServiceRoot),
    '-Port', $Port.ToString(),
    '-StatusPath', ('"{0}"' -f $resolvedStatusPath)
) -join ' '

$action = New-ScheduledTaskAction -Execute $powershellExe -Argument $arguments
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

if ($PSCmdlet.ShouldProcess($TaskName, 'Register FreshQuant Symphony restart task')) {
    if (-not (Test-IsElevatedSession)) {
        throw 'Registering the restart task requires an elevated PowerShell session (Run as Administrator).'
    }

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Principal $principal `
        -Settings $settings `
        -Description 'Restart FreshQuant Symphony orchestrator and verify its local health endpoint.' `
        -Force | Out-Null

    Grant-TaskReadAndExecuteAccess -TaskName $TaskName -UserSid (Get-CurrentUserSid)
}

Write-Host "[freshquant] restart task ready: $TaskName"
Write-Host "[freshquant] invoke from normal sessions with runtime/symphony/scripts/invoke_freshquant_symphony_restart_task.ps1"
