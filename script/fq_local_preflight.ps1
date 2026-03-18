[CmdletBinding()]
param(
    [ValidateSet("Check", "Run", "Ensure")]
    [string]$Mode = "Ensure",
    [string]$BaseRef,
    [switch]$SkipFetch
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

function Resolve-UvPath {
    $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uvCommand) {
        throw "uv not found in PATH."
    }
    return $uvCommand.Source
}

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Args
    )

    $result = & git -C $RepoRoot @Args
    $exitCode = $LASTEXITCODE
    return @{
        Output = $result
        ExitCode = $exitCode
    }
}

function Resolve-BaseRef {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    if (-not [string]::IsNullOrWhiteSpace($BaseRef)) {
        return $BaseRef.Trim()
    }

    $remotePushDefault = (& git -C $RepoRoot config --get remote.pushDefault 2>$null)
    $candidates = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($remotePushDefault)) {
        $candidates.Add("$($remotePushDefault.Trim())/main")
    }
    $candidates.Add("github/main")
    $candidates.Add("origin/main")

    $seen = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::OrdinalIgnoreCase)
    foreach ($candidate in $candidates) {
        if (-not $seen.Add($candidate)) {
            continue
        }
        & git -C $RepoRoot show-ref --verify --quiet "refs/remotes/$candidate"
        if ($LASTEXITCODE -eq 0) {
            return $candidate
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($remotePushDefault)) {
        return "$($remotePushDefault.Trim())/main"
    }
    return "origin/main"
}

function Fetch-BaseRef {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$ResolvedBaseRef
    )

    $parts = $ResolvedBaseRef.Split("/", 2)
    if ($parts.Length -ne 2) {
        throw "Base ref must look like <remote>/<branch>: $ResolvedBaseRef"
    }

    & git -C $RepoRoot fetch $parts[0] $parts[1] --no-tags --prune
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to fetch base ref: $ResolvedBaseRef"
    }
}

function Get-GitSha {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$RefName
    )

    $sha = (& git -C $RepoRoot rev-parse $RefName 2>$null)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($sha)) {
        throw "Unable to resolve git ref: $RefName"
    }

    return $sha.Trim()
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

function Test-ValidPreflightRecord {
    param(
        [Parameter(Mandatory = $true)][string]$RecordPath,
        [Parameter(Mandatory = $true)][string]$HeadSha,
        [Parameter(Mandatory = $true)][string]$BaseSha
    )

    if (-not (Test-Path $RecordPath)) {
        return $false
    }

    $payload = Get-Content -Raw $RecordPath | ConvertFrom-Json
    if ($payload.head_sha -ne $HeadSha -or $payload.base_sha -ne $BaseSha) {
        return $false
    }

    return (
        $payload.governance.status -eq "passed" -and
        $payload.pre_commit.status -eq "passed" -and
        $payload.pytest.status -eq "passed" -and
        @("passed", "skipped") -contains [string]$payload.review_threads.status
    )
}

function Invoke-ReviewThreadsCheck {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][hashtable]$PythonLauncher
    )

    $checkReviewThreadsScript = Join-Path $RepoRoot "script\ci\check_pr_review_threads.py"
    $reviewThreadsRaw = & $PythonLauncher.Path @(
        $PythonLauncher.Prefix + @(
            $checkReviewThreadsScript,
            "--repo-root",
            $RepoRoot
        )
    )
    $reviewThreadsExitCode = $LASTEXITCODE
    return @{
        ExitCode = $reviewThreadsExitCode
        Payload = (($reviewThreadsRaw -join "`n") | ConvertFrom-Json)
    }
}

function Invoke-ExternalCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $FilePath @Arguments
    return $LASTEXITCODE
}

$repoRoot = (& git rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repoRoot)) {
    throw "fq_local_preflight.ps1 must run inside a git repository."
}
$repoRoot = $repoRoot.Trim()
$absoluteGitDir = (& git -C $repoRoot rev-parse --absolute-git-dir 2>$null)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($absoluteGitDir)) {
    throw "Unable to resolve absolute git dir."
}
$recordRoot = Join-Path $absoluteGitDir.Trim() "fq-preflight"
$resolvedBaseRef = Resolve-BaseRef -RepoRoot $repoRoot

if ($Mode -ne "Check" -and -not $SkipFetch) {
    Fetch-BaseRef -RepoRoot $repoRoot -ResolvedBaseRef $resolvedBaseRef
}

$headSha = Get-GitSha -RepoRoot $repoRoot -RefName "HEAD"
$baseSha = Get-GitSha -RepoRoot $repoRoot -RefName $resolvedBaseRef
$recordPath = Join-Path $recordRoot "$headSha.json"
$pythonLauncher = Resolve-PythonLauncher -RepoRoot $repoRoot

if ($Mode -eq "Check") {
    if (Test-ValidPreflightRecord -RecordPath $recordPath -HeadSha $headSha -BaseSha $baseSha) {
        $reviewThreadsResult = Invoke-ReviewThreadsCheck -RepoRoot $repoRoot -PythonLauncher $pythonLauncher
        if ($reviewThreadsResult.ExitCode -ne 0) {
            exit 1
        }
        if ([string]$reviewThreadsResult.Payload.status -eq "failed") {
            exit 1
        }
        exit 0
    }
    exit 1
}

if ($Mode -eq "Ensure" -and (Test-ValidPreflightRecord -RecordPath $recordPath -HeadSha $headSha -BaseSha $baseSha)) {
    $reviewThreadsResult = Invoke-ReviewThreadsCheck -RepoRoot $repoRoot -PythonLauncher $pythonLauncher
    if ($reviewThreadsResult.ExitCode -ne 0) {
        exit $reviewThreadsResult.ExitCode
    }
    if ([string]$reviewThreadsResult.Payload.status -eq "failed") {
        exit 2
    }
    $reviewThreadPayload = $reviewThreadsResult.Payload
    $cachedPayload = Get-Content -Raw $recordPath | ConvertFrom-Json
    $cachedPayload.review_threads = [ordered]@{
        status = [string]$reviewThreadPayload.status
        unresolved_count = if ($null -ne $reviewThreadPayload.unresolved_threads) { [int]$reviewThreadPayload.unresolved_threads } else { 0 }
        pr_number = if ($null -ne $reviewThreadPayload.pr_number -and -not [string]::IsNullOrWhiteSpace([string]$reviewThreadPayload.pr_number)) { [int]$reviewThreadPayload.pr_number } else { $null }
    }
    Write-Utf8NoBomFile -Path $recordPath -Content ($cachedPayload | ConvertTo-Json -Depth 4)
    Write-Host "[freshquant] local preflight cache hit for $headSha against $resolvedBaseRef"
    exit 0
}

$uvPath = Resolve-UvPath
$checkCurrentDocsScript = Join-Path $repoRoot "script\ci\check_current_docs.py"
$governanceExitCode = Invoke-ExternalCommand -FilePath $pythonLauncher.Path -Arguments @(
    $pythonLauncher.Prefix + @(
        $checkCurrentDocsScript,
        "--base-ref",
        $resolvedBaseRef,
        "--head-ref",
        "HEAD"
    )
)
if ($governanceExitCode -ne 0) {
    exit $governanceExitCode
}

$preCommitExitCode = Invoke-ExternalCommand -FilePath $uvPath -Arguments @(
    "tool",
    "run",
    "pre-commit",
    "run",
    "--show-diff-on-failure",
    "--color=always",
    "--from-ref",
    $resolvedBaseRef,
    "--to-ref",
    "HEAD"
)
if ($preCommitExitCode -ne 0) {
    exit $preCommitExitCode
}

$pytestExitCode = Invoke-ExternalCommand -FilePath $uvPath -Arguments @(
    "run",
    "pytest",
    "-q",
    "freshquant/tests",
    "-n",
    "auto",
    "--dist",
    "loadfile"
)
if ($pytestExitCode -ne 0) {
    exit $pytestExitCode
}

$reviewThreadsResult = Invoke-ReviewThreadsCheck -RepoRoot $repoRoot -PythonLauncher $pythonLauncher
if ($reviewThreadsResult.ExitCode -ne 0) {
    exit $reviewThreadsResult.ExitCode
}
$reviewThreads = $reviewThreadsResult.Payload
$reviewThreadStatus = [string]$reviewThreads.status
$reviewThreadUnresolvedCount = 0
if ($null -ne $reviewThreads.unresolved_threads) {
    $reviewThreadUnresolvedCount = [int]$reviewThreads.unresolved_threads
}
$reviewThreadPrNumber = $null
if ($null -ne $reviewThreads.pr_number -and -not [string]::IsNullOrWhiteSpace([string]$reviewThreads.pr_number)) {
    $reviewThreadPrNumber = [int]$reviewThreads.pr_number
}

$payload = [ordered]@{
    head_sha = $headSha
    base_ref = $resolvedBaseRef
    base_sha = $baseSha
    executed_at = (Get-Date).ToString("o")
    governance = [ordered]@{ status = "passed" }
    pre_commit = [ordered]@{ status = "passed" }
    pytest = [ordered]@{ status = "passed" }
    review_threads = [ordered]@{
        status = $reviewThreadStatus
        unresolved_count = $reviewThreadUnresolvedCount
        pr_number = $reviewThreadPrNumber
    }
}

Write-Utf8NoBomFile -Path $recordPath -Content ($payload | ConvertTo-Json -Depth 4)
Write-Host "[freshquant] local preflight passed for $headSha against $resolvedBaseRef"
