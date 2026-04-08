param(
    [Alias("d")]
    [switch]$Detached,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ComposeArgs
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:DOCKER_BUILDKIT = "1"
$env:COMPOSE_DOCKER_CLI_BUILD = "1"
$env:COMPOSE_BAKE = "true"
Set-Item -Path "Env:DOCKER_BUILDKIT" -Value "1"
Set-Item -Path "Env:COMPOSE_DOCKER_CLI_BUILD" -Value "1"
Set-Item -Path "Env:COMPOSE_BAKE" -Value "true"

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
        (Join-Path $repoRoot '.worktrees\main-deploy-production\.venv\Scripts\python.exe'),
        (Join-Path $repoRoot '.venv\Scripts\python.exe'),
        (Join-Path $repoRoot '.venv/bin/python'),
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

    foreach ($commandName in @('python', 'python3')) {
        $commandInfo = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($commandInfo) {
            $candidates += [pscustomobject]@{
                Executable = $commandInfo.Source
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

    throw "Unable to resolve a usable Python 3.12 launcher for docker compose helpers."
}

function Invoke-Python312 {
    param([string[]]$Arguments)

    $resolved = Resolve-Python312Command
    & $resolved.Executable @($resolved.PrefixArgs + $Arguments)
}

if (-not $env:FQ_RUNTIME_LOG_HOST_DIR) {
    $resolvedRuntimeLogHostDir = Invoke-Python312 @(
        "$repoRoot\script\docker_parallel_runtime.py",
        '--repo-root',
        $repoRoot,
        '--kind',
        'runtime-log-dir'
    )
    if ($LASTEXITCODE -ne 0) {
        throw "failed to resolve FQ_RUNTIME_LOG_HOST_DIR"
    }
    $env:FQ_RUNTIME_LOG_HOST_DIR = $resolvedRuntimeLogHostDir.Trim()
}

if (-not $env:FQ_COMPOSE_ENV_FILE) {
    $resolvedComposeEnvFile = Invoke-Python312 @(
        "$repoRoot\script\docker_parallel_runtime.py",
        '--repo-root',
        $repoRoot,
        '--kind',
        'compose-env-file'
    )
    if ($LASTEXITCODE -ne 0) {
        throw "failed to resolve FQ_COMPOSE_ENV_FILE"
    }
    $env:FQ_COMPOSE_ENV_FILE = $resolvedComposeEnvFile.Trim()
}

if (-not $env:FQ_DOCKER_BUILD_CACHE_ROOT) {
    Set-Item -Path "Env:FQ_DOCKER_BUILD_CACHE_ROOT" -Value (Join-Path $repoRoot ".artifacts\docker-build-cache")
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

$currentRevision = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "failed to resolve current git revision"
}
$env:FQ_IMAGE_GIT_SHA = $currentRevision

$resolvedComposeArgs = @($ComposeArgs)
if ($Detached.IsPresent -and $resolvedComposeArgs -and $resolvedComposeArgs -notcontains "-d") {
    $reconstructedComposeArgs = @($resolvedComposeArgs[0], "-d")
    if ($resolvedComposeArgs.Count -gt 1) {
        $reconstructedComposeArgs += $resolvedComposeArgs[1..($resolvedComposeArgs.Count - 1)]
    }
    $resolvedComposeArgs = $reconstructedComposeArgs
}

$fallbackComposeArgs = @($resolvedComposeArgs)
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

        $smartBuildJson = Invoke-Python312 -Arguments $helperArgs
        if ($LASTEXITCODE -eq 0 -and $smartBuildJson) {
            $smartBuild = $smartBuildJson | ConvertFrom-Json
            $resolvedComposeArgs = @($smartBuild.compose_args | ForEach-Object { [string]$_ })
            if ($smartBuild.image_overrides) {
                foreach ($property in $smartBuild.image_overrides.PSObject.Properties) {
                    Set-Item -Path "Env:$($property.Name)" -Value ([string]$property.Value)
                }
            }
            if ($smartBuild.skip_build) {
                Write-Host "smart-build[$($smartBuild.mode)]: $($smartBuild.reason)"
            }
            if ($smartBuild.mode -eq "remote_cached" -and $smartBuild.pull_images) {
                $pullFailed = $false
                foreach ($pullImage in @($smartBuild.pull_images | ForEach-Object { [string]$_ })) {
                    Write-Host "PULL_IMAGE=$pullImage"
                    & docker pull $pullImage
                    if ($LASTEXITCODE -ne 0) {
                        Write-Warning "remote image pull failed for $pullImage; falling back to original compose args"
                        $resolvedComposeArgs = @($fallbackComposeArgs)
                        $pullFailed = $true
                        break
                    }
                }
                if ($pullFailed) {
                    Write-Host "smart-build fallback: build_required"
                }
            }
        }
    } catch {
        Write-Warning "smart-build fallback to original compose args: $($_.Exception.Message)"
        $resolvedComposeArgs = @($fallbackComposeArgs)
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
Write-Host "FQ_DOCKER_BUILD_CACHE_ROOT=$($env:FQ_DOCKER_BUILD_CACHE_ROOT)"
Write-Host "FQ_IMAGE_GIT_SHA=$($env:FQ_IMAGE_GIT_SHA)"
Write-Host "FQ_ENABLE_REMOTE_CACHE_PULL=$($env:FQ_ENABLE_REMOTE_CACHE_PULL)"
Write-Host "DOCKER_BUILDKIT=$($env:DOCKER_BUILDKIT)"
Write-Host "COMPOSE_BAKE=$($env:COMPOSE_BAKE)"
Write-Host "DOCKER_ARGS=$($dockerArgs -join ' ')"
& docker @dockerArgs
exit $LASTEXITCODE
