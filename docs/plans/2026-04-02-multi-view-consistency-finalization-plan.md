# Multi-View Consistency Finalization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把“仓位与订单多视图一致性检查”完整落地为一套只读、可复用、跨页面统一语义的最终方案，并完成从代码、文档、验证到部署的闭环。

**Architecture:** 以“broker truth / snapshot / ledger / compat projection / evidence”五层模型为核心，在后端提供统一只读 reconciliation contract，在前端以 shared meta 和 shared view-model 消除页面各自翻译状态的漂移。`/position-management` 作为主入口承载完整只读对账，`/order-management`、`/runtime-observability`、`/subject-management`、`/tpsl` 逐步接入同一套状态与契约，而不是重复维护局部规则。

**Tech Stack:** Python, Flask routes, pytest, Vue 3, Element Plus, node:test, Markdown

---

## 范围定义

### 正式真值边界

- `xt_positions`：券商当前仓位真值
- `pm_symbol_position_snapshots`：仓位管理快照真值投影
- `om_position_entries`：系统持仓入口真值
- `om_entry_slices`：entry slice 解释层
- `stock_fills_compat`、`/api/stock_fills`：compat / adapter 只读投影

### 只作为过程证据，不直接要求等于当前仓位

- `xt_orders`
- `xt_trades`
- `om_order_requests`
- `om_orders`
- `om_broker_orders`
- `om_execution_fills`
- `om_trade_facts`

### 统一状态集合

- reconciliation state：`ALIGNED / OBSERVING / AUTO_RECONCILED / BROKEN / DRIFT`
- PM gate state：`ALLOW_OPEN / HOLDING_ONLY / FORCE_PROFIT_REDUCE`
- runtime trace status：`open / completed / failed / stalled / broken`
- order state：`ACCEPTED / QUEUED / SUBMITTING / SUBMITTED / BROKER_BYPASSED / CANCEL_REQUESTED / PARTIAL_FILLED / FILLED / CANCELED / FAILED / REJECTED / INFERRED_PENDING / INFERRED_CONFIRMED / MATCHED / OPEN`

## 当前基线

### 已完成

- `/position-management` 中的对账展示已从“基础配置 + 单标的仓位上限覆盖”抽离为独立只读 `PositionReconciliationPanel`
- 后端已存在 `PositionReconciliationReadService` 与 reconciliation API route
- reconciliation state / audit status / PM gate state 已经 shared meta 化
- `runtimeObservability` 已经接入 shared trace/order state meta
- TPSL 已经复用 reconciliation shared meta

### 尚未完成

- `/order-management` 仍未完全接入 shared order-state meta，存在 raw state 展示残留
- shared meta 文件位置仍偏“页面命名”，还不是最终的领域命名
- 多视图一致性 contract 还没抽成显式的共享定义
- docs 还没把“多视图一致性 contract”写成统一章节
- 本轮还没有完成 PR、merge、deploy、health check

## 最终交付形态

### 用户可见形态

- `/position-management`
  - 继续作为只读一致性检查主入口
  - 显示 broker / snapshot / entry ledger / reconciliation / audit / mismatch evidence
- `/order-management`
  - 订单状态、筛选项、详情标签统一使用 shared order-state meta
- `/runtime-observability`
  - trace status 与 order state 的 label / chip / severity 与其他页面一致
- `/subject-management`
  - 只显示 canonical PM gate label，不再显示 raw code
- `/tpsl`
  - reconciliation state 与其他页面一致

### 工程形态

- 后端有一个显式的“只读一致性 contract”
- 前端有一组按领域命名的 shared meta / view-model
- 所有页面不再各自维护状态中文翻译
- 一致性检查只负责读、解释、跳转，不负责修复

## Task 1: 固化一致性 contract 与领域命名

**Files:**
- Create: `freshquant/position_management/reconciliation_contract.py`
- Create: `freshquant/tests/test_position_reconciliation_contract.py`
- Create: `morningglory/fqwebui/src/views/consistencyContract.mjs`
- Create: `morningglory/fqwebui/src/views/consistencyContract.test.mjs`
- Modify: `docs/current/modules/position-management.md`
- Modify: `docs/current/modules/order-management.md`
- Modify: `docs/current/modules/runtime-observability.md`

**Step 1: 写失败测试，锁定 contract 常量**

- 后端新增 contract test，断言：
  - canonical layer 集合
  - canonical comparison rule 集合
  - reconciliation 5 态
- 前端新增 contract test，断言：
  - 页面展示用的 layer label / rule label / tone 固定

**Step 2: 跑失败测试确认 contract 尚不存在**

Run:

```powershell
py -3.12 -m pytest freshquant/tests/test_position_reconciliation_contract.py -q
node --test D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/consistencyContract.test.mjs
```

Expected: FAIL，提示新模块不存在

**Step 3: 实现最小 contract**

- 后端定义：
  - surface names
  - rule ids
  - rule expected relation
  - read-only guard 注释
- 前端定义：
  - 对应中文 label
  - 展示顺序
  - 说明文案

**Step 4: 再跑测试确认通过**

Run:

```powershell
py -3.12 -m pytest freshquant/tests/test_position_reconciliation_contract.py -q
node --test D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/consistencyContract.test.mjs
```

**Step 5: Commit**

```bash
git add freshquant/position_management/reconciliation_contract.py freshquant/tests/test_position_reconciliation_contract.py morningglory/fqwebui/src/views/consistencyContract.mjs morningglory/fqwebui/src/views/consistencyContract.test.mjs docs/current/modules/position-management.md docs/current/modules/order-management.md docs/current/modules/runtime-observability.md
git commit -m "feat: add multi-view consistency contract"
```

## Task 2: 完成后端 reconciliation read service 的 contract 化

**Files:**
- Modify: `freshquant/position_management/reconciliation_read_service.py`
- Modify: `freshquant/rear/position_management/routes.py`
- Modify: `freshquant/tests/test_position_reconciliation_read_service.py`
- Modify: `freshquant/tests/test_position_management_routes.py`

**Step 1: 写失败测试，锁定 canonical DTO**

新增断言：

- summary 中带 `rule_counts`
- row 中带 `surface_values`
- row 中带 `mismatch_codes`
- row 中带 `rule_results`
- symbol detail 中带 evidence sections

示例结构：

```python
assert row["rule_results"]["R1"]["status"] == "OK"
assert row["surface_values"]["broker"]["quantity"] == 1200
assert row["surface_values"]["entry_ledger"]["quantity"] == 1200
```

**Step 2: 跑测试确认当前 DTO 不完整**

Run:

```powershell
py -3.12 -m pytest freshquant/tests/test_position_reconciliation_read_service.py freshquant/tests/test_position_management_routes.py -q
```

Expected: FAIL，失败点集中在新字段缺失

**Step 3: 做最小实现**

- read service 输出 contract 化 DTO
- route 保持 GET-only
- 不新增任何写入型 action

**Step 4: 再跑测试**

Run:

```powershell
py -3.12 -m pytest freshquant/tests/test_position_reconciliation_read_service.py freshquant/tests/test_position_management_routes.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/position_management/reconciliation_read_service.py freshquant/rear/position_management/routes.py freshquant/tests/test_position_reconciliation_read_service.py freshquant/tests/test_position_management_routes.py
git commit -m "feat: finalize reconciliation read contract"
```

## Task 3: 把 shared meta 从“页面命名”收口到“领域命名”

**Files:**
- Create: `morningglory/fqwebui/src/views/orderStateMeta.mjs`
- Create: `morningglory/fqwebui/src/views/traceStatusMeta.mjs`
- Modify: `morningglory/fqwebui/src/views/runtimeStateMeta.mjs`
- Modify: `morningglory/fqwebui/src/views/runtimeStateMeta.test.mjs`
- Modify: `morningglory/fqwebui/src/views/runtimeOrderTraceSemantic.test.mjs`

**Step 1: 写失败测试，锁定新领域文件出口**

- `getOrderStateMeta` 从 `orderStateMeta.mjs` 导出
- `getTraceStatusMeta` 从 `traceStatusMeta.mjs` 导出
- `runtimeStateMeta.mjs` 只做兼容 re-export，后续可删除

**Step 2: 跑测试确认失败**

Run:

```powershell
node --test D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/runtimeStateMeta.test.mjs D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/runtimeOrderTraceSemantic.test.mjs
```

**Step 3: 迁移实现**

- 把订单状态 meta 移到领域文件
- 把 trace 状态 meta 移到领域文件
- runtime 模块改为消费领域文件

**Step 4: 跑测试**

Run:

```powershell
node --test D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/runtimeStateMeta.test.mjs D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/runtimeOrderTraceSemantic.test.mjs D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/workbenchDesignSystem.test.mjs
```

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/orderStateMeta.mjs morningglory/fqwebui/src/views/traceStatusMeta.mjs morningglory/fqwebui/src/views/runtimeStateMeta.mjs morningglory/fqwebui/src/views/runtimeStateMeta.test.mjs morningglory/fqwebui/src/views/runtimeOrderTraceSemantic.test.mjs
git commit -m "refactor: move shared state meta to domain modules"
```

## Task 4: 完成 `/order-management` 的 shared order-state 收口

**Files:**
- Modify: `morningglory/fqwebui/src/views/orderManagement.mjs`
- Modify: `morningglory/fqwebui/src/views/OrderManagement.vue`
- Modify: `morningglory/fqwebui/src/views/orderManagement.test.mjs`
- Modify: `docs/current/modules/order-management.md`

**Step 1: 写失败测试**

断言：

- filter option 与列表 state label 不再直接显示 raw enum
- detail、stats、timeline 全部复用 shared meta
- unknown state 仍有 muted fallback

**Step 2: 跑测试确认失败**

Run:

```powershell
node --test D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/orderManagement.test.mjs
```

**Step 3: 最小实现**

- `buildOrderRows()` 输出 `state_label / state_chip_variant / state_severity`
- 页面筛选项可保留 raw value，但展示 label
- 详情 badge 和状态卡统一使用 shared meta

**Step 4: 跑测试**

Run:

```powershell
node --test D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/orderManagement.test.mjs D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/workbenchDesignSystem.test.mjs
```

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/orderManagement.mjs morningglory/fqwebui/src/views/OrderManagement.vue morningglory/fqwebui/src/views/orderManagement.test.mjs docs/current/modules/order-management.md
git commit -m "feat: unify order management state semantics"
```

## Task 5: 完成 `PositionReconciliationPanel` 的最终交互形态

**Files:**
- Modify: `morningglory/fqwebui/src/components/position-management/PositionReconciliationPanel.vue`
- Modify: `morningglory/fqwebui/src/views/positionReconciliation.mjs`
- Modify: `morningglory/fqwebui/src/views/positionReconciliation.test.mjs`
- Modify: `morningglory/fqwebui/src/views/positionManagement.test.mjs`

**Step 1: 写失败测试**

断言：

- summary 区显示 rule counts
- 每行支持展开 evidence
- mismatch codes 有中文解释
- 只读 panel 不包含任何写操作按钮

**Step 2: 跑测试确认失败**

Run:

```powershell
node --test D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/positionReconciliation.test.mjs D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/positionManagement.test.mjs
```

**Step 3: 最小实现**

- view-model 补 `rule_results`、`surface_values`、`mismatch_explanations`
- panel 展开区固定显示：
  - broker
  - snapshot
  - entry
  - slice
  - compat
  - stock_fills projection
- 禁止出现“同步 / 修复 / 自动平账”按钮

**Step 4: 跑测试**

Run:

```powershell
node --test D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/positionReconciliation.test.mjs D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/positionManagement.test.mjs D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/workbenchDesignSystem.test.mjs
```

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/components/position-management/PositionReconciliationPanel.vue morningglory/fqwebui/src/views/positionReconciliation.mjs morningglory/fqwebui/src/views/positionReconciliation.test.mjs morningglory/fqwebui/src/views/positionManagement.test.mjs
git commit -m "feat: finalize reconciliation panel evidence view"
```

## Task 6: 完成跨页面状态与跳转一致性

**Files:**
- Modify: `morningglory/fqwebui/src/views/subjectManagement.mjs`
- Modify: `morningglory/fqwebui/src/views/SubjectManagement.vue`
- Modify: `morningglory/fqwebui/src/views/tpslManagement.mjs`
- Modify: `morningglory/fqwebui/src/views/TpslManagement.vue`
- Modify: `morningglory/fqwebui/src/views/runtimeObservability.mjs`
- Modify: `morningglory/fqwebui/src/views/RuntimeObservability.vue`
- Modify: `morningglory/fqwebui/src/views/subjectManagement.test.mjs`
- Modify: `morningglory/fqwebui/src/views/tpslManagement.test.mjs`
- Modify: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`

**Step 1: 写失败测试**

断言：

- Subject/TPSL/Runtime 中同一状态的 label 和 chip 一致
- 相关页面可跳转到 `/position-management` 的 reconciliation browse 状态，或至少保留 query/filter contract

**Step 2: 跑测试确认失败**

Run:

```powershell
node --test D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/subjectManagement.test.mjs D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/tpslManagement.test.mjs D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/runtime-observability.test.mjs
```

Expected: 可能部分因 `vue` 依赖缺失而无法本地跑；若如此，必须补 lightweight semantic tests 并在最终 PR 中依赖 CI 完整验证

**Step 3: 最小实现**

- 统一使用 shared meta 输出 label/chip
- 如做跳转，只允许跳到只读筛选态，不允许触发修复动作

**Step 4: 跑可执行测试**

Run:

```powershell
node --test D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/runtimeOrderTraceSemantic.test.mjs D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/runtimePositionGateSemantic.test.mjs D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/tpslReconciliationState.test.mjs
```

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/subjectManagement.mjs morningglory/fqwebui/src/views/SubjectManagement.vue morningglory/fqwebui/src/views/tpslManagement.mjs morningglory/fqwebui/src/views/TpslManagement.vue morningglory/fqwebui/src/views/runtimeObservability.mjs morningglory/fqwebui/src/views/RuntimeObservability.vue morningglory/fqwebui/src/views/subjectManagement.test.mjs morningglory/fqwebui/src/views/tpslManagement.test.mjs morningglory/fqwebui/src/views/runtime-observability.test.mjs
git commit -m "feat: align cross-view state semantics"
```

## Task 7: 文档收口与运行手册更新

**Files:**
- Modify: `docs/current/modules/position-management.md`
- Modify: `docs/current/modules/order-management.md`
- Modify: `docs/current/modules/subject-management.md`
- Modify: `docs/current/modules/tpsl.md`
- Modify: `docs/current/modules/runtime-observability.md`
- Modify: `docs/current/architecture.md`
- Modify: `docs/current/runtime.md`

**Step 1: 写 docs guard 级检查清单**

文档必须明确：

- 哪些层必须相等
- 哪些层只是过程证据
- 一致性检查只读
- 各页面复用同一套状态语义

**Step 2: 更新文档**

- 增加“多视图一致性 contract”小节
- 加入状态集合与页面复用说明
- 说明 `/position-management` 是主入口

**Step 3: 跑文档相关测试或 guard**

Run:

```powershell
py -3.12 -m pytest freshquant/tests/test_position_management_routes.py freshquant/tests/test_order_management_read_service.py -q
```

如仓库已有 docs guard，本地补跑对应命令。

**Step 4: Commit**

```bash
git add docs/current/modules/position-management.md docs/current/modules/order-management.md docs/current/modules/subject-management.md docs/current/modules/tpsl.md docs/current/modules/runtime-observability.md docs/current/architecture.md docs/current/runtime.md
git commit -m "docs: document multi-view consistency contract"
```

## Task 8: 完整验证、PR、部署与健康检查

**Files:**
- No code changes required

**Step 1: 跑后端验证**

Run:

```powershell
py -3.12 -m pytest freshquant/tests/test_position_reconciliation_read_service.py freshquant/tests/test_position_management_routes.py freshquant/tests/test_position_management_dashboard.py freshquant/tests/test_order_management_read_service.py freshquant/tests/test_order_management_routes.py freshquant/tests/test_tpsl_service.py -q
```

**Step 2: 跑前端轻量验证**

Run:

```powershell
node --test D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/runtimeStateMeta.test.mjs D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/runtimeOrderTraceSemantic.test.mjs D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/positionReconciliation.test.mjs D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/positionManagement.test.mjs D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/orderManagement.test.mjs D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/tpslReconciliationState.test.mjs D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/workbenchDesignSystem.test.mjs
```

**Step 3: 跑前端 build**

Run:

```powershell
cd morningglory/fqwebui
npm run build
```

Expected: PASS  
如果本地缺 `vite` 或 `vue` 依赖，先修复依赖环境，再执行；不能跳过 build 就宣称前端完成。

**Step 4: 提交 PR**

- PR 标题说明：
  - 多视图一致性 contract
  - position reconciliation panel
  - shared state semantics
- PR 正文写清：
  - 背景
  - 目标
  - 范围
  - 非目标
  - 验收标准
  - 部署影响

**Step 5: 合并后部署**

受影响模块：

- `freshquant/position_management/**`
  - 重部署后端
  - 重启 `xt_account_sync.worker`
- `freshquant/order_management/**`
  - 重部署后端/API
  - 必要时重启相关 worker
- `freshquant/tpsl/**`
  - 重启 `tpsl.tick_listener`
- `morningglory/fqwebui/**`
  - 重建并部署 Web UI

**Step 6: 健康检查**

- 打开 `/position-management`
  - 确认对账检查面板可加载
- 打开 `/order-management`
  - 确认状态 label/chip 正确
- 打开 `/runtime-observability`
  - 确认 trace/order 状态 label/chip 正确
- 打开 `/tpsl`、`/subject-management`
  - 确认状态语义未回退为 raw code

**Step 7: Cleanup**

- 删除临时脚本与临时测试产物
- 清理已合并 feature branch
- 保留 `docs/current/**`

## 风险与应对

- 风险 1：shared meta 命名仍带页面色彩
  - 应对：先 contract 化，再迁到领域命名
- 风险 2：订单页和 runtime 页状态集合继续分叉
  - 应对：以 order state meta 为唯一来源，页面禁止自带 label map
- 风险 3：对账面板膨胀成“隐式修复入口”
  - 应对：测试中明确禁止修复按钮和写动作
- 风险 4：前端本地环境缺依赖，导致 build 证据缺失
  - 应对：在 Task 8 前先恢复依赖，不能用“轻量测试通过”替代 build

## 完成标准

- 所有状态 label/chip/severity 只保留一套 shared 来源
- `/position-management` 完整承载只读 reconciliation browse
- `/order-management`、`/runtime-observability`、`/subject-management`、`/tpsl` 的状态语义不再漂移
- docs/current 完整记录一致性 contract
- PR 合并、部署、健康检查完成
