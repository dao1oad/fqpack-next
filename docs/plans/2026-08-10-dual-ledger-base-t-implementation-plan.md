# 双账本底仓/T + 标的设置保存门禁联合实施计划

> 日期：2026-08-10
> 关联：GitHub Issue #549、#548
> 主方案：`docs/plans/2026-08-10-dual-ledger-base-t-final.md`（v4.1）
> 实施分支：`codex/dual-ledger-base-t`
> 状态：实施会话使用本地同目录工作区；先完成后端账本/状态机，再完成前端保存门禁，统一验收后合并本地 `main`、推送远程并部署 101/100/116。

## 1. 实施目标

### 1.1 Issue #549：双账本与固定价格底仓

- 首开、手动首开、手动加仓、固定买入线补仓 → `base`；
- Guardian 信号加仓、破线区深档做 T → `t`；
- TPSL 只卖 `base`，Guardian 只卖 `t`；
- 建立 3 条 BUY 线 + 3 条 TP 线的对称阶梯状态机；
- 容量统一为：
  `R = cap - max(D + C, MV) - 在途买单金额`；
- `D/C` 最简实现为该账本剩余股数 × 当前市场价；
- 完成历史回填、存量 TP 激活、API/前端双账本展示。

### 1.2 Issue #548：标的设置保存门禁

- 所有 KlineSlim 标的设置写操作必须建立在对应后端 detail 已加载完成；
- 加载中、加载失败、detail 缺失时，按钮/开关/拖线保存禁用；
- 已加载且后端值为 `null` 时显示默认值并标记“默认”，保存即把当前展示值落库；
- 保存 payload 采用当前展示值，不做字段省略；
- 只改 Web UI，不改后端接口。

## 2. 实施边界与顺序

1. 先完成 #549 后端最小纵向切片：数据打标 → 状态机 → BUY/TP 执行 → ingest 对账 → 后端测试。
2. 同一实施分支完成 #548 前端门禁，避免 `guardian_buy_grid_configs` 新字段/状态接口变化后前端保存链路失配。
3. 再完成 #549 前端双账本展示与接口透传。
4. 最后执行联合测试、文档同步、PR/CI、合并与三机部署。

## 3. 代码改动范围

### 3.1 #549 后端

- `freshquant/strategy/common.py`
- `freshquant/strategy/guardian.py`
- `freshquant/strategy/guardian_buy_grid.py`
- 新增 `freshquant/strategy/guardian_ladder.py`
- `freshquant/tpsl/service.py`
- `freshquant/tpsl/takeprofit_quantity.py`
- `freshquant/tpsl/takeprofit_service.py`
- `freshquant/tpsl/consumer.py`
- `freshquant/tpsl/pools.py`
- `freshquant/order_management/guardian/arranger.py`
- `freshquant/order_management/guardian/allocation_policy.py`
- `freshquant/order_management/guardian/read_model.py`
- `freshquant/order_management/guardian/slice_evaluation.py`
- `freshquant/order_management/entry_aggregation.py`
- `freshquant/order_management/entry_adapter.py`
- `freshquant/order_management/ingest/xt_reports.py`
- `freshquant/order_management/rebuild/service.py`
- `freshquant/order_management/manual/service.py`
- `freshquant/rear/stock/routes.py`
- `freshquant/position_review/service.py`
- 新增 `script/maintenance/backfill_position_type.py`

### 3.2 #548 前端

- `morningglory/fqwebui/src/views/KlineSlim.vue`
- `morningglory/fqwebui/src/views/js/kline-slim-price-panel.mjs`
- `morningglory/fqwebui/src/views/js/kline-slim-subject-panel.mjs`
- 对应前端单测与 `subjectManagementPage.test.mjs`

### 3.3 #549 前端与文档

- `morningglory/fqwebui/src/views/StockPositionList.vue`
- `morningglory/fqwebui/src/views/PositionReview.vue`
- `morningglory/fqwebui/src/api/stockApi.js` 等透传文件
- `docs/current/modules/strategy-guardian.md`
- 必要时同步 `docs/index.md` 索引

## 4. 关键实现约束

### 4.1 状态机

- BUY 线提交时先关触发档及以上买入线，并全开 TP；
- TP 提交时先关该档，成交后关该档及以下 TP 并全开 BUY；
- 撤单、废单、部分成交后撤单按订单状态幂等重开未成交对应档；
- 状态使用单文档字段级原子 `$set`，联动字段在同一 Mongo 更新内写入；
- 条件更新冲突：
  - tick 路径在下一 tick 重试；
  - XT ingest 成交/撤单路径在当前事件内进行有限重试，并输出失败清单/告警；
- 事件以 `broker_order_id`/`intent_id` 幂等，重复报告不得重复重算。

### 4.2 账本与容量

- 读取侧 `position_type != "t"` 一律视为 `base`；
- `D/C = 剩余股数 × 当前市场价`，不新增 `cost_price`；
- `MV` 缺失时买入路径 fail-closed；
- buy line universe = 持仓 ∩ 有 buy grid 配置；
- TP/SL universe 与 buy line universe 分离；
- 手动加仓算 `base`，并触发 TP 全开；
- Guardian T 买入不触发 LadderState。

### 4.3 #548 保存门禁

- 视图层和 mjs 构建层双重校验 detail 已加载；
- detail 未加载、加载失败、缺失时不发请求；
- 已加载的 null detail 使用展示默认值并允许保存；
- 保存 payload = 当前展示值，禁止旧默认值覆盖已加载值。

## 5. 验证顺序

1. 后端单测：guardian buy grid、guardian strategy、TPSL、XT ingest、allocation、rebuild/backfill。
2. 前端单测：KlineSlim 保存门禁、null 默认值、拖线/开关/批量操作、双账本展示。
3. 合同/集成测试：Mongo/Redis services、API routes、状态 GET/POST/reset、回填 dry-run/execute。
4. 全量 CI：`docs-current-guard`、`pre-commit`、`pytest`。
5. 回填前生成账本备份；先 dry-run，再 execute。
6. 部署前确认 #548 的前端构建产物与 #549 API 字段一致。

## 6. 交付与部署验收

1. 只在 feature branch 开发，显式 add 本次文件，禁止 `git add -A`。
2. 开 PR，处理全部 review discussion，CI 三绿。
3. 合并 PR 到本地 `main`，确认本地 `main` 与远程 `origin/main` SHA。
4. 推送远程 `main`，等待 101 自动部署完成。
5. 使用 `freshquant-deploy-ops` 对 100/116 执行 `workflow_dispatch` 人工部署。
6. 三台机器分别验收：
   - API `/api/runtime/health/summary`；
   - API/WebUI 容器与挂载；
   - supervisor 程序状态；
   - QFQ 状态；
   - 账本 flatten dry-run/verify；
   - 101 的 must-pool/CLX 相关接口。
7. 部署顺序：回填 `position_type` → 新代码部署并重启 → 非交易时段激活存量 TP → 前端健康检查。
8. 清理临时文件、已合并 feature branch、临时 artifacts；保留正式数据与日志。

## 7. 实施会话验收闸门

- 每完成一个纵向切片，先运行最小相关测试；
- 每次状态机/账本改动必须补正向、重复事件、撤单、部分成交、并发冲突测试；
- 未通过相关测试不得进入下一个大范围切片；
- 未完成 CI、merge、部署和三机健康检查，不报告 Done。
