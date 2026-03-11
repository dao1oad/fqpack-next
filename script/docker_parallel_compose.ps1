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
    throw "FQ_RUNTIME_LOG_HOST_DIR does not exist: $($env:FQ_RUNTIME_LOG_HOST_DIR)"
}

if (-not (Test-Path $env:FQ_COMPOSE_ENV_FILE)) {
    throw "FQ_COMPOSE_ENV_FILE does not exist: $($env:FQ_COMPOSE_ENV_FILE)"
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
& docker @dockerArgs
exit $LASTEXITCODE
