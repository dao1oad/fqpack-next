# 三个开放 Issue 综合分析 + 实施编排方案（2026-08-10）

> 状态：待评审 / 待实施
> 关联：GitHub Issue #545 / #546 / #547（dao1oad/fqpack-next）
> 本文件为跨 Issue 实施编排；各 Issue 细案见：
> - `docs/plans/2026-08-10-must-pool-signal-panel-alignment-plan.md`（#547）
> - `docs/plans/2026-08-10-clx-15-30-tdx-today-overwrite-plan.md`（#546）
> - `docs/plans/2026-08-10-memory-v2-migration-plan.md`（#545）

## 1. 三 Issue 综述

| # | 标题 | 类型 | 影响面 | 规模 | 建议优先级 |
|---|------|------|--------|------|-----------|
| #547 | must_pool 买入信号面板口径与 5 分钟监控不一致 + TDX 导入未知标的边界 | bug 修复（口径分叉 + 边界） | `stock_service.py` / `data/astock/must_pool.py` / 测试 / docs | 小 | P1（先做） |
| #546 | CLX 15/30 监控结果写入通达信当天覆盖 + 持仓同步未持仓即关闭价位配置 | 行为修复（真值对账 + 覆盖写） | `tdx_export.py` / `strategy_consumer.py` / `guardian_buy_grid.py` / `xt_account_sync/service.py` / `tpsl/takeprofit_service.py` / docs | 中 | P2 |
| #545 | 记忆系统 v2 重构：读取端索引化 + 写入端有界化 + 新库并行迁移（B 方案） | 架构重构（agent 上下文层） | `freshquant/runtime/memory/**` / `bootstrap_config.py` memory 段 / `codex_run/**` / `runtime/memory/scripts/` / docs | 大 | P3（最后做） |

依赖关系：无代码级相互依赖；部署面部分重叠（#547 与 #546 都需重部署 `fq_apiserver`）；文档面重叠（`docs/current/runtime.md` 被 #547 与 #545 同时涉及，`docs/current/reference/stock-pools-and-positions.md` 被 #546 与 #547 同时涉及）。

## 2. 代码现状核实（2026-08-10 本机事实）

### 2.1 #547
- `freshquant/stock_service.py:551-572`：`must_pool_buys` 分支 `must_pool.find({})` 无 `disabled`/`instrument_type` 过滤，`stock_signals` 查询无 `period`/`tags` 过滤 —— 口径分叉属实。
- `freshquant/stock_service.py:459-468`：`sync_must_pool_from_tdx_self_select` 循环忽略 `import_pool` 返回值，`failed_codes` 永不填充。
- `freshquant/stock_service.py:471`：`target_code_set = set(synced_codes)` —— 同步失败的代码其旧记录会被覆盖删除。
- `freshquant/data/astock/must_pool.py:319,327,349`：`query_instrument_info` 返回 None 时 `instrument["name"]` 抛 TypeError；函数无显式返回值。
- `freshquant/stock_service.py:895-924`：`add_to_must_pool` 同样忽略返回值。
- `freshquant/tests/test_stock_pool_service.py:542`：既有测试固化旧宽口径（fixture 全为 `period=1m`）。
- `freshquant/pool/general.py:14`：`queryMustPoolCodes()` 存在（60s 缓存，过滤条件 = enabled + stock/etf）。

### 2.2 #546
- `freshquant/market_data/xtdata/strategy_consumer.py:777-880`：`_process_clx_signals` 写库后调 `append_tdx_group_members(sorted codes)` 去重追加；**注意**：`insert_many` 失败（853-854 捕获）后仍继续执行追加（856 行起），实现当天覆盖写时需改为「入库失败跳过 TDX 写入」。
- `freshquant/clx_daily_selection/tdx_export.py`：`append_tdx_group_members`（213）/ `write_clx_tdx_group`（96，CLX_18）/ `_atomic_write_blk`（256）/ `ensure_tdx_group_registered`（176）/ `encode_tdx_blk_code`（28）/ 模块级 `_TDX_BLK_WRITE_LOCK`（25）全部存在，可复用。
- `realtime_screen_multi_period` 索引：docker 实测仅 `_id_`（无 `datetime` 索引），补索引建议成立。
- `freshquant/xt_account_sync/service.py:128-160`：`sync_positions_once` 结构为 `persist_positions` → `empty_snapshot_guard` 早退（138-144）→ `_resolve_effective_positions`（145）→ `reconcile_account`（150）。收敛挂载点应在 guard 早退之后（有效快照才收敛）、reconcile 之前。
- `freshquant/strategy/guardian_buy_grid.py`：`get_config`（110）/ `upsert_state`（215）存在；**无 `disable_grid`**，需新增；`upsert_config` 的 caps 校验在 168-179（capacity 不可用时关闭会失败），`disable_grid` 直写 `$set` 绕过 caps 的动机成立。
- `freshquant/tpsl/takeprofit_service.py:167`：`TakeprofitService.set_tier_manual_enabled(symbol, *, level, enabled, updated_by)` 存在，profile + armed_levels 同步关闭，逐档调用语义匹配。
- docs 现状：`docs/current/modules/market-data-xtdata.md:102` 仍写「去重追加」；`docs/current/reference/stock-pools-and-positions.md:84` 同。

### 2.3 #545
- `freshquant/bootstrap_config.py:49,175-189`：`memory.mongodb.db` 默认 `fq_memory`，支持 `FRESHQUANT_MEMORY__MONGODB__DB` 环境变量覆盖（回滚路径成立）。
- `freshquant/runtime/memory/compiler.py:110-202`：`compile_context_pack` 全量嵌入 `knowledge_items` 全文 + `module_status`（`_format_knowledge_items` / `_format_module_status`），无索引模式 —— 全量预载属实。
- 脚本目录在**仓库根** `runtime/memory/scripts/`（bootstrap/compile/refresh/smoke 四个脚本），包代码在 `freshquant/runtime/memory/`；新 consolidate 脚本建议放 `runtime/memory/scripts/consolidate_freshquant_memory.py`。
- `.codex/memory/` 8 个冷记忆文件存在（与验收「knowledge_items=8」对应）。
- Mongo 实测：仅 `fq_memory` 存在，`fq_memory_v2` 尚未创建 —— B 方案迁移可从零开始。
- 文档漂移：`docs/current/architecture.md:63` 写「bootstrap / archive / retrieval 维护」，archive/retrieval 模块不存在。
- 测试：`test_runtime_memory.py` / `test_runtime_memory_docs.py` / `test_codex_run_entrypoints.py` 均存在。

## 3. 前置状态与 Git 收敛（Phase 0）

本机现状：
- 本地 `main` 领先 `origin/main` 5 个提交（ea25bade 起，均为部署/排障相关）。
- `docs/plans/` 三个 Issue 方案文档未跟踪。

决策（默认方案）：
1. 从本地 main 建 `codex/sync-local-main-ahead` 分支，把 5 个本地提交 + 3 个方案文档作为一个 PR 合入远程 main（禁止直推 main），恢复「feature 分支基于最新远程 main」的干净基线。
2. 三个实施 PR 依次基于更新后的 main 创建，串行合并（防 docs 冲突）。

## 4. 实施编排

### PR-1：#547 must_pool 面板口径对齐 + TDX 导入边界

分支：`codex/fix-must-pool-signal-panel-alignment`

改动（细案见 `2026-08-10-must-pool-signal-panel-alignment-plan.md`）：
- F1 `stock_service.py:551-572`：`period="5m"` + `tags="must_pool_5m_new_open"` + enabled 池过滤；**建议直接复用 `queryMustPoolCodes()`**（与监控同函数，永不分叉），并将 tag 提为模块级常量。
- F2 `must_pool.py:319` 后加 None 分支返回 False；`stock_service.py:459-469` 按返回值计 `failed_codes` 并 try/except 单条兜底；`stock_service.py:471` 改为 `target_code_set = set(synced_codes) | set(failed_codes)`；`add_to_must_pool` 处理返回值。
- F3 测试更新 + 新增 2 个用例。
- F5 docs：`stock-pools-and-positions.md:63-65`、`strategy-guardian.md:32-37`、`runtime.md:37`（15s/30s 分层）。

部署：重部署 `fq_apiserver`（rear 镜像）；健康检查 = API 存活 + 接口口径抽查 + TDX 同步一次成功。

### PR-2：#546 CLX TDX 当天覆盖写 + 持仓未持仓即关闭

分支：`codex/clx-tdx-today-overwrite-position-cleanup`

改动（细案见 `2026-08-10-clx-15-30-tdx-today-overwrite-plan.md`）：
- `tdx_export.py` 新增 `write_tdx_group_members`（覆盖写 + per-code 容错 + 空列表 no-op + 复用原子写/注册）。
- `strategy_consumer.py::_process_clx_signals`：**入库失败跳过 TDX 写入**（修复 853-854 后仍追加的现状）；锁内「查询当天记录 → 按 code 取 max(datetime) → (datetime, code) 升序 → 覆盖写」。
- `realtime_screen_multi_period.datetime` 补索引。
- `guardian_buy_grid.py` 新增 `disable_grid`（判空 + 直写 `$set` 绕过 caps、不 upsert）+ `upsert_state`。
- `xt_account_sync/service.py::sync_positions_once`：`empty_snapshot_guard` 早退之后、reconcile 之前挂收敛（启用配置 − 持仓集合 → 逐档/逐 code 关闭 + runtime 事件留痕，best-effort 幂等）。
- 测试：tdx_export、consumer、xt_account_sync、tpsl、guardian_buy_grid 既有用例零回归 + 新增用例。
- docs：`market-data-xtdata.md:102`、`stock-pools-and-positions.md:84` 改「当天覆盖写 + 未持仓即关闭」。

部署：重启 `fqnext_realtime_xtdata_consumer` + 重部署 `fq_apiserver` + 重启 `fqnext_xt_account_sync_worker`；生产验收 = 盘中观察文件行序、重启后内容一致、一轮同步后未持仓配置关闭。

### PR-3：#545 记忆系统 v2（B 方案）

分支：`codex/memory-v2-refactor`（可拆 PR-A 读取端 / PR-B 写入端）

流程（细案见 `2026-08-10-memory-v2-migration-plan.md`）：
- Step 0：`bootstrap_config.py` memory.mongodb.db 切 `fq_memory_v2`（保留环境变量回滚）。
- Step 1：mongodump 归档 `fq_memory` + context-packs 目录改名冻结。
- Step 2：PR-A 读取端（pack 索引化 + 按需检索 + docs 对齐）+ PR-B 写入端（git_status 摘要 ≤1KB、task_events 有界、consolidate 脚本、注入可观测性）。
- Step 3：从正式真值重新播种（跑新 bootstrap 生成干净基线）。
- Step 4：对照验收标准验证（knowledge=8 / module_status=14 / task_state 1 条 / task_events ≤5 / pack ≤25KB·200 行 / deploy·health 真实产物）。
- Step 5：观察 1-2 周后清理归档。

部署：无常驻服务重启；`codex_run/start_freshquant_codex.ps1` 与 AGENTS.md 自举规则随 PR 同步；回滚 = `FRESHQUANT_MEMORY__MONGODB__DB=fq_memory`。

## 5. 冲突与风险

| 风险 | 缓解 |
|------|------|
| docs 重叠（runtime.md / stock-pools-and-positions.md 被多个 PR 修改） | 三个 PR 串行合并；每个 PR 内 docs 改动与代码同 PR 提交；docs-current-guard 强制把关 |
| #546 收敛在空快照早退后挂载 | 代码 138-144 行 guard 已确认，收敛放 145 行后、150 行前 |
| #546 入库失败仍写 TDX | 实现时 insert 失败 return/skip，避免「库无、文件有」假信号 |
| #545 迁移期旧会话继续写 fq_memory | Step 0 先行切换配置并同步 codex_run 入口；旧库冻结 + mongodump 可回滚 |
| 本地 main 领先 5 提交未同步 | Phase 0 先以 PR 同步，恢复干净基线 |

## 6. Done 定义（每个 PR 独立）

`Done = PR 合并 + CI 三绿（docs-current-guard / pre-commit / pytest）+ docs/current 同步 + 受影响模块部署 + 健康检查 + cleanup（删分支/临时文件）`（AGENTS.md 第 8 节）。
