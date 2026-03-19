[CmdletBinding()]
param(
    [string[]]$ChangedPath = @(),
    [string]$FromGitDiff,
    [string[]]$DeploymentSurface = @(),
    [switch]$RunHealthChecks,
    [switch]$RunRuntimeOpsCheck,
    [string]$StatePath,
    [string]$ResumeFromStatePath,
    [switch]$ResumeLatest
)

$ErrorActionPreference = "Stop"

function Resolve-PythonLauncher {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return @{
            Path = $venvPython
            Prefix = @()
        }
    }

    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        return @{
            Path = $pyCommand.Source
            Prefix = @("-3.12")
        }
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return @{
            Path = $pythonCommand.Source
            Prefix = @()
        }
    }

    throw "Python launcher not found in PATH."
}

function Write-Utf8NoBomFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )

    $directory = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($directory)) {
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
    }

    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function ConvertTo-IsoTimestamp {
    param([datetime]$Value)

    return $Value.ToString("o")
}

function Resolve-ArtifactRoot {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    return Join-Path $RepoRoot ".artifacts\manual-deploy"
}

function Resolve-OptionalPath {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$PathValue
    )

    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return $PathValue
    }

    return Join-Path $RepoRoot $PathValue
}

function New-PhaseState {
    param([string]$Status = "pending")

    return [ordered]@{
        status = $Status
        started_at = $null
        completed_at = $null
        error = $null
    }
}

function Ensure-PhaseState {
    param(
        [Parameter(Mandatory = $true)]$State,
        [Parameter(Mandatory = $true)][string]$PhaseName
    )

    $existing = $State.phases.PSObject.Properties[$PhaseName]
    if ($null -eq $existing) {
        $State.phases | Add-Member -NotePropertyName $PhaseName -NotePropertyValue ([pscustomobject](New-PhaseState)) -Force
    }

    return $State.phases.$PhaseName
}

function Save-DeployState {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$State
    )

    $State.updated_at = ConvertTo-IsoTimestamp -Value (Get-Date)
    $json = $State | ConvertTo-Json -Depth 16
    Write-Utf8NoBomFile -Path $Path -Content $json
}

function Resolve-LatestStatePath {
    param([Parameter(Mandatory = $true)][string]$ArtifactRoot)

    if (-not (Test-Path $ArtifactRoot)) {
        throw "Deploy state artifact root not found: $ArtifactRoot"
    }

    $latest = Get-ChildItem -LiteralPath $ArtifactRoot -Filter "deploy-state-*.json" -File |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $latest) {
        throw "No deploy state file found under: $ArtifactRoot"
    }

    return $latest.FullName
}

function Initialize-DeployState {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)]$Plan,
        [Parameter(Mandatory = $true)][string[]]$EffectiveChangedPaths,
        [Parameter(Mandatory = $true)][string[]]$EffectiveDeploymentSurface,
        [Parameter(Mandatory = $true)][bool]$EffectiveRunHealthChecks,
        [Parameter(Mandatory = $true)][bool]$EffectiveRunRuntimeOpsCheck,
        [string]$EffectiveFromGitDiff,
        [string]$PlanSummary
    )

    return [pscustomobject][ordered]@{
        schema_version = 1
        repo_root = $RepoRoot
        created_at = ConvertTo-IsoTimestamp -Value (Get-Date)
        updated_at = $null
        inputs = [pscustomobject][ordered]@{
            changed_paths = @($EffectiveChangedPaths)
            from_git_diff = $EffectiveFromGitDiff
            deployment_surfaces = @($EffectiveDeploymentSurface)
            run_health_checks = $EffectiveRunHealthChecks
            run_runtime_ops_check = $EffectiveRunRuntimeOpsCheck
        }
        plan = $Plan
        plan_summary = $PlanSummary
        artifacts = [pscustomobject][ordered]@{
            baseline_path = $null
            verify_path = $null
        }
        phases = [pscustomobject][ordered]@{
            baseline = [pscustomobject](New-PhaseState)
            docker = [pscustomobject](New-PhaseState)
            host = [pscustomobject](New-PhaseState)
            health = [pscustomobject](New-PhaseState)
            verify = [pscustomobject](New-PhaseState)
        }
    }
}

function Sync-PhaseStatuses {
    param([Parameter(Mandatory = $true)]$State)

    $phaseEnabled = @{
        baseline = [bool]$State.inputs.run_runtime_ops_check
        docker = (@($State.plan.docker_services).Count -gt 0)
        host = (@($State.plan.host_surfaces).Count -gt 0)
        health = ([bool]$State.inputs.run_health_checks -and @($State.plan.health_checks).Count -gt 0)
        verify = [bool]$State.inputs.run_runtime_ops_check
    }

    foreach ($phaseName in @("baseline", "docker", "host", "health", "verify")) {
        $phaseState = Ensure-PhaseState -State $State -PhaseName $PhaseName
        $enabled = [bool]$phaseEnabled[$phaseName]
        $status = [string]$phaseState.status

        if (-not $enabled) {
            if ($status -ne "completed") {
                $phaseState.status = "skipped"
                $phaseState.error = $null
            }
            continue
        }

        if ([string]::IsNullOrWhiteSpace($status) -or $status -eq "skipped" -or $status -eq "running") {
            $phaseState.status = "pending"
            if ($status -eq "running") {
                $phaseState.error = "reset to pending during resume"
            }
        }
    }
}

function Get-OrCreateArtifactPath {
    param(
        [Parameter(Mandatory = $true)]$State,
        [Parameter(Mandatory = $true)][string]$ArtifactRoot,
        [Parameter(Mandatory = $true)][string]$PropertyName,
        [Parameter(Mandatory = $true)][string]$Prefix
    )

    $existing = $State.artifacts.PSObject.Properties[$PropertyName]
    if ($null -ne $existing -and -not [string]::IsNullOrWhiteSpace([string]$existing.Value)) {
        return [string]$existing.Value
    }

    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $path = Join-Path $ArtifactRoot "$Prefix-$timestamp.json"
    $State.artifacts.$PropertyName = $path
    return $path
}

function Invoke-CheckedPhase {
    param(
        [Parameter(Mandatory = $true)]$State,
        [Parameter(Mandatory = $true)][string]$StateFilePath,
        [Parameter(Mandatory = $true)][string]$PhaseName,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    $phaseState = Ensure-PhaseState -State $State -PhaseName $PhaseName
    $phaseState.status = "running"
    $phaseState.started_at = ConvertTo-IsoTimestamp -Value (Get-Date)
    $phaseState.completed_at = $null
    $phaseState.error = $null
    Save-DeployState -Path $StateFilePath -State $State

    try {
        & $Action
        $phaseState.status = "completed"
        $phaseState.completed_at = ConvertTo-IsoTimestamp -Value (Get-Date)
        $phaseState.error = $null
        Save-DeployState -Path $StateFilePath -State $State
    }
    catch {
        $phaseState.status = "failed"
        $phaseState.completed_at = ConvertTo-IsoTimestamp -Value (Get-Date)
        $phaseState.error = $_.Exception.Message
        Save-DeployState -Path $StateFilePath -State $State
        throw
    }
}

if ($ResumeLatest -and -not [string]::IsNullOrWhiteSpace($ResumeFromStatePath)) {
    throw "ResumeLatest and ResumeFromStatePath cannot be used together."
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$artifactRoot = Resolve-ArtifactRoot -RepoRoot $repoRoot
$pythonLauncher = Resolve-PythonLauncher -RepoRoot $repoRoot
$deployPlanScript = Join-Path $repoRoot "script\freshquant_deploy_plan.py"
$composeScript = Join-Path $repoRoot "script\docker_parallel_compose.ps1"
$hostRuntimeScript = Join-Path $repoRoot "script\fqnext_host_runtime_ctl.ps1"
$runtimeOpsScript = Join-Path $repoRoot "runtime\symphony\scripts\check_freshquant_runtime_post_deploy.ps1"

$stateFilePath = $null
$state = $null
$plan = $null

if ($ResumeLatest -or -not [string]::IsNullOrWhiteSpace($ResumeFromStatePath)) {
    $stateFilePath = if ($ResumeLatest) {
        Resolve-LatestStatePath -ArtifactRoot $artifactRoot
    }
    else {
        Resolve-OptionalPath -RepoRoot $repoRoot -PathValue $ResumeFromStatePath
    }

    if (-not (Test-Path $stateFilePath)) {
        throw "Deploy state file not found: $stateFilePath"
    }

    $state = Get-Content -LiteralPath $stateFilePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($null -eq $state.plan) {
        throw "Deploy state file is missing plan payload: $stateFilePath"
    }

    $plan = $state.plan
    Write-Host "[freshquant] resuming deploy state: $stateFilePath"
    if (-not [string]::IsNullOrWhiteSpace([string]$state.plan_summary)) {
        Write-Host ([string]$state.plan_summary)
    }
}
else {
    $allChangedPaths = New-Object System.Collections.Generic.List[string]
    foreach ($path in $ChangedPath) {
        if (-not [string]::IsNullOrWhiteSpace($path)) {
            $allChangedPaths.Add($path)
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($FromGitDiff)) {
        $diffPaths = (& git -C $repoRoot diff --name-only $FromGitDiff 2>$null)
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to resolve changed paths from git diff range: $FromGitDiff"
        }
        foreach ($path in $diffPaths) {
            if (-not [string]::IsNullOrWhiteSpace($path)) {
                $allChangedPaths.Add($path.Trim())
            }
        }
    }

    $planArgs = @()
    foreach ($path in $allChangedPaths) {
        $planArgs += @("--changed-path", $path)
    }
    foreach ($surface in $DeploymentSurface) {
        if (-not [string]::IsNullOrWhiteSpace($surface)) {
            $planArgs += @("--deployment-surface", $surface)
        }
    }

    $planJson = & $pythonLauncher.Path @(
        $pythonLauncher.Prefix + @(
            $deployPlanScript,
            "--format",
            "json"
        ) + $planArgs
    )
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    $plan = $planJson | ConvertFrom-Json

    $summaryText = & $pythonLauncher.Path @(
        $pythonLauncher.Prefix + @(
            $deployPlanScript,
            "--format",
            "summary"
        ) + $planArgs
    )
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($summaryText)) {
        Write-Host $summaryText
    }

    if (-not [bool]$plan.deployment_required) {
        Write-Host "[freshquant] no deployment required for current inputs."
        exit 0
    }

    $stateFilePath = if (-not [string]::IsNullOrWhiteSpace($StatePath)) {
        Resolve-OptionalPath -RepoRoot $repoRoot -PathValue $StatePath
    }
    else {
        $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
        Join-Path $artifactRoot "deploy-state-$timestamp.json"
    }

    $state = Initialize-DeployState `
        -RepoRoot $repoRoot `
        -Plan $plan `
        -EffectiveChangedPaths @($allChangedPaths.ToArray()) `
        -EffectiveDeploymentSurface @($DeploymentSurface) `
        -EffectiveRunHealthChecks ([bool]$RunHealthChecks.IsPresent) `
        -EffectiveRunRuntimeOpsCheck ([bool]$RunRuntimeOpsCheck.IsPresent) `
        -EffectiveFromGitDiff $FromGitDiff `
        -PlanSummary ([string]$summaryText)

    Save-DeployState -Path $stateFilePath -State $state
    Write-Host "[freshquant] deploy state: $stateFilePath"
}

Sync-PhaseStatuses -State $state
Save-DeployState -Path $stateFilePath -State $state

$baselinePath = [string]$state.artifacts.baseline_path
if ([string]::IsNullOrWhiteSpace($baselinePath) -and [bool]$state.inputs.run_runtime_ops_check) {
    $baselinePath = Get-OrCreateArtifactPath -State $state -ArtifactRoot $artifactRoot -PropertyName "baseline_path" -Prefix "runtime-baseline"
    Save-DeployState -Path $stateFilePath -State $state
}

if ((Ensure-PhaseState -State $state -PhaseName "baseline").status -eq "pending") {
    Invoke-CheckedPhase -State $state -StateFilePath $stateFilePath -PhaseName "baseline" -Action {
        & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $runtimeOpsScript -Mode CaptureBaseline -OutputPath $baselinePath | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Runtime baseline capture failed with exit code $LASTEXITCODE"
        }
    }
}

if ((Ensure-PhaseState -State $state -PhaseName "docker").status -eq "pending") {
    Invoke-CheckedPhase -State $state -StateFilePath $stateFilePath -PhaseName "docker" -Action {
        & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $composeScript "up" "-d" "--build" @($plan.docker_services)
        if ($LASTEXITCODE -ne 0) {
            throw "Docker deploy failed with exit code $LASTEXITCODE"
        }
    }
}

if ((Ensure-PhaseState -State $state -PhaseName "host").status -eq "pending") {
    Invoke-CheckedPhase -State $state -StateFilePath $stateFilePath -PhaseName "host" -Action {
        & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $hostRuntimeScript -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface ((@($plan.host_surfaces)) -join ",") -BridgeIfServiceUnavailable
        if ($LASTEXITCODE -ne 0) {
            throw "Host runtime reconcile failed with exit code $LASTEXITCODE"
        }
    }
}

if ((Ensure-PhaseState -State $state -PhaseName "health").status -eq "pending") {
    Invoke-CheckedPhase -State $state -StateFilePath $stateFilePath -PhaseName "health" -Action {
        foreach ($url in @($plan.health_checks)) {
            Invoke-WebRequest -UseBasicParsing $url | Out-Null
        }
    }
}

$verifyPath = [string]$state.artifacts.verify_path
if ([string]::IsNullOrWhiteSpace($verifyPath) -and [bool]$state.inputs.run_runtime_ops_check) {
    $verifyPath = Get-OrCreateArtifactPath -State $state -ArtifactRoot $artifactRoot -PropertyName "verify_path" -Prefix "runtime-verify"
    Save-DeployState -Path $stateFilePath -State $state
}

if ((Ensure-PhaseState -State $state -PhaseName "verify").status -eq "pending") {
    Invoke-CheckedPhase -State $state -StateFilePath $stateFilePath -PhaseName "verify" -Action {
        & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $runtimeOpsScript -Mode Verify -BaselinePath $baselinePath -OutputPath $verifyPath -DeploymentSurface ((@($plan.runtime_ops_surfaces)) -join ",")
        if ($LASTEXITCODE -ne 0) {
            throw "Runtime verification failed with exit code $LASTEXITCODE"
        }
    }
}

Write-Host "[freshquant] deploy completed. state=$stateFilePath"
exit 0
