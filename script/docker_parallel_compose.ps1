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

if (-not $env:FQ_DOCKER_BUILD_CACHE_ROOT) {
    $env:FQ_DOCKER_BUILD_CACHE_ROOT = (Join-Path $repoRoot ".artifacts\docker-build-cache")
}

if (-not $env:DOCKER_BUILDKIT) {
    $env:DOCKER_BUILDKIT = "1"
}

if (-not $env:COMPOSE_BAKE) {
    $env:COMPOSE_BAKE = "true"
}

if (-not (Test-Path $env:FQ_RUNTIME_LOG_HOST_DIR)) {
    New-Item -ItemType Directory -Path $env:FQ_RUNTIME_LOG_HOST_DIR -Force | Out-Null
}

if (-not (Test-Path $env:FQ_COMPOSE_ENV_FILE)) {
    throw "FQ_COMPOSE_ENV_FILE does not exist: $($env:FQ_COMPOSE_ENV_FILE)"
}

if (-not (Test-Path $env:FQ_DOCKER_BUILD_CACHE_ROOT)) {
    New-Item -ItemType Directory -Path $env:FQ_DOCKER_BUILD_CACHE_ROOT -Force | Out-Null
}

$dockerArgs = @(
    "compose",
    "-f",
    "$repoRoot\docker\compose.parallel.yaml"
)

if ($ComposeArgs) {
    $dockerArgs += $ComposeArgs
}

Write-Host "FQ_RUNTIME_LOG_HOST_DIR=$($env:FQ_RUNTIME_LOG_HOST_DIR)"
Write-Host "FQ_COMPOSE_ENV_FILE=$($env:FQ_COMPOSE_ENV_FILE)"
Write-Host "FQ_DOCKER_BUILD_CACHE_ROOT=$($env:FQ_DOCKER_BUILD_CACHE_ROOT)"
Write-Host "DOCKER_BUILDKIT=$($env:DOCKER_BUILDKIT)"
Write-Host "COMPOSE_BAKE=$($env:COMPOSE_BAKE)"
& docker @dockerArgs
exit $LASTEXITCODE
