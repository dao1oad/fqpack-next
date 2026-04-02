# Subject Management Overview Scope Design

**Date:** 2026-03-30

**Goal:** 让 `标的管理` 页左侧 `标的总览` 只显示“持仓股 + must_pool 标的”，不再因为残留的 Guardian / 止盈 / 止损配置把孤儿标的带进总览。

## Current Problem

- `SubjectManagementDashboardService.get_overview()` 目前把 `must_pool`、Guardian 配置、止盈 profile、持仓、止损摘要做并集。
- 这会让不在持仓、也不在 `must_pool` 的历史配置标的继续出现在左侧总览。
- 真实案例：`002594` 当前由 `guardian_buy_grid_configs` 和 `om_takeprofit_profiles` 带进 overview。

## Desired Behavior

- overview 的 symbol seed 只允许来自：
  - `must_pool`
  - 当前持仓聚合
- Guardian、止盈、止损、最近触发事件、仓位上限摘要仍作为补充字段挂到这些 seed 标的上。
- detail 接口保持不变，仍允许读取单标的完整配置与运行态。

## Recommended Approach

采用后端聚合层收口：

1. 在 `SubjectManagementDashboardService.get_overview()` 中只用 `must_pool_rows` 与 `positions` 生成 symbol 集合。
2. 保留对 Guardian / 止盈 / 止损摘要的读取，但仅对 seed symbols 做补充。
3. 新增回归测试，覆盖“只有 Guardian/止盈配置的孤儿标的不会进入 overview”。
4. 同步 `docs/current/modules/subject-management.md`。

## Non-Goals

- 不修改 `/api/subject-management/<symbol>` detail 结构
- 不清理现有 Mongo 历史数据
- 不修改 Guardian / 止盈写入入口
