# Gantt Postclose Multi-Op Graph Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 `job_gantt_postclose` 从单个包裹式 op 重构为 Dagster UI 可见的多 op dynamic graph，同时保持现有增量补跑语义和 `shouban30` 盘后快照行为不变。

**Architecture:** 在 Dagster 层新增一个“解析待处理交易日”的 dynamic output op，并把单交易日盘后流水线建成显式 graph。所有业务构建逻辑继续复用现有读模型函数，重构重点只放在编排、输入输出和测试上。

**Tech Stack:** Python 3.12, Dagster, pytest, Mongo-backed readmodel helpers

---

### Task 1: 为多 op graph 先定义失败测试

**Files:**
- Modify: `freshquant/tests/test_gantt_dagster_ops.py`
- Read: `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`
- Read: `morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py`

**Step 1: 写失败测试，约束新的 graph 形状**

在 `freshquant/tests/test_gantt_dagster_ops.py` 增加测试，至少覆盖：

- `job_gantt_postclose` 中不再包含 `op_run_gantt_postclose_incremental`
- graph 中包含 `resolve pending dates` 节点
- graph 中包含 `sync_xgb`、`sync_jygs`、`build_plate_reason`、`build_gantt`、`build_stock_hot_reason`、`build_shouban30`

建议断言：

```python
def test_job_gantt_postclose_uses_multi_op_graph():
    node_names = {node.name for node in job_gantt_postclose.graph.node_defs}
    assert "op_run_gantt_postclose_incremental" not in node_names
    assert "op_resolve_pending_gantt_trade_dates" in node_names
```

**Step 2: 跑测试确认红灯**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_dagster_ops.py -k "multi_op_graph or resolve_pending" -q`

Expected: FAIL，说明当前 job 仍是单 op 编排。

**Step 3: 最小实现：补充 graph 定义骨架**

在 `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py` 和 `morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py` 中：

- 新增 `op_resolve_pending_gantt_trade_dates`
- 新增单交易日 graph 骨架
- 先把 job 接到新的 graph 上

**Step 4: 重新跑测试确认转绿**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_dagster_ops.py -k "multi_op_graph or resolve_pending" -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/tests/test_gantt_dagster_ops.py morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py
git commit -m "test: 定义 gantt 多 op graph 编排"
```

### Task 2: 把待处理交易日解析改成 DynamicOutput

**Files:**
- Modify: `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`
- Test: `freshquant/tests/test_gantt_dagster_ops.py`

**Step 1: 写失败测试，约束 dynamic output 语义**

增加测试，mock `resolve_gantt_backfill_trade_dates()` 返回多个日期，并验证：

- `op_resolve_pending_gantt_trade_dates` 产出对应数量的动态项
- `mapping_key` 使用安全日期格式，例如 `2026_03_09`

**Step 2: 跑测试确认红灯**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_dagster_ops.py -k "dynamic_output or mapping_key" -q`

Expected: FAIL

**Step 3: 最小实现**

在 `ops/gantt.py` 中：

- 引入 `DynamicOut`、`DynamicOutput`
- 实现 `op_resolve_pending_gantt_trade_dates()`
- 抽一个小 helper 生成 `mapping_key`

**Step 4: 重新跑测试确认转绿**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_dagster_ops.py -k "dynamic_output or mapping_key" -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/tests/test_gantt_dagster_ops.py morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py
git commit -m "feat: 输出 gantt 待处理交易日动态映射"
```

### Task 3: 将 daily op 改成显式 trade_date 输入

**Files:**
- Modify: `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`
- Test: `freshquant/tests/test_gantt_dagster_ops.py`

**Step 1: 写失败测试，约束 op 不再隐式解析日期**

增加测试，直接调用：

- `op_sync_xgb_history_for_trade_date`
- `op_sync_jygs_action_for_trade_date`

验证它们显式消费传入的 `trade_date`，不再调用 `_resolve_trade_date()`。

**Step 2: 跑测试确认红灯**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_dagster_ops.py -k "for_trade_date" -q`

Expected: FAIL

**Step 3: 最小实现**

在 `ops/gantt.py` 中：

- 新增或重命名为 `op_sync_xgb_history_for_trade_date(context, trade_date)`
- 新增或重命名为 `op_sync_jygs_action_for_trade_date(context, trade_date)`
- 保留 `op_build_plate_reason_daily / op_build_gantt_daily / op_build_stock_hot_reason_daily / op_build_shouban30_daily`

**Step 4: 重新跑测试确认转绿**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_dagster_ops.py -k "for_trade_date" -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/tests/test_gantt_dagster_ops.py morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py
git commit -m "refactor: 显式传递 gantt trade_date"
```

### Task 4: 连接单交易日 graph

**Files:**
- Modify: `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`
- Modify: `morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py`
- Test: `freshquant/tests/test_gantt_dagster_ops.py`

**Step 1: 写失败测试，约束节点顺序和依赖**

增加测试，至少验证：

- `build_plate_reason` 依赖 `sync_xgb` 和 `sync_jygs`
- `build_gantt` 依赖 `build_plate_reason`
- `build_stock_hot_reason` 依赖 `build_gantt`
- `build_shouban30` 依赖 `build_stock_hot_reason`

**Step 2: 跑测试确认红灯**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_dagster_ops.py -k "node_dependency or single_trade_date_graph" -q`

Expected: FAIL

**Step 3: 最小实现**

在 `ops/gantt.py` 中定义单交易日 graph，例如：

```python
@graph
def graph_gantt_postclose_for_trade_date(trade_date):
    xgb_trade_date = op_sync_xgb_history_for_trade_date(trade_date)
    jygs_trade_date = op_sync_jygs_action_for_trade_date(trade_date)
    agreed_trade_date = op_build_plate_reason_daily(xgb_trade_date, jygs_trade_date)
    gantt_trade_date = op_build_gantt_daily(agreed_trade_date)
    hot_reason_trade_date = op_build_stock_hot_reason_daily(gantt_trade_date)
    op_build_shouban30_daily(hot_reason_trade_date)
```

然后在 `jobs/gantt.py` 把 job 接到 dynamic map。

**Step 4: 重新跑测试确认转绿**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_dagster_ops.py -k "node_dependency or single_trade_date_graph" -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/tests/test_gantt_dagster_ops.py morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py
git commit -m "feat: 连接 gantt 单交易日多 op 流水线"
```

### Task 5: 收敛旧入口并保留辅助函数

**Files:**
- Modify: `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`
- Test: `freshquant/tests/test_gantt_dagster_ops.py`

**Step 1: 写失败测试，约束 job 不再依赖旧的大 op 入口**

增加测试，确认：

- `op_run_gantt_postclose_incremental` 不再被 job graph 引用
- 保留的 helper 不影响现有 backfill 规则测试

**Step 2: 跑测试确认红灯**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_dagster_ops.py -k "legacy_job_entry" -q`

Expected: FAIL

**Step 3: 最小实现**

按实现结果决定：

- 删除 `op_run_gantt_postclose_incremental`
- 或保留为内部兼容 helper，但从 job graph 中移除

同时清理无用 `_resolve_trade_date()` 分支，避免产生双入口语义。

**Step 4: 重新跑测试确认转绿**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_dagster_ops.py -k "legacy_job_entry" -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/tests/test_gantt_dagster_ops.py morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py
git commit -m "refactor: 移除 gantt 单 op job 入口"
```

### Task 6: 回归验证与文档更新

**Files:**
- Modify: `docs/migration/progress.md`
- Verify: `freshquant/tests/test_gantt_dagster_ops.py`
- Verify: `freshquant/tests/test_gantt_readmodel.py`
- Verify: `freshquant/tests/test_gantt_routes.py`

**Step 1: 更新迁移进度**

在 `docs/migration/progress.md` 追加简短记录：

- `job_gantt_postclose` 已改为多 op dynamic graph
- 目的：提升 Dagster UI 可观察性和阶段级重试能力

**Step 2: 跑完整相关测试**

Run:

```bash
py -3.12 -m pytest freshquant/tests/test_gantt_dagster_ops.py freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py -q
```

Expected: 全绿

**Step 3: 如有需要跑格式化或 lint**

Run:

```bash
py -3.12 -m pre_commit run --files morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py freshquant/tests/test_gantt_dagster_ops.py docs/migration/progress.md
```

Expected: 全绿

**Step 4: 最终 Commit**

```bash
git add docs/migration/progress.md morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py freshquant/tests/test_gantt_dagster_ops.py
git commit -m "feat: 重构 gantt 盘后多 op graph"
```
