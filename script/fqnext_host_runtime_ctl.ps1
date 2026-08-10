[CmdletBinding()]
param(
    [ValidateSet('Status', 'EnsureSupervisorService', 'StopSurfaces', 'RestartSurfaces', 'EnsureServiceAndRestartSurfaces', 'InvokeAdminBridge')]
    [string]$Mode = 'Status',
    [string[]]$DeploymentSurface = @(),
    [string]$SupervisorServiceName = 'fqnext-supervisord',
    [string]$RestartTaskName = 'fqnext-supervisord-restart',
    [string]$ConfigPath = 'D:\fqpack\config\supervisord.fqnext.conf',
    [string]$SupervisorConfigRepoRoot,
    [double]$TimeoutSeconds = 45,
    [switch]$BridgeIfServiceUnavailable
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonScript = Join-Path $repoRoot 'script\fqnext_host_runtime.py'
$supervisorConfigScript = Join-Path $repoRoot 'script\fqnext_supervisor_config.py'
$invokeBridgeScript = Join-Path $repoRoot 'script\invoke_fqnext_supervisord_restart_task.ps1'

function Resolve-Python312Command {
    $candidates = @()

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $candidates += [pscustomobject]@{
            Executable = $pyLauncher.Source
            PrefixArgs = @('-3.12')
        }
    }

    $fallbackExecutables = @(
        (Join-Path $repoRoot '.artifacts\bin\py.exe'),
        (Join-Path $repoRoot '.venv\Scripts\python.exe'),
        (Join-Path $repoRoot '.artifacts\python\cpython-3.12.13-windows-x86_64-none\python.exe')
    )

    foreach ($candidate in $fallbackExecutables) {
        if (Test-Path $candidate) {
            $candidates += [pscustomobject]@{
                Executable = $candidate
                PrefixArgs = @()
            }
        }
    }

    foreach ($candidate in $candidates) {
        try {
            & $candidate.Executable @($candidate.PrefixArgs + @('--version')) | Out-Null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        } catch {
            continue
        }
    }

    throw "Unable to resolve a usable Python 3.12 launcher. Checked py, repo-local py.exe, repo .venv, and workspace Python."
}

function Invoke-Python312 {
    param([string[]]$Arguments)

    $resolved = Resolve-Python312Command
    & $resolved.Executable @($resolved.PrefixArgs + $Arguments)
}

function Normalize-DeploymentSurfaces {
    param([string[]]$Surfaces)

    $normalized = [System.Collections.Generic.List[string]]::new()
    foreach ($surface in @($Surfaces)) {
        foreach ($token in @([string]$surface -split ',')) {
            $trimmed = $token.Trim()
            if (-not [string]::IsNullOrWhiteSpace($trimmed)) {
                $normalized.Add($trimmed)
            }
        }
    }

    return @($normalized)
}

function Test-IsElevatedSession {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-SupervisorService {
    param([string]$ServiceName)

    return Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
}

function Get-SupervisorServiceProcessStartTimeUtc {
    param([string]$ServiceName)

    $serviceInstance = Get-CimInstance Win32_Service -Filter "Name='$ServiceName'" -ErrorAction SilentlyContinue
    if ($null -eq $serviceInstance -or [int]$serviceInstance.ProcessId -le 0) {
        return $null
    }

    $process = Get-Process -Id ([int]$serviceInstance.ProcessId) -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $null
    }

    $startTime = $process.StartTime
    if ($null -eq $startTime) {
        return $null
    }

    return $startTime.ToUniversalTime()
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
        return [pscustomobject]@{
            Service = $service
            WasRecovered = $false
        }
    }

    if (Test-IsElevatedSession) {
        Start-Service -Name $ServiceName
        return [pscustomobject]@{
            Service = (Wait-ServiceRunning -ServiceName $ServiceName -TimeoutSeconds $TimeoutSeconds)
            WasRecovered = $true
        }
    }

    if ($AllowBridge -and (Test-Path $invokeBridgeScript)) {
        & $invokeBridgeScript -TaskName $TaskName -ServiceName $ServiceName -TimeoutSeconds ([int][Math]::Ceiling($TimeoutSeconds))
        return [pscustomobject]@{
            Service = (Wait-ServiceRunning -ServiceName $ServiceName -TimeoutSeconds $TimeoutSeconds)
            WasRecovered = $true
        }
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

    $resolvedSurfaces = @(Normalize-DeploymentSurfaces -Surfaces $Surfaces)

    $arguments = @($pythonScript, '--config-path', $ResolvedConfigPath, $Command)
    foreach ($surface in $resolvedSurfaces) {
        $arguments += @('--surface', $surface)
    }
    if ($Command -in @('stop-surfaces', 'restart-surfaces', 'wait-settled')) {
        $arguments += @('--timeout-seconds', [string]$TimeoutSeconds)
    }

    Invoke-Python312 -Arguments $arguments
    if ($LASTEXITCODE -ne 0) {
        throw "fqnext host runtime command failed: $Command"
    }
}

function Invoke-AdminBridgeRecovery {
    param(
        [string]$ServiceName,
        [string]$TaskName,
        [double]$TimeoutSeconds
    )

    if (-not (Test-Path $invokeBridgeScript)) {
        throw "Admin bridge script not found: $invokeBridgeScript"
    }

    & $invokeBridgeScript -TaskName $TaskName -ServiceName $ServiceName -TimeoutSeconds ([int][Math]::Ceiling($TimeoutSeconds))
    if ($LASTEXITCODE -ne 0) {
        throw "Admin bridge failed for service '$ServiceName'."
    }

    return Wait-ServiceRunning -ServiceName $ServiceName -TimeoutSeconds $TimeoutSeconds
}

function Test-HostRuntimeProgramsRunning {
    param([object]$Payload)

    if ($null -eq $Payload) {
        return $false
    }

    $programs = @($Payload.programs)
    if ($programs.Count -eq 0) {
        return $false
    }

    return @($programs | Where-Object { [string]$_.state -ne 'Running' }).Count -eq 0
}

function Get-HostRuntimeRunningPrograms {
    param([object]$Payload)

    if ($null -eq $Payload) {
        return @()
    }
    return @(
        $Payload.programs |
            Where-Object { [string]$_.state -eq 'Running' } |
            ForEach-Object { [string]$_.name }
    )
}

function Assert-HostRuntimeProgramsRunning {
    param(
        [object]$Payload,
        [string[]]$RequiredPrograms
    )

    $running = @(Get-HostRuntimeRunningPrograms -Payload $Payload)
    $missing = @($RequiredPrograms | Where-Object { $_ -notin $running })
    return [pscustomobject]@{
        ok = ($missing.Count -eq 0)
        missing = $missing
        running_count = $running.Count
        expected_count = $RequiredPrograms.Count
    }
}

function Get-DockerFqnextContainerCount {
    $names = & docker ps --filter "name=fqnext_20260223" --format "{{.Names}}" 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    return @($names | Where-Object { $_ }).Count
}

function Reload-SupervisorServiceForConfig {
    param(
        [string]$ServiceName,
        [string]$TaskName,
        [double]$TimeoutSeconds,
        [switch]$AllowBridge
    )

    $service = Get-SupervisorService -ServiceName $ServiceName
    if ($null -eq $service -or $service.Status -ne 'Running') {
        return $false
    }

    if (Test-IsElevatedSession) {
        Restart-Service -Name $ServiceName -Force
        Wait-ServiceRunning -ServiceName $ServiceName -TimeoutSeconds $TimeoutSeconds | Out-Null
        return $true
    }

    if ($AllowBridge) {
        Invoke-AdminBridgeRecovery -ServiceName $ServiceName -TaskName $TaskName -TimeoutSeconds $TimeoutSeconds | Out-Null
        return $true
    }

    throw "Supervisor config changed but service '$ServiceName' could not be reloaded without elevation or admin bridge."
}

function Sync-SupervisorConfig {
    param(
        [string]$TargetRepoRoot,
        [string]$ResolvedConfigPath,
        [string]$ServiceName,
        [string]$TaskName,
        [double]$TimeoutSeconds,
        [switch]$AllowBridge
    )

    if ([string]::IsNullOrWhiteSpace($TargetRepoRoot)) {
        return [pscustomobject]@{
            Changed = $false
            WasRecovered = $false
            ServiceReloadRequired = $false
            ConfigPath = $ResolvedConfigPath
        }
    }

    if (-not (Test-Path $supervisorConfigScript)) {
        throw "Supervisor config sync script not found: $supervisorConfigScript"
    }

    $raw = Invoke-Python312 -Arguments @($supervisorConfigScript, 'write', '--repo-root', $TargetRepoRoot, '--output-path', $ResolvedConfigPath)
    if ($LASTEXITCODE -ne 0) {
        throw "fqnext supervisor config write failed for repo root '$TargetRepoRoot'."
    }

    $payload = $raw | ConvertFrom-Json
    $serviceReloadRequired = [bool]$payload.changed
    if (-not $serviceReloadRequired -and (Test-Path $ResolvedConfigPath)) {
        $serviceStartTimeUtc = Get-SupervisorServiceProcessStartTimeUtc -ServiceName $ServiceName
        if ($null -eq $serviceStartTimeUtc) {
            # Some Windows service processes report a null StartTime; reload
            # conservatively so the in-memory supervisor config still converges.
            $serviceReloadRequired = $true
        }
        else {
            $configWriteTimeUtc = (Get-Item -LiteralPath $ResolvedConfigPath).LastWriteTimeUtc
            $serviceReloadRequired = $configWriteTimeUtc -gt $serviceStartTimeUtc
        }
    }

    $wasRecovered = $false
    if ($serviceReloadRequired) {
        $wasRecovered = Reload-SupervisorServiceForConfig -ServiceName $ServiceName -TaskName $TaskName -TimeoutSeconds $TimeoutSeconds -AllowBridge:$AllowBridge
    }

    return [pscustomobject]@{
        Changed = [bool]$payload.changed
        WasRecovered = [bool]$wasRecovered
        ServiceReloadRequired = [bool]$serviceReloadRequired
        ConfigPath = $ResolvedConfigPath
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
        $configSync = Sync-SupervisorConfig -TargetRepoRoot $SupervisorConfigRepoRoot -ResolvedConfigPath $ConfigPath -ServiceName $SupervisorServiceName -TaskName $RestartTaskName -TimeoutSeconds $TimeoutSeconds -AllowBridge:$BridgeIfServiceUnavailable
        $result = Ensure-SupervisorServiceRunning -ServiceName $SupervisorServiceName -TaskName $RestartTaskName -TimeoutSeconds $TimeoutSeconds -AllowBridge:$BridgeIfServiceUnavailable
        $service = $result.Service
        [ordered]@{
            service_name = $service.Name
            service_status = [string]$service.Status
            was_recovered = ([bool]$result.WasRecovered -or [bool]$configSync.WasRecovered)
            config_changed = [bool]$configSync.Changed
        } | ConvertTo-Json -Depth 4
        exit 0
    }
    'RestartSurfaces' {
        Invoke-HostRuntimePython -Command 'restart-surfaces' -Surfaces $DeploymentSurface -ResolvedConfigPath $ConfigPath -TimeoutSeconds $TimeoutSeconds
        exit 0
    }
    'StopSurfaces' {
        Invoke-HostRuntimePython -Command 'stop-surfaces' -Surfaces $DeploymentSurface -ResolvedConfigPath $ConfigPath -TimeoutSeconds $TimeoutSeconds
        exit 0
    }
    'EnsureServiceAndRestartSurfaces' {
        $configSync = Sync-SupervisorConfig -TargetRepoRoot $SupervisorConfigRepoRoot -ResolvedConfigPath $ConfigPath -ServiceName $SupervisorServiceName -TaskName $RestartTaskName -TimeoutSeconds $TimeoutSeconds -AllowBridge:$BridgeIfServiceUnavailable
        $result = Ensure-SupervisorServiceRunning -ServiceName $SupervisorServiceName -TaskName $RestartTaskName -TimeoutSeconds $TimeoutSeconds -AllowBridge:$BridgeIfServiceUnavailable
        $serviceRecovered = ([bool]$result.WasRecovered -or [bool]$configSync.WasRecovered)
        if ($serviceRecovered) {
            Invoke-HostRuntimePython -Command 'wait-settled' -Surfaces $DeploymentSurface -ResolvedConfigPath $ConfigPath -TimeoutSeconds $TimeoutSeconds
        }
        $bridgeRetried = $false
        try {
            Invoke-HostRuntimePython -Command 'restart-surfaces' -Surfaces $DeploymentSurface -ResolvedConfigPath $ConfigPath -TimeoutSeconds $TimeoutSeconds
        } catch {
            $originalMessage = $_.Exception.Message
            if (-not $BridgeIfServiceUnavailable) {
                throw
            }
            if ($originalMessage -match 'FAKE_START_DETECTED') {
                # P3-C: supervisord-go state machine wedged (fake start). Recover at
                # service level: restart fqnext-supervisord, autostart pulls all programs.
                Write-Warning "supervisor fake start detected; recovering via service restart. error=$originalMessage"
                Invoke-AdminBridgeRecovery -ServiceName $SupervisorServiceName -TaskName $RestartTaskName -TimeoutSeconds $TimeoutSeconds | Out-Null
                $recoveredPayload = Invoke-HostRuntimePython -Command 'wait-settled' -Surfaces $DeploymentSurface -ResolvedConfigPath $ConfigPath -TimeoutSeconds $TimeoutSeconds | ConvertFrom-Json
                $recoveredRunning = Test-HostRuntimeProgramsRunning -Payload $recoveredPayload
                if (-not $recoveredRunning) {
                    throw "host runtime not Running after fake-start service restart. error=$originalMessage"
                }
            } else {
                if ($bridgeRetried) {
                    throw
                }
                $bridgeRetried = $true
                Invoke-AdminBridgeRecovery -ServiceName $SupervisorServiceName -TaskName $RestartTaskName -TimeoutSeconds $TimeoutSeconds | Out-Null
                $bridgeSettledPayload = Invoke-HostRuntimePython -Command 'wait-settled' -Surfaces $DeploymentSurface -ResolvedConfigPath $ConfigPath -TimeoutSeconds $TimeoutSeconds | ConvertFrom-Json
                $bridgeRecoveredRunning = Test-HostRuntimeProgramsRunning -Payload $bridgeSettledPayload
                if (-not $bridgeRecoveredRunning) {
                    try {
                        Invoke-HostRuntimePython -Command 'restart-surfaces' -Surfaces $DeploymentSurface -ResolvedConfigPath $ConfigPath -TimeoutSeconds $TimeoutSeconds
                    } catch {
                        throw "fqnext host runtime restart failed after admin bridge retry. initial_error=$originalMessage retry_error=$($_.Exception.Message)"
                    }
                }
            }
        }

        # P3-B: validate all supervisor programs Running (9/9); explicitly restart
        # tpsl if not Running; fail the deploy if it still is not Running.
        $statusPayload = Invoke-HostRuntimePython -Command 'status' -Surfaces $DeploymentSurface -ResolvedConfigPath $ConfigPath -TimeoutSeconds $TimeoutSeconds | ConvertFrom-Json
        $requiredPrograms = @($statusPayload.programs | ForEach-Object { [string]$_.name })
        $validation = Assert-HostRuntimeProgramsRunning -Payload $statusPayload -RequiredPrograms $requiredPrograms
        if (-not $validation.ok) {
            Write-Warning "host runtime validation: running=$($validation.running_count)/$($validation.expected_count) missing=$($validation.missing -join ',')"
            if ('fqnext_tpsl_worker' -in $validation.missing) {
                Write-Warning "tpsl worker not Running; explicit restart attempt."
                try {
                    Invoke-HostRuntimePython -Command 'restart-surfaces' -Surfaces @('tpsl') -ResolvedConfigPath $ConfigPath -TimeoutSeconds $TimeoutSeconds | Out-Null
                } catch {
                    throw "tpsl explicit start failed after validation: $($_.Exception.Message)"
                }
                $retryPayload = Invoke-HostRuntimePython -Command 'status' -Surfaces @('tpsl') -ResolvedConfigPath $ConfigPath -TimeoutSeconds $TimeoutSeconds | ConvertFrom-Json
                $retryValidation = Assert-HostRuntimeProgramsRunning -Payload $retryPayload -RequiredPrograms @('fqnext_tpsl_worker')
                if (-not $retryValidation.ok) {
                    throw "tpsl worker still not Running after explicit start; deploy run must fail."
                }
            }
            $remainingMissing = @($validation.missing | Where-Object { $_ -ne 'fqnext_tpsl_worker' })
            if ($remainingMissing.Count -gt 0) {
                throw "host runtime programs not Running after restart: $($remainingMissing -join ',')"
            }
        }
        $dockerCount = Get-DockerFqnextContainerCount
        if ($null -ne $dockerCount -and $dockerCount -lt 10) {
            Write-Warning "docker fqnext containers up=$dockerCount/10; verify compose stack."
        } else {
            Write-Output "docker fqnext containers up=$dockerCount/10"
        }
        exit 0
    }
    'InvokeAdminBridge' {
        Invoke-AdminBridgeRecovery -ServiceName $SupervisorServiceName -TaskName $RestartTaskName -TimeoutSeconds $TimeoutSeconds | Out-Null
        exit 0
    }
}
