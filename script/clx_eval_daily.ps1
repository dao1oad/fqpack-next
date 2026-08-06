param(
    [string]$TradeDate = (Get-Date -Format "yyyy-MM-dd"),
    [string]$RunDir = "",
    [switch]$SkipPhaseA,
    [switch]$SkipPublish
)

$ErrorActionPreference = "Stop"

$repo = "D:/fqpack/freshquant-2026.2.23"
$skill = "C:/Users/Administrator/.codex/skills/clx-market-context-evaluator"
$clxRun = Join-Path $skill "run-templates/clx_run.py"
$py = Join-Path $repo ".venv/Scripts/python.exe"

# 评价数据发布目录：出 git，由 fq_webui compose bind mount 提供
$evalDataDir = "D:/fqpack/runtime/artifacts/clx-evaluator"

# 运行目录固定放在仓库外（防止并发 main-sync 清理）
$workRoot = "C:/Users/Administrator/fq-clx-work"
if (-not $RunDir) {
    $RunDir = Join-Path $workRoot "clx-$TradeDate"
}

Write-Host "=============================================="
Write-Host "CLX 日线评价每日运行  trade_date=$TradeDate"
Write-Host "  run_dir      = $RunDir"
Write-Host "  publish_dir  = $evalDataDir"
Write-Host "=============================================="

function Invoke-Skill([string]$ArgsLine) {
    Write-Host "`n>>> clx_run.py $ArgsLine"
    & $py $clxRun @($ArgsLine -split " ")
    if ($LASTEXITCODE -ne 0) {
        throw "clx_run.py 失败: $ArgsLine (exit=$LASTEXITCODE)"
    }
}

function Test-PhaseAComplete([string]$Dir) {
    return Test-Path (Join-Path $Dir "phase-a/market-state.v1.json") -and
           Test-Path (Join-Path $Dir "market-state.lock.json")
}

function Get-LatestTradeDate {
    $marker = "D:/fqpack/runtime/artifacts/clx-evaluator/latest.json"
    if (Test-Path $marker) {
        $latest = Get-Content $marker -Raw | ConvertFrom-Json
        return $latest.tradeDate
    }
    return $null
}

if (-not $SkipPhaseA) {
    # ---------- 1. bootstrap：Phase 0 + 生成 Phase A 启动器 ----------
    if (-not (Test-Path (Join-Path $RunDir "run-request.json"))) {
        New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
        Invoke-Skill "bootstrap --trade-date $TradeDate --external-root $workRoot"
        Write-Host "`n!!! Phase A 需要 clean-room Codex 会话执行（fork_turns=none，无 CLX 上下文）!!!"
        Write-Host "    启动器: $RunDir/run_phase_a.ps1"
        Write-Host "    启动:   Start-Process pwsh -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',`"$RunDir/run_phase_a.ps1`" -WindowStyle Hidden"
        Write-Host "    等待 Phase A 完成（约 15-30 分钟，出现 PHASE_A_COMPLETE）后重新运行本脚本。"
        Write-Host "    （或加 -SkipPhaseA 仅做后续步骤）"
        exit 0
    }
} else {
    if (-not (Test-Path (Join-Path $RunDir "run-request.json"))) {
        throw "run_dir 不存在 run-request.json，先运行 bootstrap/Phase A: $RunDir"
    }
}

if (-not $SkipPhaseA -and -not (Test-PhaseAComplete $RunDir)) {
    Write-Host "Phase A 尚未完成（缺少 market-state.lock.json），请先完成 clean-room Phase A 后重跑。"
    Write-Host "  验证脚本: $skill/scripts/validate_market_state.py"
    exit 0
}

# ---------- 2. Phase B：规范化 + 评价 + 严格验证 ----------
Invoke-Skill "phase-b --run-dir $RunDir"

# ---------- 3. build：评价 + 前端快照 + strict validate ----------
Invoke-Skill "build --run-dir $RunDir"

# ---------- 4. publish：写入外部数据目录（webui bind mount 直接可见）----------
if (-not $SkipPublish) {
    New-Item -ItemType Directory -Force -Path $evalDataDir | Out-Null
    Invoke-Skill "publish --run-dir $RunDir --webui-public $evalDataDir --webui-web $evalDataDir"

    $latest = Get-LatestTradeDate
    Write-Host "`n=== 发布完成 ==="
    Write-Host "  最新交易日: $latest"
    Write-Host "  数据目录:   $evalDataDir"
    Write-Host "  前端地址:   http://127.0.0.1:18080/clx-market-evaluation"
    Write-Host "  验收脚本:   node $skill/run-templates/clx_accept.mjs $latest"
    Write-Host "  （webui 容器已挂载该目录，无需 rebuild 镜像/commit）"
} else {
    Write-Host "`n跳过 publish（-SkipPublish），数据未更新。"
}

Write-Host "`nCLX_EVAL_DAILY_DONE"
