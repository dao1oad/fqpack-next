# FRE-6 Human Review Comment Packet

Issue is ready for Human Review.

## Deliverables

- RFC: `docs/rfcs/0029-kline-slim-zhongshu-ghosting-fix.md`
- Implementation plan: `docs/plans/2026-03-11-kline-slim-zhongshu-ghosting-implementation-plan.md`
- Task checklist: `docs/plans/2026-03-11-kline-slim-zhongshu-ghosting-implementation-plan.md` 的 `Task Checklist`
- Progress update: `docs/migration/progress.md`

## Scope Summary

- In scope: `KlineSlim` 在 `symbol / period / endDate` 结构性切换时的显式清图语义；`中枢 / 段中枢 / 高级段中枢` 残影回归；浏览器自动化主验收路径。
- Out of scope: 后端 API、fullcalc payload、自绘 renderer 重写、部署与运行面操作。

## Key Risks

- 结构性切换时显式 `chart.clear()` 会重置切标的/切主周期时的视口。
- 浏览器自动化主验收依赖 deterministic stub 数据；测试数据若不稳定，截图哈希会抖动。
- 如果 controller 清图仍不足以收敛残影，后续可能需要单独再开 renderer 层修复，而不是在本票里临时扩大范围。

## Approval Instruction

- 如果认可本设计，请把 Linear issue 从 `Human Review` 移到 `In Progress`。
- 如果需要调整，请直接在 Linear 评论里指出：
  - 是否接受“结构性切换重置视口”
  - 是否接受“浏览器自动化主测重复切换 symbol”
  - 是否要求本票同时覆盖 period/legend 组合回归
