# 持仓复盘页加载性能优化设计（Codex × Devin 一致结论）

> 状态：**最终方案已确认（方案A = S1 现算消重止血）**，未实施。参与方：Codex（主分析）+
> Devin Ultra（第二意见评审，多轮，只读）。
> 最终结论（双方一致）：**确认方案A（S1）为最终可实施方案**——组合接口复用统一目录快照、
> 单飞、恢复 refresh 语义、credit/xt_assets 只读一次；不落库、不加 Redis/worker、
> 不改接口合同。物化方案（S2/S3，用户曾提出「新订单完成时预计算、前端只读」）经讨论后
> **长期搁置**，S1 不预置任何 S2 结构。

## 1. 背景与现状（代码级事实）

### 1.1 页面运行链路

- 入口路由 `/position-review` → 懒加载
  `morningglory/fqwebui/src/views/PositionReview.vue`，`onMounted` 串行执行
  `loadInitialData()`：`loadSummary()` → `loadSymbols({forceDetail: true})` →
  `loadSymbolDetail(选中标的)`。
- 默认激活「组合总览」tab（`activeWorkbenchTab = ref('portfolio')`），其子组件
  `morningglory/fqwebui/src/components/position-review/PortfolioOverview.vue`
  `onMounted` 用 `Promise.allSettled` 并行发 3 个组合请求：
  `portfolio/summary`、`portfolio/series?period=day`、`portfolio/contributions`。
- 一次页面打开至少 6 个后端请求；API 封装在
  `morningglory/fqwebui/src/api/positionReviewApi.js`。

### 1.2 后端读模型

- 路由：`freshquant/rear/position_review/routes.py`；服务：
  `freshquant/position_review/service.py`（单例 `PositionReviewService`）；
  数据访问：`freshquant/position_review/repository.py`、
  `freshquant/position_review/runtime_repository.py`。
- `_get_catalog_snapshot()`（service.py 行735）带 30s TTL 内存目录缓存
  `_catalog_cache`（`rows` + `detail_by_symbol`）；summary/symbols/detail 走该缓存。
- 缓存未命中时 `_build_symbol_rows()`（行773）全量重建：
  - `repository.load_catalog_bundles()`（repository.py 行223）：对 11 个 Mongo 集合
    `find({})` 全表读取（无过滤、无投影、无分页）；
  - `_runtime_catalog_evidence()`：ClickHouse guardian 事件分页拉取，
    `page_size=5000`、上限 500,000 条（runtime_repository.py 行52，无时间窗）；
  - 逐标的 `_build_detail()`（service.py 行973）：成交关联、库存重建、逐单复盘、图表投影。
- 组合接口**不走目录缓存**：`_build_portfolio_inputs()`（service.py 行473）开头
  `del refresh`，每次请求独立重跑全量重建 + `replay_cost_basis` +
  `list_xt_assets()` + `list_credit_asset_snapshots(limit=200_000)`（行530-531）。
- `get_event_conditions()`（行363）：遍历目录内全部 symbol，对每个 symbol 调用
  `_load_symbol_bundle()`（约 11 次 Mongo 查询），最坏 O(N×11) 数据库往返。
- `get_symbol_chart()`（行234）：每次 `_load_symbol_bundle` + `_build_detail` 重算，
  不共享目录缓存。

### 1.3 实测数据（本地 API http://127.0.0.1:15000，10 个标的，缓存已热）

| 接口 | 实测耗时 | 说明 |
|---|---|---|
| `summary` | 0.073s | 缓存命中 |
| `symbols` | 0.002s | 缓存命中 |
| `detail 600917` | 0.77s | 缓存命中但 deepcopy 大对象 |
| `chart 600917` | 0.028s | 无缓存、数据量小 |
| `portfolio/summary` | 0.82s | 每次全量重建 |
| `portfolio/series` | 1.05s | 每次全量重建 |
| `portfolio/contributions` | 0.79s | 每次全量重建 |

## 2. 问题诊断（双方一致）

1. **组合接口 3 连发 × 每次全量重建（首要瓶颈）**：3 个组合请求相互独立、
   内容高度重复，同一份重活同时做 3 遍；且都不走 30s 目录缓存。
2. **`del refresh` 静默失效语义**：`get_symbol_chart`（行251）、
   `get_event_conditions`（行366）、`_build_portfolio_inputs`（行476）三处
   `del refresh`，刷新参数被吞掉，与 summary/symbols/detail 的 refresh 语义不一致。
3. **一次重建内 `xt_trades` 被重复全扫**：`_annotate_execution_conflicts`
   （repository.py 行314）在 `_list_all_execution_fills` 与
   `_list_all_trade_facts` 中各全扫一次 `xt_trades`（`find({})`）；
   组合 3 请求并发时放大为多次全扫。
4. **20 万条 credit 快照每个组合请求各读一遍**：`list_credit_asset_snapshots(limit=200_000)`
   在 3 个组合接口中各执行一次，无复用。
5. **`get_event_conditions` 是 O(N×11) 查询**：hover 一次主图 marker，
   最坏对目录内每个 symbol 重读整包。
6. **目录缓存命中路径的 deepcopy 成本**：`_get_catalog_snapshot` 命中时
   `deepcopy(cached["rows"])`，`_get_cached_catalog_detail` 命中时 deepcopy 整个标的详情，
   目录变大后每次请求的拷贝成本线性上涨。

## 3. 候选方案 A-F 评审结论

| 候选 | Devin 评审 | Codex 核验 | 结论 |
|---|---|---|---|
| A. 组合接口复用目录缓存 / 加 TTL 缓存 | 方向正确，但应扩展为「统一快照 + 单飞 + 恢复 refresh 语义」，而非仅加一层缓存 | 行473 `del refresh`、行530-531 每请求重读均属实 | **采纳（扩展后）**，作为 S1 |
| B. 前端 3 请求合并/串行 | 优先级低于后端复用快照；合并接口会破坏接口独立性 | 前端 `Promise.allSettled` 并发属实 | **采纳（降级为前端小修）**，不改接口合同 |
| C. ClickHouse 加时间窗 | **有翻转 verdict 的语义风险**：历史阈值/可卖约束证据被窗口截断可能把 PASS/FAIL 降为 INSUFFICIENT_EVIDENCE，不是纯性能改动 | 阈值来自 runtime 事件（replay.py `build_historical_threshold_ratios`），截断确会改变判定 | **需修改后采纳**：窗口以目录首末成交区间为界（而非固定近 N 天），且只作为安全上限不参与判定逻辑 |
| D. `get_event_conditions` 按 event 定位 | 认可方向，未展开 | 行363-425 遍历全目录属实 | **采纳**：目录快照内建 `event_id → symbol` 轻量索引，避免 O(N×11) |
| E. `get_symbol_chart` 复用目录 detail | 认可方向 | 行255-267 每次重读 bundle + 重算 detail 属实 | **采纳**：与 `get_symbol_detail` 共用 `_get_cached_catalog_detail` |
| F. Mongo `(symbol, trade_time)` 索引 | **救不了 `find({})` 全扫路径**：目录批量重建走全扫，索引只对单标的路径有效 | 行223-290 全扫属实；索引仅利于 `_load_symbol_bundle` 单标的查询 | **部分采纳**：作为辅助项，不改变「批量走全扫」的主结论 |

## 4. 116 生产故障复现与根因（2026-08-09，来源：生产实测）

### 4.1 故障现象

- 用户报告：`192.168.1.116` 页面（`http://192.168.1.116:18080/position-review`）
  显示「加载全局复盘摘要失败：timeout of 15000ms exceeded」。
- 该文案对应前端 `PositionReview.vue` 的 `loadErrors.summary` 分支；
  `timeout of 15000ms exceeded` 是 `morningglory/fqwebui/src/http.js` 中
  `axios timeout: 15000` 触发的 `ECONNABORTED`，**不是 nginx 超时**：
  `morningglory/fqwebui/nginx.conf` 对 `/api/` 未设 `proxy_read_timeout`
  （默认 60s），15s 限制完全来自前端 axios。

### 4.2 本机复现数据（对 192.168.1.116:15000 直连实测）

页面打开的真实并发场景（6 个请求，目录缓存**冷**，TTL 过期后并发触发）：

| 接口 | 冷缓存并发实测 | 是否超 15s |
|---|---|---|
| `summary` | 3.47s | 否（并发负载下可能被拖超时） |
| `symbols` | 3.39s | 否 |
| `portfolio/summary` | 10.90s | 否（临界） |
| `portfolio/series` | **18.95s** | **是** |
| `portfolio/contributions` | **26.48s** | **是** |

缓存热时的同一并发场景：

| 接口 | 热缓存并发实测 |
|---|---|
| `summary` / `symbols` | 0.004s / 0.008s |
| `portfolio/summary` | 7.47s |
| `portfolio/series` | 15.39s |
| `portfolio/contributions` | 22.84s |

结论：**组合接口在 116 上无论缓存冷热都远超 15s 前端超时线**；summary/symbols
走目录缓存（冷时约 3.4s 重建，热时毫秒级）。用户看到的 summary 报错，是冷缓存
首开 + 3 个组合接口并发重建挤占单进程 gevent 资源时，summary 请求被拖至超时；
而稳定超时的是 `portfolio/series` 与 `portfolio/contributions`。

### 4.3 116 数据规模（根因放大的具体量级）

生产 Mongo（116，Docker 内实测）：

| 集合 | 行数 |
|---|---|
| `xt_trades` | 615 |
| `om_execution_fills` / `om_trade_facts` | 0（当前账本以请求/订单为主） |
| `stock_signals` | 843 |
| `pm_strategy_decisions` | 262 |
| `pm_credit_asset_snapshots` | **523,906** |
| `xt_assets` | 1 |

生产 ClickHouse：`runtime_events` 共 77,774 条，其中 guardian 复盘相关
（`price_threshold_check` / `sellable_volume_check`）仅 884 条 → **ClickHouse
事件量不是 116 的瓶颈**。

根因量化：`_build_portfolio_inputs()`（service.py 行473）每次请求
`list_credit_asset_snapshots(limit=200_000)` 读 20 万条并做分钟聚合
（portfolio_projection.py `build_portfolio_series`），3 个组合接口并发
= 3 份独立全量重建 + 最高 60 万条 credit 快照读取/聚合 + 3 次
`load_catalog_bundles()` 全扫 + 3 次 `_annotate_execution_conflicts`
重复全扫 `xt_trades`，单请求 15~27s，稳定击穿前端 15s 超时。

## 5. 预计算物化方案（第二轮讨论一致结论，用户诉求核心）

> 用户诉求：不要在前端请求时现算，希望在某时机（如新订单完成时）预先算一遍并保存，
> 前端只读计算后的结果直接展示。双方（Codex + Devin Ultra，单轮只读评审）一致结论如下。

### 5.1 方案定性（双方一致）

- **方向正确**：写侧触发物化 + 前端只读，是比「请求时现算 + 缓存」更彻底的形态。
- 但**不能只靠「订单完成」一个触发**，必须是「事件触发 + 时间驱动」双轨：
  - 订单/成交事件（`xt_reports.py` ingest）触发 **symbol 级 / 全量重算**；
  - 权益曲线数据源 `pm_credit_asset_snapshots`（分钟级写入、无成交也在变）由
    **时间驱动水位增量**补充，否则组合 series 会陈旧。
- 存储形态：**Mongo 投影集合 `position_review_snapshots`（写侧物化）+ Redis 只做
  dirty 标记 / 跨进程版本号 + Dagster 每日收盘全量兜底**。
- 前端最终只读 `position-review` API 返回的物化快照，不再触发任何重算。

### 5.2 两个代码事实修正（Devin 指出，Codex 已核验属实）

1. **`mark_stock_holdings_projection_updated()` 只是进程内 dict 计数器**
   （`freshquant/database/cache.py:42-51`，`_cache_versions: defaultdict(int)`；
   未写 Redis，虽然 `redis_cache` 已存在）。ingest 运行在 `xt_account_sync.worker`
   进程、API 运行在另一进程（Docker `fq_apiserver`），**该失效信号从未跨进程生效**。
   → 预计算方案的跨进程失效标记必须搬进 Redis（如 `INCR position_review_dirty_version`）。
2. **权益曲线依赖分钟级写入的 `pm_credit_asset_snapshots`**（116 实测 523,906 条，
   由 `xt_account_sync.worker` 持续写入；见 `docs/current/architecture.md` 链路
   `xt_account_sync.worker -> pm_credit_asset_snapshots`）。无成交时曲线也在变，
   "订单完成触发"覆盖不到 → 必须配时间驱动的水位增量双轨。

### 5.3 物化存储与一致性（双方一致）

| 项 | 选择 | 理由 |
|---|---|---|
| 物化位置 | Mongo `position_review_snapshots`（新投影集合，含 schema_version + generated_at + 数据质量标记） | 可跨进程读、可回滚、与既有 `pm_*` 投影同风格；避免进程内缓存重启丢失 |
| 失效标记 | Redis 版本号（`INCR`） | 跨进程（worker 与 apiserver）真正生效；替代进程内 `bump_cache_version` |
| 兜底 | Dagster 每日收盘全量重算 job | 覆盖错过事件、进程重启、数据修复；保证每日终态正确 |
| 增量 | S2 先「事件触发 + 异步全量重算写快照」；S3 再做 series 水位追加增量 | symbol 级增量可行但非首要收益——最大放大项（52 万 snapshot 扫描）与 symbol 无关 |
| 降级 | 重算失败保留旧快照 + 告警，前端照常读旧结果 | 写侧（成交回报）是主链路，不能因重算失败卡成交或阻塞 ingest |

### 5.4 触发链路设计（双方一致）

```
xt_reports.py ingest 成功
  └─ ① INCR Redis position_review_dirty_version（非阻塞，不卡成交主链路）
      └─ ② 异步 worker 检测到版本变化 → 全量重算 → 写 position_review_snapshots
           （或同步小重算 + 异步大重算分级）
  └─ ③ 时间驱动：水位增量任务按 queried_at 追加 pm_credit_asset_snapshots 聚合
       → 更新组合 series（与订单事件无关，独立触发）
  └─ ④ Dagster 每日收盘全量兜底重算
前端 GET /api/position-review/* → 直接读物化快照（30s TTL 内存缓存仅作读加速）
```

- 写侧不因重算失败而阻塞：Redis `INCR` 是唯一同步动作，失败仅告警；
  重算任务独立进程/worker，与 `xt_account_sync.worker` 解耦。
- 幂等：快照按 `(symbol, schema_version, generated_at)` 覆盖写，天然幂等；
  并发重算用 Redis 锁（`SET NX`）防双写。

### 5.5 分阶段实施（双方一致，各阶段可单独上线、可回滚）

| 阶段 | 内容 | 文件 | 验收（116） | 回滚 |
|---|---|---|---|---|
| S1 止血（现算消重） | 组合接口复用统一目录快照 + 单飞 + 恢复 refresh 语义；`xt_assets`/credit 快照读一次复用 | `freshquant/position_review/service.py`、`repository.py` | 首开 6 请求全部 <15s（组合 tab ≤2s 目标） | 一行开关回退原路径，无数据迁移 |
| S2 写侧触发物化 | 新增 `position_review_snapshots` 投影；ingest 后 `INCR` Redis 版本号；异步 worker 全量重算写快照；API 改为优先读快照（灰度开关） | `freshquant/order_management/ingest/xt_reports.py`、新增 `freshquant/position_review/snapshot_worker.py`、`repository.py`、`database/cache.py`（版本号入 Redis） | 冷启动首开 ≤3s；重算 <10s；写侧零阻塞 | 灰度开关关闭即回读模型，快照集合可保留不删 |
| S3 前端纯只读 + 增量 | 前端切到只读快照结果；series 水位追加增量（重算 <1s）；去掉请求时重算路径 | `freshquant/position_review/portfolio_projection.py`、`service.py`；`morningglory/fqwebui/src/components/position-review/PortfolioOverview.vue` | 重算 <1s；页面无 timeout；权益曲线分钟级新鲜 | 前端还原 + 保留 S2 开关 |

- **S1 必须先于 S2**：S2 依赖对现有重建路径的消重结论；S1 同时是 116 生产故障的止血方案。
- **S2/S3 的 Mongo 投影、Redis 版本号、Dagster 兜底** 为新增只读/辅助设施，不改变
  "复盘 API 只读、归档只写不读" 的既有边界。
- 业务逻辑双份维护风险（现算路径 vs 物化路径）由「S3 移除请求时重算路径」收敛为单份；
  S1/S2 过渡期保留双份但以物化路径为准、现算路径仅作回退。

## 6. 分歧点与收敛（双方一致）

1. **分歧**：Codex 原方案把 C（ClickHouse 时间窗）列为独立性能项；Devin 指出其会
   改变判定语义。**收敛**：接受 Devin 判断，C 降级为可选且加边界条件，不在首轮实施。
2. **分歧**：Codex 原方案把 F（索引）列为通用提速；Devin 指出 `find({})` 全扫路径
   不受益。**收敛**：接受 Devin 判断，F 降为辅助项并限定单标的路径。
3. **分歧**：Codex 原方案倾向「前端合并 3 组合接口为 1 个」；Devin 建议保留接口独立性、
   后端先共享快照。**收敛**：接受 Devin 判断，B 降为前端小修，不改后端接口合同。
4. **分歧**：Codex 倾向「订单完成触发即可」；Devin 指出权益曲线数据源分钟级变化，
   单事件触发覆盖不全。**收敛**：事件 + 时间驱动双轨。
5. **分歧**：Codex 假设 `mark_stock_holdings_projection_updated()` 是跨进程失效信号；
   Devin 指出它只是进程内计数器。**收敛**：失效标记搬进 Redis。
6. **分歧**：Codex 原方案把 symbol 级增量列为重点；Devin 指出最大放大项
   （52 万 credit 快照）与 symbol 无关，增量收益有限。**收敛**：S2 全量重算写快照、
   S3 再做 series 水位增量。
7. **一致**：A 方向正确但必须扩展为「统一快照 + 单飞 + 恢复 refresh 语义」，
   不能只是加一层 TTL 缓存；用户「新订单完成时预计算」方向正确但要双轨。

## 7. 落地与验收总纲

- **最终实施范围：方案A（S1），仅改 `freshquant/position_review/service.py` 与
  必要时 `repository.py`**；S2/S3 物化方案长期搁置，不预置 snapshots 集合、不加 Redis
  版本号、不加异步 worker。
- 遵循 `AGENTS.md` 正式工作流：`local session → feature branch → PR → merge → deploy`；
  改动影响 `freshquant/rear/**`，需重部署 API server 并做健康检查。
- 验收：以 1.3/4.2 实测为基线，S1 后 116 首屏组合 tab 目标 ≤2s、全部 6 请求 <15s；
  热缓存毫秒级；refresh=1 语义可观测且单飞；组合接口不再超 15s timeout；
  **额外确认热路径 P95 不因快照 deepcopy 回升**。
- 部署约束：116 出站 TLS 异常，代码用 git bundle + scp，镜像用 docker save/load
  （见 `docs/current/machines.md` §5.3），禁止在 116 上 pip/uv/docker pull 官方源。
- 本文件为设计结论，正式文档 `docs/current/**` 在实施 PR 内同步更新。

## 8. 最终方案确认（方案A = S1，2026-08-09 第三轮，Devin 明确同意）

> Devin 单轮结论：「同意方案A（S1 现算消重止血）为最终方案，不落库、不加 Redis/worker、
> 不改接口合同、不动 ClickHouse 时间窗，边界正确，可独立上线/回滚；同意 S2/S3 物化方案
> 长期搁置、方案A先落地。」以下 3 个实施细节为 Devin 提出、Codex 核验后纳入的
> **落地正确性要求（不改变方案本身）**：

### 8.1 快照结构必须扩展承载组合接口所需字段

- 现有 `_catalog_cache` 只存 `rows + detail_by_symbol`（service.py 行760-765）；
  组合接口还需：`cost_by_symbol`（`replay_cost_basis`，行506）、`positions`、
  holding-only 行（`_append_holding_only_portfolio_rows`，当前目录快照路径不含）、
  `xt_assets`、`credit_snapshots`。
- 快照结构必须扩展承载这五项，否则组合接口复用后会丢失 holding-only 标的与成本口径。

### 8.2 52 万条 credit_snapshots 严禁进入命中路径的 deepcopy

- `_get_catalog_snapshot` 命中时会对 `cached["rows"]` 做 `deepcopy`（行751）；
  credit 快照（116 实测 523,906 条）**不得**随快照整体 deepcopy。
- 正确做法：credit 快照按引用只读复用，或直接缓存**聚合后的 series 中间结果**；
  否则热路径每请求拷贝 52 万条会把优化吃回去。

### 8.3 refresh 单飞重建必须连同组合数据源一起重读

- `refresh=True` 触发快照重建时，`xt_assets` / `credit_snapshots` 必须一并重读，
  保证 refresh 语义覆盖组合数据源（不能只刷新 rows/detail 而组合数据陈旧）。
- 30s TTL 内 credit 数据陈旧 ≤30s，与分钟级写入频率相容，可接受。

### 8.4 验收补充

- 冷缓存首开全部 6 请求 <15s，组合 tab 首屏 ≤2s 目标；
- 热缓存毫秒级，热路径 P95 不因快照 deepcopy 回升；
- `refresh=1` 语义可观测且单飞；组合接口不再超 15s timeout。
