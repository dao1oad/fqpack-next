[CmdletBinding()]
param(
    [ValidateSet('Status', 'EnsureSupervisorService', 'RestartSurfaces', 'EnsureServiceAndRestartSurfaces', 'InvokeAdminBridge')]
    [string]$Mode = 'Status',
    [string[]]$DeploymentSurface = @(),
    [string]$SupervisorServiceName = 'fqnext-supervisord',
    [string]$RestartTaskName = 'fqnext-supervisord-restart',
    [string]$ConfigPath = 'D:\fqpack\config\supervisord.fqnext.conf',
    [double]$TimeoutSeconds = 45,
    [switch]$BridgeIfServiceUnavailable
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonScript = Join-Path $repoRoot 'script\fqnext_host_runtime.py'
$invokeBridgeScript = Join-Path $repoRoot 'script\invoke_fqnext_supervisord_restart_task.ps1'

function Test-IsElevatedSession {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-SupervisorService {
    param([string]$ServiceName)

    return Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
}

function Wait-ServiceRunning {
    param(
        [string]$ServiceName,
        [double]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $service = Get-SupervisorService -ServiceName $ServiceName
        if ($null -ne $service -and $service.Status -eq 'Running') {
            return $service
        }
        Start-Sleep -Seconds 1
    }

    throw "Service '$ServiceName' did not reach Running within $TimeoutSeconds seconds."
}

function Ensure-SupervisorServiceRunning {
    param(
        [string]$ServiceName,
        [string]$TaskName,
        [double]$TimeoutSeconds,
        [switch]$AllowBridge
    )

    $service = Get-SupervisorService -ServiceName $ServiceName
    if ($null -eq $service) {
        throw "Supervisor service not found: $ServiceName"
    }

    if ($service.Status -eq 'Running') {
        return $service
    }

    if (Test-IsElevatedSession) {
        Start-Service -Name $ServiceName
        return Wait-ServiceRunning -ServiceName $ServiceName -TimeoutSeconds $TimeoutSeconds
    }

    if ($AllowBridge -and (Test-Path $invokeBridgeScript)) {
        & $invokeBridgeScript -TaskName $TaskName -ServiceName $ServiceName -TimeoutSeconds ([int][Math]::Ceiling($TimeoutSeconds))
        return Wait-ServiceRunning -ServiceName $ServiceName -TimeoutSeconds $TimeoutSeconds
    }

    throw "Supervisor service '$ServiceName' is not Running and no admin bridge was used."
}

function Invoke-HostRuntimePython {
    param(
        [string]$Command,
        [string[]]$Surfaces,
        [string]$ResolvedConfigPath,
        [double]$TimeoutSeconds
    )

    if (-not (Test-Path $pythonScript)) {
        throw "Host runtime script not found: $pythonScript"
    }

    $arguments = @('-3.12', $pythonScript, '--config-path', $ResolvedConfigPath, $Command)
    foreach ($surface in @($Surfaces)) {
        $arguments += @('--surface', $surface)
    }
    if ($Command -eq 'restart-surfaces') {
        $arguments += @('--timeout-seconds', [string]$TimeoutSeconds)
    }

    & py @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "fqnext host runtime command failed: $Command"
    }
}

switch ($Mode) {
    'Status' {
        $service = Get-SupervisorService -ServiceName $SupervisorServiceName
        if ($null -eq $service -or $service.Status -ne 'Running') {
            $payload = [ordered]@{
                service_name = $SupervisorServiceName
                service_status = if ($null -eq $service) { 'Missing' } else { [string]$service.Status }
                rpc_ready = $false
                note = 'Use install_fqnext_supervisord_service.ps1 or admin bridge to recover the host runtime base.'
            }
            $payload | ConvertTo-Json -Depth 6
            exit 0
        }

        Invoke-HostRuntimePython -Command 'status' -Surfaces $DeploymentSurface -ResolvedConfigPath $ConfigPath -TimeoutSeconds $TimeoutSeconds
        exit 0
    }
    'EnsureSupervisorService' {
        $service = Ensure-SupervisorServiceRunning -ServiceName $SupervisorServiceName -TaskName $RestartTaskName -TimeoutSeconds $TimeoutSeconds -AllowBridge:$BridgeIfServiceUnavailable
        [ordered]@{
            service_name = $service.Name
            service_status = [string]$service.Status
        } | ConvertTo-Json -Depth 4
        exit 0
    }
    'RestartSurfaces' {
        Invoke-HostRuntimePython -Command 'restart-surfaces' -Surfaces $DeploymentSurface -ResolvedConfigPath $ConfigPath -TimeoutSeconds $TimeoutSeconds
        exit 0
    }
    'EnsureServiceAndRestartSurfaces' {
        Ensure-SupervisorServiceRunning -ServiceName $SupervisorServiceName -TaskName $RestartTaskName -TimeoutSeconds $TimeoutSeconds -AllowBridge:$BridgeIfServiceUnavailable | Out-Null
        Invoke-HostRuntimePython -Command 'restart-surfaces' -Surfaces $DeploymentSurface -ResolvedConfigPath $ConfigPath -TimeoutSeconds $TimeoutSeconds
        exit 0
    }
    'InvokeAdminBridge' {
        if (-not (Test-Path $invokeBridgeScript)) {
            throw "Admin bridge script not found: $invokeBridgeScript"
        }
        & $invokeBridgeScript -TaskName $RestartTaskName -ServiceName $SupervisorServiceName -TimeoutSeconds ([int][Math]::Ceiling($TimeoutSeconds))
        exit $LASTEXITCODE
    }
}
