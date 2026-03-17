param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ComposeArgs
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $env:FQ_RUNTIME_LOG_HOST_DIR) {
    $resolvedRuntimeLogHostDir = & py -3.12 "$repoRoot\script\docker_parallel_runtime.py" --repo-root $repoRoot --kind runtime-log-dir
    if ($LASTEXITCODE -ne 0) {
        throw "failed to resolve FQ_RUNTIME_LOG_HOST_DIR"
    }
    $env:FQ_RUNTIME_LOG_HOST_DIR = $resolvedRuntimeLogHostDir.Trim()
}

if (-not $env:FQ_COMPOSE_ENV_FILE) {
    $resolvedComposeEnvFile = & py -3.12 "$repoRoot\script\docker_parallel_runtime.py" --repo-root $repoRoot --kind compose-env-file
    if ($LASTEXITCODE -ne 0) {
        throw "failed to resolve FQ_COMPOSE_ENV_FILE"
    }
    $env:FQ_COMPOSE_ENV_FILE = $resolvedComposeEnvFile.Trim()
}

if (-not (Test-Path $env:FQ_RUNTIME_LOG_HOST_DIR)) {
    New-Item -ItemType Directory -Path $env:FQ_RUNTIME_LOG_HOST_DIR -Force | Out-Null
}

if (-not (Test-Path $env:FQ_COMPOSE_ENV_FILE)) {
    throw "FQ_COMPOSE_ENV_FILE does not exist: $($env:FQ_COMPOSE_ENV_FILE)"
}

$currentRevision = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "failed to resolve current git revision"
}
$env:FQ_IMAGE_GIT_SHA = $currentRevision

$resolvedComposeArgs = @($ComposeArgs)
if ($resolvedComposeArgs.Count -gt 0) {
    try {
        $helperArgs = @(
            "$repoRoot\script\docker_parallel_compose.py",
            "--repo-root",
            $repoRoot,
            "--compose-file",
            "$repoRoot\docker\compose.parallel.yaml"
        )
        foreach ($composeArg in $resolvedComposeArgs) {
            $helperArgs += "--compose-arg=$([string]$composeArg)"
        }
        $smartBuildJson = & py -3.12 @helperArgs
        if ($LASTEXITCODE -eq 0 -and $smartBuildJson) {
            $smartBuild = $smartBuildJson | ConvertFrom-Json
            $resolvedComposeArgs = @($smartBuild.compose_args | ForEach-Object { [string]$_ })
            if ($smartBuild.skip_build) {
                Write-Host "smart-build: $($smartBuild.reason)"
            }
        }
    } catch {
        Write-Warning "smart-build fallback to original compose args: $($_.Exception.Message)"
        $resolvedComposeArgs = @($ComposeArgs)
    }
}

$dockerArgs = @(
    "compose",
    "-f",
    "$repoRoot\docker\compose.parallel.yaml"
)

if ($resolvedComposeArgs) {
    $dockerArgs += $resolvedComposeArgs
}

Write-Host "FQ_RUNTIME_LOG_HOST_DIR=$($env:FQ_RUNTIME_LOG_HOST_DIR)"
Write-Host "FQ_COMPOSE_ENV_FILE=$($env:FQ_COMPOSE_ENV_FILE)"
Write-Host "FQ_IMAGE_GIT_SHA=$($env:FQ_IMAGE_GIT_SHA)"
Write-Host "DOCKER_ARGS=$($dockerArgs -join ' ')"
& docker @dockerArgs
exit $LASTEXITCODE
