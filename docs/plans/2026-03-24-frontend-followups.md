# Frontend Followups Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 完成一轮多页面密度与交互后续修复，收口 `kline-slim / order-management / position-management / subject-management / tpsl / runtime-observability` 的已确认问题。

**Architecture:** 以前端页面壳子不再调整为前提，本轮只做页面级信息密度和交互收口，同时补两处后端真 bug。所有行为改动都先补失败测试，再写最小实现，最后同步更新 `docs/current/**`。

**Tech Stack:** Vue 3、Element Plus、Node built-in test、Python service layer、Flask API backend

---

### Task 1: 建立当前失败基线

**Files:**
- Test: `morningglory/fqwebui/src/views/klineSlim.test.mjs`
- Test: `morningglory/fqwebui/src/views/orderManagement.test.mjs`
- Test: `morningglory/fqwebui/src/views/position-management.test.mjs`
- Test: `morningglory/fqwebui/src/views/subjectManagement.test.mjs`
- Test: `morningglory/fqwebui/src/views/tpslManagement.test.mjs`
- Test: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`

**Step 1: 为六个问题补失败断言**

- `klineSlim.test.mjs`：
  - 断言基础配置区不再出现硬编码 `must_pool`
  - 断言仓位上限区只保留当前生效值 / 市值 / 设置框 / 买入状态
- `orderManagement.test.mjs`：
  - 断言高级筛选按钮存在，长筛选区默认折叠
- `position-management.test.mjs`：
  - 断言“规则矩阵”出现在“参数 inventory”之前
  - 断言 symbol-limit ledger 的“推断仓位 / stock_fills仓位”列宽已放大
- `subjectManagement.test.mjs`：
  - 断言 overview 在 `symbol_limit_loader` 抛异常时仍返回 rows
- `tpslManagement.test.mjs`：
  - 断言 `external_inferred` stock fill 会显示非空方向文案
  - 断言“原始/剩余”列宽已放大
- `runtime-observability.test.mjs`：
  - 断言组件切换入口不会被默认 sidebar 回退逻辑覆盖
  - 断言点击组件卡片时立即切到 `events`

**Step 2: 运行失败测试**

Run:

```powershell
node --test morningglory/fqwebui/src/views/klineSlim.test.mjs morningglory/fqwebui/src/views/orderManagement.test.mjs morningglory/fqwebui/src/views/position-management.test.mjs morningglory/fqwebui/src/views/subjectManagement.test.mjs morningglory/fqwebui/src/views/tpslManagement.test.mjs morningglory/fqwebui/src/views/runtime-observability.test.mjs
```

Expected: 新增断言失败，且失败点对应上述目标行为。

### Task 2: 修 `kline-slim` 信息密度

**Files:**
- Modify: `morningglory/fqwebui/src/views/KlineSlim.vue`
- Test: `morningglory/fqwebui/src/views/klineSlim.test.mjs`

**Step 1: 写最小实现**

- 去掉基础配置标题右侧的硬编码说明字。
- 精简“单标的仓位上限”展示块与辅助文案，只保留当前生效值、市值、设置框、买入状态。

**Step 2: 跑单测**

Run:

```powershell
node --test morningglory/fqwebui/src/views/klineSlim.test.mjs
```

Expected: PASS

### Task 3: 收口 `order-management` 高级筛选

**Files:**
- Modify: `morningglory/fqwebui/src/views/OrderManagement.vue`
- Test: `morningglory/fqwebui/src/views/orderManagement.test.mjs`

**Step 1: 写最小实现**

- 默认只显示统计、核心操作和“高级筛选”按钮。
- 将长筛选区放入折叠面板或条件渲染区域。
- 保持 active chips 与刷新逻辑不变。

**Step 2: 跑单测**

Run:

```powershell
node --test morningglory/fqwebui/src/views/orderManagement.test.mjs
```

Expected: PASS

### Task 4: 收口 `position-management`

**Files:**
- Modify: `morningglory/fqwebui/src/views/PositionManagement.vue`
- Test: `morningglory/fqwebui/src/views/position-management.test.mjs`

**Step 1: 写最小实现**

- 压缩“当前仓位状态”的卡片/表格间距和布局。
- 把“规则矩阵”模块移动到“参数 inventory”之前。
- 调整“推断仓位 / stock_fills仓位”列宽。

**Step 2: 跑单测**

Run:

```powershell
node --test morningglory/fqwebui/src/views/position-management.test.mjs
```

Expected: PASS

### Task 5: 修 `subject-management` 500

**Files:**
- Modify: `freshquant/subject_management/dashboard_service.py`
- Test: `morningglory/fqwebui/src/views/subjectManagement.test.mjs`

**Step 1: 写最小实现**

- 对 `symbol_limit_loader(symbol)` 的异常做兜底。
- 为未被 position-management 追踪的 symbol 返回空/标记化 summary，而不是整页失败。

**Step 2: 跑对应测试与脚本验证**

Run:

```powershell
node --test morningglory/fqwebui/src/views/subjectManagement.test.mjs
```

Run:

```powershell
@'
from freshquant.subject_management.dashboard_service import SubjectManagementDashboardService
rows = SubjectManagementDashboardService().get_overview()
print(len(rows))
'@ | .venv\Scripts\python.exe -
```

Expected: 测试通过；脚本不再抛 `ValueError("symbol is not tracked by holdings or pools")`

### Task 6: 修 `tpsl` 方向列和窄列

**Files:**
- Modify: `freshquant/tpsl/management_service.py`
- Modify: `morningglory/fqwebui/src/views/tpslManagement.mjs`
- Modify: `morningglory/fqwebui/src/views/TpslManagement.vue`
- Test: `morningglory/fqwebui/src/views/tpslManagement.test.mjs`

**Step 1: 写最小实现**

- 在 `stock_fills` 归一化阶段补一个前端可消费的方向显示字段：
  - 有 `op` 时沿用真实方向
  - `source=external_inferred` 时显示 `推断持仓`
- 扩大“原始/剩余”列宽。

**Step 2: 跑单测与样本脚本**

Run:

```powershell
node --test morningglory/fqwebui/src/views/tpslManagement.test.mjs
```

Run:

```powershell
@'
from freshquant.tpsl.management_service import TpslManagementService
detail = TpslManagementService().get_symbol_detail("512000")
print(detail["stock_fills"][0])
'@ | .venv\Scripts\python.exe -
```

Expected: 测试通过；样本输出中存在非空方向展示字段

### Task 7: 修 `runtime-observability` 组件切换与交互阻尼

**Files:**
- Modify: `morningglory/fqwebui/src/views/runtimeObservability.mjs`
- Modify: `morningglory/fqwebui/src/views/RuntimeObservability.vue`
- Test: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`

**Step 1: 写最小实现**

- 收口“组件切换”到单一入口，点击时先切 view 再刷新 events。
- 防止 `componentSidebarItems` 的默认回填逻辑覆盖用户刚选择的组件。
- 减少 sidebar 切换时的整页级派生重算。

**Step 2: 跑单测**

Run:

```powershell
node --test morningglory/fqwebui/src/views/runtime-observability.test.mjs
```

Expected: PASS

### Task 8: 运行整体验证

**Files:**
- Verify: `morningglory/fqwebui/src/views/*.test.mjs`
- Verify: `morningglory/fqwebui/src/views/*.vue`
- Verify: `freshquant/subject_management/dashboard_service.py`
- Verify: `freshquant/tpsl/management_service.py`

**Step 1: 跑本轮相关测试集**

Run:

```powershell
node --test morningglory/fqwebui/src/views/klineSlim.test.mjs morningglory/fqwebui/src/views/orderManagement.test.mjs morningglory/fqwebui/src/views/position-management.test.mjs morningglory/fqwebui/src/views/subjectManagement.test.mjs morningglory/fqwebui/src/views/tpslManagement.test.mjs morningglory/fqwebui/src/views/runtime-observability.test.mjs morningglory/fqwebui/src/views/KlineSlim.layout.test.mjs
```

**Step 2: 跑前端构建**

Run:

```powershell
cd morningglory/fqwebui
pnpm build
```

**Step 3: 跑后端脚本验证**

Run:

```powershell
@'
from freshquant.subject_management.dashboard_service import SubjectManagementDashboardService
from freshquant.tpsl.management_service import TpslManagementService
print("subject_overview", len(SubjectManagementDashboardService().get_overview()))
print("tpsl_detail", TpslManagementService().get_symbol_detail("512000").get("symbol"))
'@ | .venv\Scripts\python.exe -
```

Expected: 所有命令 exit 0

### Task 9: 同步当前文档

**Files:**
- Modify: `docs/current/modules/subject-management.md`
- Modify: `docs/current/modules/tpsl.md`
- Modify: `docs/current/modules/runtime-observability.md`

**Step 1: 更新当前事实**

- `subject-management` 记录 overview 的 position-limit 兜底行为
- `tpsl` 记录 `external_inferred` 的方向展示语义
- `runtime-observability` 记录 sidebar 组件切换行为

**Step 2: 再跑验证命令**

Run:

```powershell
node --test morningglory/fqwebui/src/views/subjectManagement.test.mjs morningglory/fqwebui/src/views/tpslManagement.test.mjs morningglory/fqwebui/src/views/runtime-observability.test.mjs
```

Expected: PASS
