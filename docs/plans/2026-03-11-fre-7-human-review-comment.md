# FRE-7 Human Review Comment Packet

Issue is ready for Human Review.

## Deliverables

- RFC: `docs/rfcs/0031-gantt-shouban30-pool-persistence-and-blk-sync.md`
- Design: `docs/plans/2026-03-11-gantt-shouban30-pool-persistence-design.md`
- Implementation plan: `docs/plans/2026-03-11-gantt-shouban30-pool-persistence-implementation-plan.md`
- Task checklist: `docs/plans/2026-03-11-gantt-shouban30-pool-persistence-implementation-plan.md` 的 `Task Checklist`
- Progress update: `docs/migration/progress.md`

## Scope Summary

- In scope: `/gantt/shouban30` 的“筛选结果保存到预选池 / 单板块保存到预选池 / pre_pool 与 stockpools 标签页 / pre_pool -> stock_pools -> must_pool / 30RYZT.blk 同步”。
- Out of scope: 恢复旧分支独立集合 `sanshi_zhangting_pro / sanshi_zhangting_watchlist`、导出/SSE/重算链路、全站股票池管理页重构、must_pool 参数弹窗。

## Key Risks

- 当前仓 `stock_pre_pools / stock_pools` 是共享集合；如果直接接管整张集合，会误删其他来源的数据。
- `30RYZT.blk` 依赖 `TDX_HOME`；运行环境缺失该变量时，保存动作需要显式失败而不是静默跳过。
- `加入 must_pool` 沿用旧页默认参数 `0.1 / 50000 / 50000 / forever=true / category=三十涨停Pro`，若用户不接受，需要在评审阶段改口径。

## Explicit Review Items

- 是否接受本 RFC 的默认边界：`/gantt/shouban30` 只管理 `stock_pre_pools / stock_pools` 中的 `三十涨停Pro预选 / 三十涨停Pro自选` 专用分类，而不是覆盖整张共享集合。
- 是否接受 `30RYZT.blk` 只镜像 `三十涨停Pro预选`，不镜像整张 `stock_pre_pools`。
- 是否接受 `加入 must_pool` 沿用旧页默认参数，不新增弹窗。

## Approval Instruction

- 如果认可本设计，请把 Linear issue 从 `Human Review` 移到 `In Progress`。
- 如果需要调整，请直接在 Linear 评论里指出：
  - 是否要改成“覆盖整张 `stock_pre_pools`”
  - 是否要让 `pre_pool / stockpools` 标签页展示全量集合而不是专用分类
  - 是否要调整 `must_pool` 默认参数
