# Subject Entry Slices Design

**Context**

- `subject-management` 和 `kline-slim` 当前展示的是 open entry 视图，不是原始买单。
- buy-side 已经按保守规则聚合为 `buy_cluster / broker_execution_cluster` entry。
- entry slice 真值已经落在 `om_entry_slices`，但前端缺少直接校验入口。
- “剩余市值”当前由前端按 `runtime_summary.avg_price * remaining_quantity` 计算，语义更接近成本估算，不是市值。

**Goal**

- 在 `subject-management` 的“按持仓入口止损”区域增加 entry 级切片查看能力，直接校验聚合 entry 的成员与 slices。
- 把“剩余市值”统一改为“最新价 * 剩余数量”，取不到最新价时回退到 `avg_price * remaining_quantity`。
- `kline-slim` 与 `subject-management` 继续共用同一套 entry 摘要字段，避免页面口径再次漂移。

**Recommended Approach**

- 主入口放在 `subject-management`，因为这里本来就是 entry 级止损配置页，用户已经在按 entry 操作。
- 每个 entry 行增加折叠区，分两块展示：
  - 聚合成员：原始 broker order / trade time / quantity / entry price
  - slices：`entry_slice_id / guardian_price / original_quantity / remaining_quantity / remaining_amount / status`
- `kline-slim` 保持轻量摘要，不堆叠切片表格；必要时只同步摘要字段，不复制完整明细 UI。

**Data Design**

- 后端 `SubjectManagementDashboardService.get_detail()` 继续返回 `entries`，但每个 entry 增补：
  - `aggregation_members`
  - `aggregation_window`
  - `entry_slices`
  - `latest_price`
  - `latest_price_source`
  - `remaining_market_value`
  - `remaining_market_value_fallback`
- `latest_price` 优先取 symbol snapshot `close_price`。
- `remaining_market_value = latest_price * remaining_quantity`。
- 若 `latest_price` 缺失，再回退到 `avg_price * remaining_quantity`，并显式标记来源，避免把 fallback 冒充实时市值。

**UI Design**

- `subject-management`
  - entry 摘要第二行继续显示“剩余市值”，但取后端字段，不再前端本地推导。
  - 每行增加“查看切片 / 收起切片”按钮。
  - 展开后先显示聚合成员，再显示 slice ledger。
- `kline-slim`
  - 继续显示相同的 entry 摘要字段。
  - 不显示完整切片表，只保留摘要和后续跳转空间。

**Trade-offs**

- 把完整切片表放在 `order-management` 的优点是贴近订单链，但页面主视角是 order，不是 entry，会把“聚合后的 entry”和“原始 order”混在一起。
- 把完整切片表也塞进 `kline-slim` 会让 overlay 继续膨胀，验证效率反而下降。
- 所以主入口放 `subject-management` 最稳，`order-management` 后续只做单笔订单反查 entry/slice 的补充链路。

**Testing**

- 后端：
  - `SubjectManagementDashboardService` 返回 entry slices / aggregation members / latest-price 口径
  - `remaining_market_value` 优先走 latest price，缺失时回退 avg_price
- 前端：
  - `subjectManagement.mjs` / `kline-slim-subject-panel.mjs` 不再自行用 `avg_price` 计算市值
  - `SubjectManagement.vue` 显示切片展开区
  - `KlineSlim.vue` 继续复用一致字段
