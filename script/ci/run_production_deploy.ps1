[CmdletBinding()]
param(
    [string]$CanonicalRoot,
    [string]$MirrorRoot = "D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production",
    [string]$MirrorBranch = "deploy-production-main",
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
  -CanonicalRoot    Canonical repository root that tracks origin/main.
  -MirrorRoot       Production deploy mirror worktree path.
  -MirrorBranch     Local branch name used inside the deploy mirror.
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

    $pythonExe = & $pyCommand.Source -3.12 -c "import sys; print(sys.executable)" 2>$null
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

$CanonicalRoot = (Resolve-Path $CanonicalRoot).Path
$MirrorRoot = [System.IO.Path]::GetFullPath($MirrorRoot)

if (-not (Test-Path $CanonicalRoot)) {
    throw "canonical repo root does not exist: $CanonicalRoot"
}

$pythonExe = Resolve-Python312Executable
Ensure-UserPythonCoreRegistration -PythonExe $pythonExe
Ensure-UvModule -PythonExe $pythonExe

Ensure-SafeDirectory -RepoRoot $CanonicalRoot
Invoke-Git -RepoRoot $CanonicalRoot -Arguments @("fetch", "origin", "main")
$remoteMainSha = Get-GitOutput -RepoRoot $CanonicalRoot -Arguments @("rev-parse", "origin/main")
$remoteUrl = Get-GitOutput -RepoRoot $CanonicalRoot -Arguments @("remote", "get-url", "origin")

if ([string]::IsNullOrWhiteSpace($TargetSha)) {
    $TargetSha = $remoteMainSha
} elseif ($TargetSha -ne $remoteMainSha) {
    throw "stale push deploy trigger: target_sha=$TargetSha current_main=$remoteMainSha"
}

if (-not (Test-Path $MirrorRoot)) {
    Invoke-Git -RepoRoot $CanonicalRoot -Arguments @("worktree", "prune")
    Invoke-Git -RepoRoot $CanonicalRoot -Arguments @("worktree", "add", $MirrorRoot, "-B", $MirrorBranch, "refs/remotes/origin/main")
}

if (-not (Test-Path (Join-Path $MirrorRoot ".git"))) {
    throw "deploy mirror is not a git repository: $MirrorRoot"
}

Ensure-SafeDirectory -RepoRoot $MirrorRoot

Invoke-Python -PythonExe $pythonExe -WorkingDirectory $MirrorRoot -Arguments @(
    "script/ci/sync_local_deploy_mirror.py",
    "--repo-root", $MirrorRoot,
    "--target-sha", $TargetSha,
    "--remote-url", $remoteUrl,
    "--branch", "main",
    "--checkout-branch", $MirrorBranch,
    "--format", "summary"
)

Invoke-Python -PythonExe $pythonExe -WorkingDirectory $MirrorRoot -Arguments @(
    "-m", "uv", "sync", "--frozen"
)

$venvPython = Join-Path $MirrorRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "deploy mirror virtualenv python not found: $venvPython"
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

Invoke-Python -PythonExe $venvPython -WorkingDirectory $MirrorRoot -Arguments $formalDeployArgs
