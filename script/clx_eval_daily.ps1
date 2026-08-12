param(
    [string]$TradeDate = (Get-Date -Format "yyyy-MM-dd"),
    [string]$RunDir = "",
    [int]$DeepWorkers = 3,
    [int]$DeepMaxAttempts = 2,
    [string]$AgentCommand = "",
    [switch]$SkipBootstrap,
    [switch]$SkipDeepRun,
    [switch]$DeepDryRun,
    [switch]$AllowIncompleteDeep,
    [switch]$SkipPublish
)

$ErrorActionPreference = "Stop"

# Repository-owned entrypoints only. No global skill paths are used by this
# script: the official batch is fetched by the repo runner (bootstrap), and
# deep analysis (up to --deep-limit) is executed by the repo deep executor via
# the repo agent adapter. All artifacts stay in the run dir / external data dir.
$repo = "D:/fqpack/freshquant-2026.2.23"
$py = Join-Path $repo ".venv/Scripts/python.exe"
$module = "freshquant.clx_daily_selection.fundamental.runner"

# Evaluation data dir: out of git, served by fq_webui compose bind mount.
$evalDataDir = "D:/fqpack/runtime/artifacts/clx-evaluator"

# Run dir lives outside the repo (kept away from concurrent main sync).
$workRoot = "C:/Users/Administrator/fq-clx-work"
if (-not $RunDir) {
    $RunDir = Join-Path $workRoot "clx-$TradeDate"
}

Write-Host "=============================================="
Write-Host "CLX fundamental evaluation daily run  trade_date=$TradeDate"
Write-Host "  run_dir      = $RunDir"
Write-Host "  publish_dir  = $evalDataDir"
Write-Host "  deep workers = $DeepWorkers / attempts = $DeepMaxAttempts"
Write-Host "=============================================="

function Invoke-Runner([string]$ArgsLine) {
    Write-Host "`n>>> $module $ArgsLine"
    & $py -m $module @($ArgsLine -split " ")
    if ($LASTEXITCODE -ne 0) {
        throw "fundamental runner failed: $ArgsLine (exit=$LASTEXITCODE)"
    }
}

function Invoke-RunnerArgs([string[]]$RunnerArgs) {
    $display = $RunnerArgs -join " "
    Write-Host "`n>>> $module $display"
    & $py -m $module @RunnerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "fundamental runner failed: $display (exit=$LASTEXITCODE)"
    }
}

function Get-LatestTradeDate {
    $marker = Join-Path $evalDataDir "latest.json"
    if (Test-Path $marker) {
        $latest = Get-Content $marker -Raw | ConvertFrom-Json
        return $latest.tradeDate
    }
    return $null
}

# ---------- 1. bootstrap: fetch official CLX batch (content_hash locked) ----------
if (-not (Test-Path (Join-Path $RunDir "clx-official-raw.json"))) {
    if ($SkipBootstrap) {
        throw "run_dir lacks clx-official-raw.json and -SkipBootstrap was set: $RunDir"
    }
    New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
    Invoke-Runner "bootstrap --run-dir $RunDir --trade-date $TradeDate"
}

# ---------- 2. prepare: pure-buy stocks + evidence (financial cached by report period) ----------
Invoke-Runner "prepare --run-dir $RunDir --trade-date $TradeDate --evidence-dir $RunDir/evidence"

# ---------- 2.5 data: multi-source data pack (local quotes + financials + compact) ----------
Invoke-Runner "data --run-dir $RunDir"

# ---------- 3. rank: deterministic quick rank + snapshots + deep specs (deep-limit 200) ----------
Invoke-Runner "rank --run-dir $RunDir --deep-limit 200"

# ---------- 4. deep-run: standard single-stock analysis for the top-100 (closed loop) ----------
if (-not $SkipDeepRun) {
    $deepArgs = @(
        "deep-run",
        "--run-dir", $RunDir,
        "--workers", [string]$DeepWorkers,
        "--max-attempts", [string]$DeepMaxAttempts
    )
    if ($DeepDryRun) {
        $deepArgs += "--dry-run"
    }
    if ($AgentCommand) {
        $deepArgs += "--agent-command", $AgentCommand
    }
    Invoke-RunnerArgs $deepArgs

    # Re-merge deep docs into the ranking (grades update, zones stay fixed).
    Invoke-Runner "rank --run-dir $RunDir"
} else {
    Write-Host "`nSkipped deep-run (-SkipDeepRun); ranking keeps quick grades only."
}

$analysisCount = @(Get-ChildItem (Join-Path $RunDir "fundamental-analysis") -Filter "*.json" -ErrorAction SilentlyContinue).Count
$specCount = @(Get-ChildItem (Join-Path $RunDir "fundamental-analysis-spec") -Filter "*.md" -ErrorAction SilentlyContinue).Count
Write-Host "`n=== deep analysis: $analysisCount / $specCount specs ==="
if ($analysisCount -lt $specCount) {
    Write-Host "Deep analysis incomplete. Check fundamental-deep-run.json /"
    Write-Host "fundamental-deep-run-report.json for per-symbol errors, then re-run."
    Write-Host "Publish below will fail closed unless -AllowIncompleteDeep is set."
}

# ---------- 5. stats: aggregation + batch quality gates ----------
Invoke-Runner "stats --run-dir $RunDir"

# ---------- 6. validate: schema + structural checks ----------
Invoke-Runner "validate --run-dir $RunDir"

# ---------- 7. publish: write to external data dir (webui bind mount) ----------
if (-not $SkipPublish) {
    New-Item -ItemType Directory -Force -Path $evalDataDir | Out-Null
    $allow = ""
    if ($AllowIncompleteDeep) {
        $allow = " --allow-incomplete-deep"
    }
    Invoke-Runner "publish --run-dir $RunDir --data-dir $evalDataDir$allow"

    $latest = Get-LatestTradeDate
    Write-Host "`n=== publish done ==="
    Write-Host "  latest trade date: $latest"
    Write-Host "  data dir:          $evalDataDir"
    Write-Host "  frontend:          http://127.0.0.1:18080/daily-screening"
    Write-Host "  (webui container mounts the dir; no rebuild/commit needed)"
} else {
    Write-Host "`nSkipped publish (-SkipPublish); data not updated."
}

Write-Host "`nCLX_FUNDAMENTAL_DAILY_DONE"
