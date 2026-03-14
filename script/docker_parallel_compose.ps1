param(
    [string]$PrimaryWorktree,
    [string]$ComposeEnvFile,
    [string]$RuntimeLogDir,
    [string]$EmitMetadataPath,
    [switch]$NoProxyLocalhost,
    [int]$BuildTimeoutSec = 0,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ComposeArgs
)

$ErrorActionPreference = "Stop"

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

function Update-NoProxyLocalhost {
    $existing = @()
    foreach ($value in @($env:NO_PROXY, $env:no_proxy)) {
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            $existing += @($value -split ',')
        }
    }

    $tokens = [System.Collections.Generic.List[string]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($token in @($existing + @("127.0.0.1", "localhost"))) {
        $trimmed = $token.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed)) {
            continue
        }
        if ($seen.Add($trimmed)) {
            $tokens.Add($trimmed)
        }
    }

    $joined = $tokens -join ","
    $env:NO_PROXY = $joined
    $env:no_proxy = $joined
}

function Write-Metadata {
    param(
        [Parameter(Mandatory = $true)]$Metadata,
        [string]$Path
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }

    $json = $Metadata | ConvertTo-Json -Depth 12
    Write-Utf8NoBomFile -Path $Path -Content $json
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$composeFile = Join-Path $repoRoot "docker\compose.parallel.yaml"
$runtimePolicyArgs = @(
    "$repoRoot\script\docker_parallel_runtime.py",
    "--repo-root",
    $repoRoot,
    "--kind",
    "runtime-policy"
)

if (-not [string]::IsNullOrWhiteSpace($PrimaryWorktree)) {
    $runtimePolicyArgs += @("--primary-worktree", $PrimaryWorktree)
}
if (-not [string]::IsNullOrWhiteSpace($ComposeEnvFile)) {
    $runtimePolicyArgs += @("--compose-env-file", $ComposeEnvFile)
}
if (-not [string]::IsNullOrWhiteSpace($RuntimeLogDir)) {
    $runtimePolicyArgs += @("--runtime-log-dir", $RuntimeLogDir)
}
if ($PrimaryWorktree -or $ComposeEnvFile -or $RuntimeLogDir) {
    $runtimePolicyArgs += "--allow-dirty-primary"
}
if ($repoRoot -ne $PrimaryWorktree) {
    $runtimePolicyArgs += "--prefer-clean-worktree"
}

$runtimePolicyJson = & py -3.12 @runtimePolicyArgs
if ($LASTEXITCODE -ne 0) {
    throw "failed to resolve docker runtime policy"
}

$runtimePolicy = $runtimePolicyJson | ConvertFrom-Json
$env:FQ_RUNTIME_LOG_HOST_DIR = [string]$runtimePolicy.runtime_log_dir
$env:FQ_COMPOSE_ENV_FILE = [string]$runtimePolicy.compose_env_file

if ($NoProxyLocalhost) {
    Update-NoProxyLocalhost
}

if (-not (Test-Path $env:FQ_RUNTIME_LOG_HOST_DIR)) {
    New-Item -ItemType Directory -Path $env:FQ_RUNTIME_LOG_HOST_DIR -Force | Out-Null
}

if (-not (Test-Path $env:FQ_COMPOSE_ENV_FILE)) {
    throw "FQ_COMPOSE_ENV_FILE does not exist: $($env:FQ_COMPOSE_ENV_FILE)"
}

$dockerArgs = @(
    "compose",
    "-f",
    $composeFile
)
if ($ComposeArgs) {
    $dockerArgs += $ComposeArgs
}

$metadata = [ordered]@{
    compose_file = $composeFile
    compose_args = @($ComposeArgs)
    docker_command = @("docker") + $dockerArgs
    primary_worktree = [string]$runtimePolicy.primary_worktree
    build_worktree = [string]$runtimePolicy.build_worktree
    compose_env_file = $env:FQ_COMPOSE_ENV_FILE
    runtime_log_dir = $env:FQ_RUNTIME_LOG_HOST_DIR
    no_proxy_localhost = [bool]$NoProxyLocalhost
    build_timeout_sec = $BuildTimeoutSec
    started_at = ConvertTo-IsoTimestamp -Value (Get-Date)
    finished_at = $null
    docker_exit_code = $null
    timed_out = $false
    review_required = $false
    review_reason = $null
    stdout = $null
    stderr = $null
}

$stdoutPath = [System.IO.Path]::GetTempFileName()
$stderrPath = [System.IO.Path]::GetTempFileName()
try {
    $process = Start-Process `
        -FilePath "docker" `
        -ArgumentList $dockerArgs `
        -WorkingDirectory $repoRoot `
        -PassThru `
        -Wait:($BuildTimeoutSec -le 0) `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath

    if ($BuildTimeoutSec -gt 0) {
        $completed = $process.WaitForExit($BuildTimeoutSec * 1000)
        if (-not $completed) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            $metadata.timed_out = $true
            $metadata.review_required = $true
            $metadata.review_reason = "docker compose timed out; inspect metadata before deciding failure"
            $metadata.docker_exit_code = 124
        }
        else {
            $metadata.docker_exit_code = $process.ExitCode
        }
    }
    else {
        $metadata.docker_exit_code = $process.ExitCode
    }
}
finally {
    if (Test-Path -LiteralPath $stdoutPath) {
        $metadata.stdout = [System.IO.File]::ReadAllText($stdoutPath, [System.Text.Encoding]::UTF8)
        Remove-Item -LiteralPath $stdoutPath -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $stderrPath) {
        $metadata.stderr = [System.IO.File]::ReadAllText($stderrPath, [System.Text.Encoding]::UTF8)
        Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
    }
    $metadata.finished_at = ConvertTo-IsoTimestamp -Value (Get-Date)
    Write-Metadata -Metadata $metadata -Path $EmitMetadataPath
}

Write-Host "FQ_RUNTIME_LOG_HOST_DIR=$($env:FQ_RUNTIME_LOG_HOST_DIR)"
Write-Host "FQ_COMPOSE_ENV_FILE=$($env:FQ_COMPOSE_ENV_FILE)"

if ($metadata.timed_out) {
    exit 124
}

exit ([int]$metadata.docker_exit_code)
