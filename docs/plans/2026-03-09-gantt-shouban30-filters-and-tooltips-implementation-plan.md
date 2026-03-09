# Gantt Shouban30 Filters And Tooltips Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 `/gantt/shouban30` 增加可读性更好的理由悬浮框，以及基于盘后快照的 `融资标的 / 均线附近 / 优质标的` 交集筛选能力。

**Architecture:** 保持 `/gantt/shouban30` 的“只读盘后快照”定位，不新增页面专用路由，不做前端散调。后端在 Dagster 盘后链路中先更新 `quality_stock_universe`，再扩展 `shouban30_stocks` 写入三类筛选标记；前端只消费扩展后的快照字段，并用本地 helper 对当前已加载 stock rows 做交集过滤和板块重算。理由悬浮框统一改为 `el-popover` 卡片式展示。

**Tech Stack:** Python 3.12, Flask, MongoDB, Dagster, Vue 3, Element Plus, Node test runner, pytest

---

### Task 1: 写 RFC 并同步迁移记录

**Files:**
- Create: `docs/rfcs/0026-gantt-shouban30-filters-and-reason-popovers.md`
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`
- Reference: `docs/rfcs/0000-template.md`
- Reference: `docs/plans/2026-03-09-gantt-shouban30-filters-and-tooltips-design.md`

**Step 1: 写 RFC 草稿**

在新 RFC 中明确：

- tooltip 改为 `el-popover`
- 三个筛选条件的最终口径
- 多选取交集
- `quality_stock_universe` 新集合
- `shouban30_stocks` 返回字段扩展
- Dagster 盘后更新链路

**Step 2: 更新迁移进度为 `Review`**

在 `docs/migration/progress.md` 新增 RFC 0026 行，并注明：

- 当前状态：`Review`
- 旧分支来源：`run_xgt_plate_screener_loop.py` 的固定 `block_names`
- 下一步：实现 `quality_stock_universe`、扩展 `shouban30` 快照、重做 tooltip

**Step 3: 预登记 breaking change**

在 `docs/migration/breaking-changes.md` 追加 RFC 0026 的预期影响：

- `/api/gantt/shouban30/stocks` 返回新增筛选字段
- 页面筛选语义改变

**Step 4: 做最小文档校验**

Run: `git diff --check`

Expected: 无空白错误

**Step 5: Commit**

```bash
git add docs/rfcs/0026-gantt-shouban30-filters-and-reason-popovers.md docs/migration/progress.md docs/migration/breaking-changes.md
git commit -m "docs: 增补 shouban30 筛选与悬浮框 RFC"
```

**Step 6: 人工评审关口**

- RFC 状态未到 `Approved` 前，不开始任何代码实现。
- 评审通过后，在同一提交把 `progress.md` 状态更新到 `Approved`，再进入 Task 2。

### Task 2: 新增优质标的基础集合与测试

**Files:**
- Create: `freshquant/data/quality_stock_universe.py`
- Create: `freshquant/tests/test_quality_stock_universe.py`
- Reference: `freshquant/quantaxis/qafetch/qaquery_advance.py`
- Reference: `D:\\fqpack\\config\\complex_screening_xgt.yaml`

**Step 1: 写失败测试**

覆盖以下行为：

- 固定 `block_names` 常量完整且顺序稳定
- 从 `stock_block` 数据聚合出去重后的 `code6 -> block_names`
- 空数据时返回空集
- `source_version` 与 `updated_at` 正确写入

示例断言：

```python
def test_refresh_quality_stock_universe_dedupes_codes_and_keeps_block_names():
    result = refresh_quality_stock_universe(...)
    assert result["count"] == 2
    assert lookup["000001"]["block_names"] == ["沪深300", "高股息股"]
```

**Step 2: 跑测试确认失败**

Run: `py -3.12 -m pytest freshquant/tests/test_quality_stock_universe.py -q`

Expected: FAIL，提示模块或函数不存在

**Step 3: 写最小实现**

在 `freshquant/data/quality_stock_universe.py` 提供：

- `QUALITY_STOCK_BLOCK_NAMES`
- `QUALITY_STOCK_SOURCE_VERSION`
- `refresh_quality_stock_universe(...)`
- `load_quality_stock_lookup(...)`

实现要求：

- 直接从当前仓库可访问的 `stock_block` 数据构建
- 同一 `code6` 去重
- 保留命中的 `block_names`
- 覆盖写入 `quality_stock_universe`

**Step 4: 跑测试确认通过**

Run: `py -3.12 -m pytest freshquant/tests/test_quality_stock_universe.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/data/quality_stock_universe.py freshquant/tests/test_quality_stock_universe.py
git commit -m "feat: 新增优质标的基础集合构建"
```

### Task 3: 把优质标的更新接入 Dagster 盘后链路

**Files:**
- Modify: `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`
- Modify: `morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py`
- Modify: `freshquant/tests/test_gantt_dagster_ops.py`
- Modify: `docs/migration/progress.md`

**Step 1: 写失败测试**

补两类测试：

- `job_gantt_postclose` 的单日依赖链中，`refresh_quality_stock_universe` 在 `op_build_shouban30_daily` 之前
- 该更新 op 被执行一次，不随四个窗口重复跑

示例断言：

```python
assert dependency_map["op_build_shouban30_daily"] == {"op_refresh_quality_stock_universe_daily": DependencyDefinition()}
```

**Step 2: 跑 Dagster 测试确认失败**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_dagster_ops.py -q`

Expected: FAIL，节点名或依赖图不匹配

**Step 3: 写最小实现**

在 `gantt.py` 中：

- 新增 `op_refresh_quality_stock_universe_daily(context, trade_date)`
- 在单日 graph 中把它串到 `op_build_shouban30_daily` 之前
- 保持 `job_gantt_postclose` 名称和 schedule 不变

**Step 4: 跑聚焦测试确认通过**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_dagster_ops.py -q`

Expected: PASS

**Step 5: 同步进度到 `Implementing`**

在 `docs/migration/progress.md` 中将 RFC 0026 更新为 `Implementing`，并注明：

- 优质标的基础集合与 Dagster 链路已接通
- 下一步进入 `shouban30` 快照扩展与前端消费

**Step 6: Commit**

```bash
git add morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py freshquant/tests/test_gantt_dagster_ops.py docs/migration/progress.md
git commit -m "feat: 接入 shouban30 优质标的盘后更新"
```

### Task 4: 扩展 `shouban30` 快照写入三类筛选字段

**Files:**
- Modify: `freshquant/data/gantt_readmodel.py`
- Modify: `freshquant/rear/gantt/routes.py`
- Modify: `freshquant/tests/test_gantt_readmodel.py`
- Modify: `freshquant/tests/test_gantt_routes.py`
- Reference: `freshquant/order_management/credit_subjects/repository.py`
- Reference: `freshquant/KlineDataTool.py`

**Step 1: 写失败测试**

在 `test_gantt_readmodel.py` 先覆盖：

- `is_credit_subject` 读取 `om_credit_subjects`
- `near_long_term_ma_passed` 严格按 `0%~3%` 判定
- `near_long_term_ma_basis` 正确落值
- `is_quality_subject` 命中基础集合
- `credit_subject_snapshot_ready / quality_subject_snapshot_ready` 在来源缺失时为 `false`

在 `test_gantt_routes.py` 覆盖：

- `/api/gantt/shouban30/stocks` 返回新增字段

示例断言：

```python
assert row["near_long_term_ma_passed"] is True
assert row["ma250_distance_pct"] == 1.8
assert row["is_quality_subject"] is True
```

**Step 2: 跑聚焦测试确认失败**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py -q`

Expected: FAIL，缺字段或口径不匹配

**Step 3: 写最小实现**

在 `gantt_readmodel.py` 中：

- 增加读取信用标的 lookup 的 helper
- 增加读取 `quality_stock_universe` lookup 的 helper
- 增加日线长均线计算 helper
- 以 `code6 + as_of_date` 为键增加长均线结果缓存，避免四窗口重复算
- 将三类筛选字段写入 `shouban30_stocks`

路由层只透传新增字段，不新增 query 参数。

**Step 4: 跑聚焦测试确认通过**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/data/gantt_readmodel.py freshquant/rear/gantt/routes.py freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py
git commit -m "feat: 扩展 shouban30 筛选快照字段"
```

### Task 5: 把前端筛选逻辑拆成独立 helper，并先做交集测试

**Files:**
- Create: `morningglory/fqwebui/src/views/shouban30StockFilters.mjs`
- Create: `morningglory/fqwebui/src/views/shouban30StockFilters.test.mjs`
- Modify: `morningglory/fqwebui/src/views/shouban30Aggregation.mjs`
- Modify: `morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs`

**Step 1: 写失败测试**

覆盖：

- 单个按钮过滤
- 多按钮取交集
- 全部取消回到原始缠论通过集合
- 基于筛选后的 stock rows 重算板块列表与数量
- `agg` 视图对筛选后的结果仍能正确聚合

示例断言：

```javascript
assert.deepEqual(
  filterStocksByExtraFlags(rows, ['credit', 'quality']).map((row) => row.code6),
  ['000001']
)
```

**Step 2: 跑前端聚焦测试确认失败**

Run: `node --test src/views/shouban30StockFilters.test.mjs src/views/shouban30Aggregation.test.mjs`

Expected: FAIL，helper 不存在或交集逻辑不正确

**Step 3: 写最小实现**

在新 helper 中提供：

- `EXTRA_FILTER_OPTIONS`
- `toggleExtraFilter()`
- `filterStocksByExtraFlags()`
- `rebuildPlatesFromFilteredStocks()`

要求：

- 多选取交集
- 只基于 `shouban30_stocks` 已有字段判断
- 不引入新的 HTTP 请求

**Step 4: 跑测试确认通过**

Run: `node --test src/views/shouban30StockFilters.test.mjs src/views/shouban30Aggregation.test.mjs`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/shouban30StockFilters.mjs morningglory/fqwebui/src/views/shouban30StockFilters.test.mjs morningglory/fqwebui/src/views/shouban30Aggregation.mjs morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs
git commit -m "feat: 抽离 shouban30 额外筛选 helper"
```

### Task 6: 重做理由悬浮框并接入筛选按钮

**Files:**
- Create: `morningglory/fqwebui/src/views/components/Shouban30ReasonPopover.vue`
- Modify: `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`
- Modify: `morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs`
- Modify: `morningglory/fqwebui/src/views/shouban30StockFilters.test.mjs`
- Reference: `morningglory/fqwebui/src/views/KlineSlim.vue`

**Step 1: 写失败测试**

覆盖：

- 左侧板块理由、中间最近理由、右侧详情理由不再依赖 `show-overflow-tooltip`
- 筛选按钮可多选、可取消
- 当前板块在筛选后为空时自动切换
- 全空时展示正确空态

**Step 2: 运行前端聚焦测试确认失败**

Run: `node --test src/views/shouban30ChanlunFilter.test.mjs src/views/shouban30StockFilters.test.mjs`

Expected: FAIL，页面仍使用旧 tooltip 或筛选状态未接入

**Step 3: 写最小实现**

实现点：

- 新建通用 `Shouban30ReasonPopover.vue`
- 在页面中三处理由列接入该组件
- 在左侧控制区加入三枚筛选按钮
- 用 `shouban30StockFilters.mjs` 做交集过滤与板块重算
- 保持页面继续只消费 `/api/gantt/shouban30/*`

**Step 4: 跑前端聚焦测试确认通过**

Run: `node --test src/views/shouban30ChanlunFilter.test.mjs src/views/shouban30StockFilters.test.mjs src/views/shouban30Aggregation.test.mjs`

Expected: PASS

**Step 5: 跑前端构建**

Run: `npm run build`

Workdir: `morningglory/fqwebui`

Expected: BUILD SUCCESS，仅允许保留现有已知 warning

**Step 6: Commit**

```bash
git add morningglory/fqwebui/src/views/components/Shouban30ReasonPopover.vue morningglory/fqwebui/src/views/GanttShouban30Phase1.vue morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs morningglory/fqwebui/src/views/shouban30StockFilters.test.mjs morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs
git commit -m "feat: 重做 shouban30 理由悬浮框与额外筛选"
```

### Task 7: 全链路验证、迁移文档收尾与完成提交

**Files:**
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`
- Optional modify: `docs/agent/项目目标与代码现状调研.md`（仅在需要补入口说明时）

**Step 1: 跑后端测试**

Run:

```bash
py -3.12 -m pytest freshquant/tests/test_quality_stock_universe.py freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py freshquant/tests/test_gantt_dagster_ops.py -q
```

Expected: PASS

**Step 2: 跑前端测试与构建**

Run:

```bash
node --test src/views/shouban30Aggregation.test.mjs src/views/shouban30ChanlunFilter.test.mjs src/views/shouban30StockFilters.test.mjs
npm run build
```

Workdir: `morningglory/fqwebui`

Expected: PASS

**Step 3: 跑格式与最小治理校验**

Run:

```bash
py -3.12 -m pre_commit run --show-diff-on-failure --color=always --files docs/rfcs/0026-gantt-shouban30-filters-and-reason-popovers.md docs/migration/progress.md docs/migration/breaking-changes.md freshquant/data/quality_stock_universe.py freshquant/data/gantt_readmodel.py freshquant/rear/gantt/routes.py morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py morningglory/fqwebui/src/views/GanttShouban30Phase1.vue morningglory/fqwebui/src/views/components/Shouban30ReasonPopover.vue
```

Expected: PASS

**Step 4: 更新迁移记录为 `Done`**

在 `docs/migration/progress.md` 与 `docs/migration/breaking-changes.md` 中补齐：

- RFC 0026 状态改为 `Done`
- 本轮新增字段、页面行为变化与迁移步骤

**Step 5: 最终 Commit**

```bash
git add docs/migration/progress.md docs/migration/breaking-changes.md
git commit -m "docs: 收尾 shouban30 筛选与悬浮框迁移记录"
```

**Step 6: 请求代码评审**

使用 `@requesting-code-review` 进行一次 review 准备，再决定是否发 PR。
