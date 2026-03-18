[CmdletBinding()]
param(
    [string[]]$ChangedPath = @(),
    [string]$FromGitDiff,
    [string[]]$DeploymentSurface = @(),
    [switch]$RunHealthChecks,
    [switch]$RunRuntimeOpsCheck
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

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonLauncher = Resolve-PythonLauncher -RepoRoot $repoRoot
$deployPlanScript = Join-Path $repoRoot "script\freshquant_deploy_plan.py"
$composeScript = Join-Path $repoRoot "script\docker_parallel_compose.ps1"
$hostRuntimeScript = Join-Path $repoRoot "script\fqnext_host_runtime_ctl.ps1"
$runtimeOpsScript = Join-Path $repoRoot "runtime\symphony\scripts\check_freshquant_runtime_post_deploy.ps1"

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

$baselinePath = $null
if ($RunRuntimeOpsCheck) {
    $artifactRoot = Join-Path $repoRoot ".artifacts\manual-deploy"
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $baselinePath = Join-Path $artifactRoot "runtime-baseline-$timestamp.json"
    & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $runtimeOpsScript -Mode CaptureBaseline -OutputPath $baselinePath | Out-Null
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

if ($plan.docker_services.Count -gt 0) {
    & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $composeScript "up" "-d" "--build" @($plan.docker_services)
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

if ($plan.host_surfaces.Count -gt 0) {
    & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $hostRuntimeScript -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface (($plan.host_surfaces) -join ",") -BridgeIfServiceUnavailable
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

if ($RunHealthChecks) {
    foreach ($url in $plan.health_checks) {
        Invoke-WebRequest -UseBasicParsing $url | Out-Null
    }
}

if ($RunRuntimeOpsCheck -and $baselinePath) {
    $artifactRoot = Join-Path $repoRoot ".artifacts\manual-deploy"
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $verifyPath = Join-Path $artifactRoot "runtime-verify-$timestamp.json"
    & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $runtimeOpsScript -Mode Verify -BaselinePath $baselinePath -OutputPath $verifyPath -DeploymentSurface (($plan.runtime_ops_surfaces) -join ",")
    exit $LASTEXITCODE
}

exit 0
