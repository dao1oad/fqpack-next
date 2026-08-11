param(
    [string]$TradeDate = (Get-Date -Format "yyyy-MM-dd"),
    [string]$RunDir = "",
    [switch]$SkipBootstrap,
    [switch]$AllowIncompleteDeep,
    [switch]$SkipPublish
)

$ErrorActionPreference = "Stop"

$repo = "D:/fqpack/freshquant-2026.2.23"
$skill = "C:/Users/Administrator/.codex/skills/clx-market-context-evaluator"
$clxRun = Join-Path $skill "run-templates/clx_run.py"
$py = Join-Path $repo ".venv/Scripts/python.exe"
$fundamentalRunner = Join-Path $repo "freshquant/clx_daily_selection/fundamental/runner.py"

# 评价数据发布目录：出 git，由 fq_webui compose bind mount 提供
$evalDataDir = "D:/fqpack/runtime/artifacts/clx-evaluator"

# 运行目录固定放在仓库外（防止并发 main-sync 清理）
$workRoot = "C:/Users/Administrator/fq-clx-work"
if (-not $RunDir) {
    $RunDir = Join-Path $workRoot "clx-$TradeDate"
}

Write-Host "=============================================="
Write-Host "CLX 基本面评价每日运行  trade_date=$TradeDate"
Write-Host "  run_dir      = $RunDir"
Write-Host "  publish_dir  = $evalDataDir"
Write-Host "=============================================="

function Invoke-Runner([string]$ArgsLine) {
    Write-Host "`n>>> runner.py $ArgsLine"
    & $py $fundamentalRunner @($ArgsLine -split " ")
    if ($LASTEXITCODE -ne 0) {
        throw "fundamental runner 失败: $ArgsLine (exit=$LASTEXITCODE)"
    }
}

function Get-LatestTradeDate {
    $marker = "D:/fqpack/runtime/artifacts/clx-evaluator/latest.json"
    if (Test-Path $marker) {
        $latest = Get-Content $marker -Raw | ConvertFrom-Json
        return $latest.tradeDate
    }
    return $null
}

# ---------- 1. bootstrap：拉取 CLX 正式批次（content_hash 锁定）----------
if (-not (Test-Path (Join-Path $RunDir "clx-official-raw.json"))) {
    if ($SkipBootstrap) {
        throw "run_dir 缺少 clx-official-raw.json 且指定了 -SkipBootstrap: $RunDir"
    }
    New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
    & $py $clxRun bootstrap --trade-date $TradeDate --external-root $workRoot
    if ($LASTEXITCODE -ne 0) {
        throw "bootstrap 失败: exit=$LASTEXITCODE"
    }
    $batchRun = Get-ChildItem $workRoot -Directory -Filter "*$TradeDate*" |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($batchRun) {
        $RunDir = $batchRun.FullName
    }
}

# ---------- 2. prepare：pure-buy Stock + 证据包（静态财务按报告期缓存）----------
Invoke-Runner "prepare --run-dir $RunDir --trade-date $TradeDate --evidence-dir $RunDir/evidence"

# ---------- 3. rank：全量确定性快排 + 深析合并 + 快照 + 深析规格 ----------
Invoke-Runner "rank --run-dir $RunDir"

# ---------- 4. 深析规格说明（快排前 100 只，agent 执行，不简化）----------
$specDir = Join-Path $RunDir "fundamental-analysis-spec"
$analysisDir = Join-Path $RunDir "fundamental-analysis"
$specCount = @(Get-ChildItem $specDir -Filter "*.md" -ErrorAction SilentlyContinue).Count
$analysisCount = @(Get-ChildItem $analysisDir -Filter "*.json" -ErrorAction SilentlyContinue).Count
Write-Host "`n=== 深析规格：$specCount 份；已存在深析：$analysisCount 份 ==="
if ($analysisCount -lt $specCount) {
    Write-Host "快排前 100 只需要标准单股深析（a-share-fundamental-analysis，不简化）。"
    Write-Host "  规格目录: $specDir（每只一份 <symbol>.md）"
    Write-Host "  产出目录: $analysisDir（每只一份 <symbol>.json）"
    Write-Host "  schema:   $repo/freshquant/clx_daily_selection/fundamental/schemas/fundamental-analysis.schema.json"
    Write-Host "深析未齐时 publish 将失败；可显式加 -AllowIncompleteDeep 发布 amber 批次。"
}

# ---------- 5. stats：统计聚合 + 批次质量门 ----------
Invoke-Runner "stats --run-dir $RunDir"

# ---------- 6. validate：schema/结构校验 ----------
Invoke-Runner "validate --run-dir $RunDir"

# ---------- 7. publish：写入外部数据目录（webui bind mount 直接可见）----------
if (-not $SkipPublish) {
    New-Item -ItemType Directory -Force -Path $evalDataDir | Out-Null
    $allow = ""
    if ($AllowIncompleteDeep) {
        $allow = " --allow-incomplete-deep"
    }
    Invoke-Runner "publish --run-dir $RunDir --data-dir $evalDataDir$allow"

    $latest = Get-LatestTradeDate
    Write-Host "`n=== 发布完成 ==="
    Write-Host "  最新交易日: $latest"
    Write-Host "  数据目录:   $evalDataDir"
    Write-Host "  前端地址:   http://127.0.0.1:18080/daily-screening"
    Write-Host "  （webui 容器已挂载该目录，无需 rebuild 镜像/commit）"
} else {
    Write-Host "`n跳过 publish（-SkipPublish），数据未更新。"
}

Write-Host "`nCLX_FUNDAMENTAL_DAILY_DONE"
