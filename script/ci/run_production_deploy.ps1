[CmdletBinding()]
param(
    [string]$CanonicalRoot,
    [string]$TargetSha,
    [string]$RunUrl,
    [string]$GitHubRepository,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($CanonicalRoot)) {
    $CanonicalRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

if ($Help) {
    @"
Run production deploy

Parameters:
  -CanonicalRoot    Canonical repository root that will be synced onto local main before deploy.
  -TargetSha        Expected latest origin/main SHA; omitted means deploy current origin/main.
  -RunUrl           Optional workflow run URL recorded into formal deploy state.
  -GitHubRepository Optional GitHub repository slug for artifact metadata.
"@ | Write-Output
    return
}

function Test-Python312Executable {
    param([string]$PythonExe)

    if ([string]::IsNullOrWhiteSpace($PythonExe)) {
        return $false
    }
    if (-not (Test-Path $PythonExe)) {
        return $false
    }

    & $PythonExe -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" *> $null
    return $LASTEXITCODE -eq 0
}

function Get-PyLauncherPython312 {
    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($null -eq $pyCommand) {
        return $null
    }

    try {
        $pythonExe = & $pyCommand.Source -3.12 -c "import sys; print(sys.executable)" 2>$null
    } catch {
        return $null
    }
    if ($LASTEXITCODE -ne 0) {
        return $null
    }

    $resolved = $pythonExe.Trim()
    if (Test-Python312Executable $resolved) {
        return (Resolve-Path $resolved).Path
    }
    return $null
}

function Get-RegisteredPython312Candidates {
    $candidates = New-Object System.Collections.Generic.List[string]
    $installKeys = @(
        "HKCU:\Software\Python\PythonCore\3.12\InstallPath",
        "HKLM:\Software\Python\PythonCore\3.12\InstallPath"
    )

    foreach ($key in $installKeys) {
        if (-not (Test-Path $key)) {
            continue
        }
        $item = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
        if ($null -eq $item) {
            continue
        }
        foreach ($candidate in @($item.ExecutablePath, $item.'(default)')) {
            if ([string]::IsNullOrWhiteSpace($candidate)) {
                continue
            }
            if ($candidate.EndsWith("python.exe", [System.StringComparison]::OrdinalIgnoreCase)) {
                $candidates.Add($candidate)
            } else {
                $candidates.Add((Join-Path $candidate "python.exe"))
            }
        }
    }

    $astralRoot = "HKCU:\Software\Python\Astral"
    if (Test-Path $astralRoot) {
        $astralKeys = Get-ChildItem $astralRoot -ErrorAction SilentlyContinue |
            Where-Object { $_.PSChildName -like "CPython3.12*" } |
            Sort-Object PSChildName -Descending
        foreach ($key in $astralKeys) {
            $installPath = Join-Path $key.PSPath "InstallPath"
            if (-not (Test-Path $installPath)) {
                continue
            }
            $item = Get-ItemProperty -Path $installPath -ErrorAction SilentlyContinue
            if ($null -eq $item) {
                continue
            }
            foreach ($candidate in @($item.ExecutablePath, $item.'(default)')) {
                if ([string]::IsNullOrWhiteSpace($candidate)) {
                    continue
                }
                if ($candidate.EndsWith("python.exe", [System.StringComparison]::OrdinalIgnoreCase)) {
                    $candidates.Add($candidate)
                } else {
                    $candidates.Add((Join-Path $candidate "python.exe"))
                }
            }
        }
    }

    return $candidates
}

function Resolve-Python312Executable {
    $pyLauncherPython = Get-PyLauncherPython312
    if ($pyLauncherPython) {
        return $pyLauncherPython
    }

    foreach ($candidate in Get-RegisteredPython312Candidates) {
        if (Test-Python312Executable $candidate) {
            return (Resolve-Path $candidate).Path
        }
    }

    throw "No usable Python 3.12 interpreter was found on this production runner."
}

function Ensure-UserPythonCoreRegistration {
    param([string]$PythonExe)

    $pythonDir = Split-Path -Parent $PythonExe
    $key = "HKCU:\Software\Python\PythonCore\3.12\InstallPath"
    New-Item -Path $key -Force | Out-Null
    Set-ItemProperty -Path $key -Name "(default)" -Value ($pythonDir + "\")
    Set-ItemProperty -Path $key -Name "ExecutablePath" -Value $PythonExe
    Set-ItemProperty -Path $key -Name "WindowedExecutablePath" -Value (Join-Path $pythonDir "pythonw.exe")
}

function Ensure-UvModule {
    param([string]$PythonExe)

    & $PythonExe -m uv --version *> $null
    if ($LASTEXITCODE -eq 0) {
        return
    }

    & $PythonExe -m pip install uv --break-system-packages
    if ($LASTEXITCODE -ne 0) {
        throw "failed to install uv into production runner Python 3.12"
    }

    & $PythonExe -m uv --version
    if ($LASTEXITCODE -ne 0) {
        throw "uv is still unavailable after installation"
    }
}

function Invoke-Git {
    param(
        [string]$RepoRoot,
        [string[]]$Arguments
    )

    & git -C $RepoRoot @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git command failed: git -C $RepoRoot $($Arguments -join ' ')"
    }
}

function Get-GitOutput {
    param(
        [string]$RepoRoot,
        [string[]]$Arguments
    )

    $output = & git -C $RepoRoot @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "git command failed: git -C $RepoRoot $($Arguments -join ' ')"
    }
    return ($output | Out-String).Trim()
}

function Ensure-SafeDirectory {
    param([string]$RepoRoot)

    & git config --global --add safe.directory $RepoRoot
    if ($LASTEXITCODE -ne 0) {
        throw "failed to trust git safe.directory: $RepoRoot"
    }
}

function Invoke-Python {
    param(
        [string]$PythonExe,
        [string]$WorkingDirectory,
        [string[]]$Arguments
    )

    Push-Location $WorkingDirectory
    try {
        & $PythonExe @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "python command failed: $PythonExe $($Arguments -join ' ')"
        }
    } finally {
        Pop-Location
    }
}

function Invoke-HostRuntimeControl {
    param(
        [string]$HostRuntimeScript,
        [string]$Mode,
        [string[]]$DeploymentSurface,
        [double]$TimeoutSeconds = 45
    )

    $resolvedSurfaces = @($DeploymentSurface | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if (-not (Test-Path $HostRuntimeScript)) {
        throw "host runtime control script not found: $HostRuntimeScript"
    }
    if ($resolvedSurfaces.Count -eq 0) {
        throw "host runtime control requires at least one deployment surface"
    }

    $arguments = @(
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $HostRuntimeScript,
        "-Mode",
        $Mode,
        "-DeploymentSurface",
        ($resolvedSurfaces -join ","),
        "-TimeoutSeconds",
        ([string]$TimeoutSeconds)
    )

    & powershell @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "host runtime control failed: $Mode"
    }
}

function Test-RepoVirtualenvHealthy {
    param([string]$RepoRoot)

    $venvRoot = Join-Path $RepoRoot ".venv"
    $venvPython = Join-Path $venvRoot "Scripts\python.exe"
    $pyvenvConfig = Join-Path $venvRoot "pyvenv.cfg"

    if (-not (Test-Path $venvPython)) {
        return $false
    }
    if (-not (Test-Path $pyvenvConfig)) {
        return $false
    }

    try {
        & $venvPython -c "import sys; raise SystemExit(0 if sys.executable else 1)" *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Repair-RepoVirtualenv {
    param(
        [string]$PythonExe,
        [string]$RepoRoot
    )

    Write-Warning "canonical repo virtualenv metadata is missing or unhealthy; recreating .venv with runner Python 3.12."
    Invoke-Python -PythonExe $PythonExe -WorkingDirectory $RepoRoot -Arguments @(
        "-m", "uv", "venv", ".venv", "--python", $PythonExe, "--clear"
    )
}

function Invoke-UvSyncWithHostRuntimeQuiesce {
    param(
        [string]$PythonExe,
        [string]$RepoRoot,
        [string]$HostRuntimeScript,
        [string[]]$HostRuntimeSurfaces
    )

    $needsQuiesce = $false
    try {
        Invoke-Python -PythonExe $PythonExe -WorkingDirectory $RepoRoot -Arguments @(
            "-m", "uv", "sync", "--frozen"
        )
    } catch {
        $needsQuiesce = $true
        Write-Warning "uv sync failed on the live canonical repo root; retrying uv sync after quiescing host runtime surfaces."
    }
    $venvHealthy = Test-RepoVirtualenvHealthy -RepoRoot $RepoRoot
    if (-not $needsQuiesce -and $venvHealthy) {
        return
    }
    if (-not $venvHealthy) {
        Write-Warning "canonical repo .venv is missing pyvenv.cfg or has an unusable python.exe; repairing after quiescing host runtime surfaces."
    }

    Invoke-HostRuntimeControl -HostRuntimeScript $HostRuntimeScript -Mode "StopSurfaces" -DeploymentSurface $HostRuntimeSurfaces
    try {
        if (-not $venvHealthy) {
            Repair-RepoVirtualenv -PythonExe $PythonExe -RepoRoot $RepoRoot
        }
        Invoke-Python -PythonExe $PythonExe -WorkingDirectory $RepoRoot -Arguments @(
            "-m", "uv", "sync", "--frozen"
        )
        if (-not (Test-RepoVirtualenvHealthy -RepoRoot $RepoRoot)) {
            Repair-RepoVirtualenv -PythonExe $PythonExe -RepoRoot $RepoRoot
            Invoke-Python -PythonExe $PythonExe -WorkingDirectory $RepoRoot -Arguments @(
                "-m", "uv", "sync", "--frozen"
            )
        }
    } finally {
        Invoke-HostRuntimeControl -HostRuntimeScript $HostRuntimeScript -Mode "RestartSurfaces" -DeploymentSurface $HostRuntimeSurfaces
    }

    if (-not (Test-RepoVirtualenvHealthy -RepoRoot $RepoRoot)) {
        throw "canonical repo virtualenv is still unhealthy after repair: $(Join-Path $RepoRoot '.venv')"
    }
}

function Ensure-CanonicalRepoSynced {
    param(
        [string]$CanonicalRoot,
        [string]$TargetSha
    )

    if (-not (Test-Path (Join-Path $CanonicalRoot ".git"))) {
        throw "canonical repo root is not a git repository: $CanonicalRoot"
    }

    & git -C $CanonicalRoot show-ref --verify refs/heads/main *> $null
    $localMainExists = $LASTEXITCODE -eq 0

    if ($localMainExists) {
        Invoke-Git -RepoRoot $CanonicalRoot -Arguments @("checkout", "-f", "main")
    } else {
        Invoke-Git -RepoRoot $CanonicalRoot -Arguments @("checkout", "-B", "main", "refs/remotes/origin/main")
    }

    Invoke-Git -RepoRoot $CanonicalRoot -Arguments @("reset", "--hard", $TargetSha)
    Invoke-Git -RepoRoot $CanonicalRoot -Arguments @("clean", "-ffd")

    $currentBranch = Get-GitOutput -RepoRoot $CanonicalRoot -Arguments @("branch", "--show-current")
    if ($currentBranch -ne "main") {
        throw "canonical repo root is not on local main after sync: branch=$currentBranch"
    }

    $headSha = Get-GitOutput -RepoRoot $CanonicalRoot -Arguments @("rev-parse", "HEAD")
    if ($headSha -ne $TargetSha) {
        throw "canonical repo root head does not match target sha after sync: head=$headSha target=$TargetSha"
    }
}

$CanonicalRoot = [System.IO.Path]::GetFullPath((Resolve-Path $CanonicalRoot).Path)
if (-not (Test-Path $CanonicalRoot)) {
    throw "canonical repo root does not exist: $CanonicalRoot"
}

$pythonExe = Resolve-Python312Executable
Ensure-UserPythonCoreRegistration -PythonExe $pythonExe
Ensure-UvModule -PythonExe $pythonExe

Ensure-SafeDirectory -RepoRoot $CanonicalRoot
Invoke-Git -RepoRoot $CanonicalRoot -Arguments @("fetch", "origin", "main")
$remoteMainSha = Get-GitOutput -RepoRoot $CanonicalRoot -Arguments @("rev-parse", "origin/main")

if ([string]::IsNullOrWhiteSpace($TargetSha)) {
    $TargetSha = $remoteMainSha
} elseif ($TargetSha -ne $remoteMainSha) {
    throw "stale push deploy trigger: target_sha=$TargetSha current_main=$remoteMainSha"
}

Ensure-CanonicalRepoSynced -CanonicalRoot $CanonicalRoot -TargetSha $TargetSha

$hostRuntimeScript = Join-Path $CanonicalRoot 'script/fqnext_host_runtime_ctl.ps1'
$hostRuntimeSurfaces = @(
    "market_data",
    "guardian",
    "position_management",
    "tpsl",
    "order_management"
)

Invoke-UvSyncWithHostRuntimeQuiesce -PythonExe $pythonExe -RepoRoot $CanonicalRoot -HostRuntimeScript $hostRuntimeScript -HostRuntimeSurfaces $hostRuntimeSurfaces

$venvPython = Join-Path $CanonicalRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "canonical repo virtualenv python not found: $venvPython"
}
if (-not (Test-RepoVirtualenvHealthy -RepoRoot $CanonicalRoot)) {
    throw "canonical repo virtualenv is missing pyvenv.cfg or python bootstrap metadata: $(Join-Path $CanonicalRoot '.venv')"
}

$formalDeployArgs = @(
    "script/ci/run_formal_deploy.py",
    "--repo-root", ".",
    "--head-sha", $TargetSha,
    "--format", "summary"
)
if (-not [string]::IsNullOrWhiteSpace($RunUrl)) {
    $formalDeployArgs += @("--run-url", $RunUrl)
}
if (-not [string]::IsNullOrWhiteSpace($GitHubRepository)) {
    $formalDeployArgs += @("--github-repository", $GitHubRepository)
}

Invoke-Python -PythonExe $venvPython -WorkingDirectory $CanonicalRoot -Arguments $formalDeployArgs
