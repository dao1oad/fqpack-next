# Gantt Postclose Multi-Op Graph Design

## 背景

当前 Dagster 的 `job_gantt_postclose` 只挂了一个 `op_run_gantt_postclose_incremental`。实际盘后链路虽然已经包含：

- XGB 同步
- JYGS 同步
- `plate_reason_daily` 构建
- `gantt_daily` 构建
- `stock_hot_reason_daily` 构建
- `shouban30` 盘后快照构建

但这些步骤都被包在单个 op 里，Dagster UI 只能看到一个节点，无法直接观察每个阶段的执行、失败位置和重试边界。

## 目标

- 保留 `job_gantt_postclose` 现有名称与 schedule。
- 将盘后链路重构为 Dagster UI 可见的多 op graph。
- 保留当前“自动补跑缺失交易日”的增量语义。
- 让每个交易日都能展开为独立的多节点流水线。

## 非目标

- 不修改 `shouban30` 的筛选口径和读模型 schema。
- 不新增单日手动重跑 job 或单阶段专用 job。
- 不修改前端页面、API 路由或 Dagster schedule cron。

## 方案选择

### 方案 1：动态多 op graph

新增一个解析待处理交易日的 op，并把每个 `trade_date` 映射到一条显式子图：

1. `sync_xgb`
2. `sync_jygs`
3. `build_plate_reason`
4. `build_gantt`
5. `build_stock_hot_reason`
6. `build_shouban30`

优点：

- UI 可见真正的阶段节点
- 失败定位和单节点重试更清晰
- 保留当前 backfill 语义

缺点：

- 需要把当前 Python 内部循环改造成 Dagster dynamic graph
- 需要更新 Dagster 相关测试

### 方案 2：静态多 op 串行图

只串单日最新交易日，不做动态映射。

优点：

- 实现最简单

缺点：

- 丢失当前缺口补跑能力

### 方案 3：继续单 op 包裹

只在内部拆 helper，不改 job graph。

优点：

- 改动最小

缺点：

- UI 仍只有一个节点，无法满足需求

### 结论

采用方案 1。

## 目标编排

### Job

保留现有 `job_gantt_postclose`，但 graph 改成：

1. `op_resolve_pending_gantt_trade_dates`
2. `graph_gantt_postclose_for_trade_date.map(...)`

### 单交易日子图

单交易日 graph 内部按固定顺序执行：

1. `op_sync_xgb_history_for_trade_date(trade_date)`
2. `op_sync_jygs_action_for_trade_date(trade_date)`
3. `op_build_plate_reason_daily(xgb_trade_date, jygs_trade_date)`
4. `op_build_gantt_daily(trade_date)`
5. `op_build_stock_hot_reason_daily(trade_date)`
6. `op_build_shouban30_daily(trade_date)`

这里不再沿用“自己解析最新日期”的 daily op 语义。每个阶段都显式接收 `trade_date`，确保 graph 中的数据流是透明的。

## 数据流

### 待处理交易日

`op_resolve_pending_gantt_trade_dates` 复用现有 `resolve_gantt_backfill_trade_dates()`，输出 `DynamicOutput[str]`。

- `mapping_key` 使用安全日期格式，例如 `2026_03_09`
- 当没有待处理交易日时，dynamic map 直接为空

### 每日流水线

每个 `trade_date` 分支内部：

- `sync_xgb` 和 `sync_jygs` 各自消费同一个 `trade_date`
- `build_plate_reason` 验证两个数据源返回日期一致
- 之后的 `build_gantt`、`build_stock_hot_reason`、`build_shouban30` 继续沿用当前构建函数

`shouban30` 的板块黑名单、30m 缠论筛选和四窗口共享缓存逻辑保持不变，仍由 `persist_shouban30_for_date()` 负责。

## 失败语义

- 某个 `trade_date` 的某一阶段失败，只影响该日期分支。
- 其他日期分支仍可以继续执行。
- `xgb/jygs trade_date mismatch` 继续视为硬错误。
- legacy `shouban30` 快照检测与自动重建语义不变。
- 不在大 op 内再包装“部分成功”状态，Dagster 节点成功/失败就是唯一事实来源。

## UI 结果

重构后 Dagster UI 应看到：

- 一个 `resolve_pending_trade_dates`
- 每个交易日展开后的节点链：
  - `sync_xgb`
  - `sync_jygs`
  - `build_plate_reason`
  - `build_gantt`
  - `build_stock_hot_reason`
  - `build_shouban30`

这能直接定位失败阶段，并支持节点级重试。

## 测试策略

重点覆盖：

- 待处理交易日解析逻辑
- 单交易日 graph 的显式依赖关系
- dynamic graph 展开后不再只剩单个 `op_run_gantt_postclose_incremental`
- 现有 `shouban30` 构建与 legacy 检测行为不回退

主要落点：

- `freshquant/tests/test_gantt_dagster_ops.py`

## 验收标准

- Dagster UI 中 `job_gantt_postclose` 不再只有一个顶层业务节点。
- 同一 run 中存在多个待处理交易日时，UI 能展开多条按日期区分的阶段链路。
- 各阶段仍按原顺序执行。
- 现有 `shouban30` 盘后快照构建结果不发生语义回退。
- 相关测试通过。
