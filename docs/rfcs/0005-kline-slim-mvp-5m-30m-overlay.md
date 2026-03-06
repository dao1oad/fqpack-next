# RFC 0005: KlineSlim MVP（5m 主图 + 30m 缠论叠加）

- **状态**：Approved
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-06
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

旧仓库 `D:\fqpack\freshquant` 的 `KlineSlim` 页面支持单图 K 线与缠论结构跨周期叠加展示，核心价值在于：

- 主周期 K 线与高周期缠论结构同图观察；
- 高周期笔、段、中枢通过时间映射落到主图坐标轴；
- 默认展示重点结构，减少多图切换成本。

目标仓库 `D:\fqpack\freshquant-2026.2.23` 已完成 XTData Producer/Consumer + Redis 实时缓存链路，但前端仍缺少 `KlineSlim` 页面，后端 `/api/stock_data` 也未利用现有 Redis 实时缓存，导致：

- 旧分支核心交易观察页面缺失；
- 实时场景仍走 `get_data_v2()` 全量计算，刷新成本高；
- 无 WebSocket 时只能靠轮询，但当前前端没有“无闪屏”更新方案。

同时，当前系统内存与实时缓存仅维护 `1m/5m/15m/30m` bar 数据，不再适合沿用旧分支默认 `120m` 叠加策略。

## 2. 目标（Goals）

- 在目标仓库落地 `KlineSlim` MVP 页面，恢复“单图跨周期叠加”核心能力。
- 默认展示 `5m` 主图 K 线，并默认叠加 `30m` 缠论结构。
- 前端使用 HTTP 轮询，不引入 WebSocket。
- 轮询刷新过程中避免明显闪屏，保留缩放与 legend 选择状态。
- 后端增强 `/api/stock_data`，提供 **opt-in** 的 Redis-first 实时查询路径，供 `KlineSlim` 实时模式使用，同时保持旧页面默认仍走原 `get_data_v2()` 契约。

## 3. 非目标（Non-Goals）

- 不迁移旧分支 `KlineSlim` 侧边工作台能力（持仓、股票池、网格、备注、信号、成交等）。
- 不新增 `/api/stock/chanlun_structure`。
- 不引入新的 WebSocket 服务或前端 WebSocket 客户端。
- 不恢复 `60m/120m/1d` 等目标仓库实时链路未维护的跨周期默认展示。
- 不重构现有 `KlineBig`/`MultiPeriod` 页面。

## 4. 范围（Scope）

**In Scope**

- 新增 `/kline-slim` 路由与对应前端页面。
- 迁移并裁剪旧分支 `draw-slim.js` 的单图跨周期叠加能力。
- 页面默认请求 `5m` 主图与 `30m` 叠加数据。
- 轮询刷新与 ECharts 增量更新策略。
- `/api/stock_data` 的 **opt-in Redis-first** 实时读取逻辑。
- 文档、迁移进度与变更记录同步更新。

**Out of Scope**

- 多股票网格模式。
- 高频 tick 级别增量推送。
- 页面视觉重设计。
- Redis miss 后的后台异步回填机制改造。

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- `morningglory/fqwebui` 负责 KlineSlim MVP UI、轮询、图表状态保持。
- `freshquant/rear/stock/routes.py` 负责 `realtimeCache=1` 场景下的 Redis 优先返回。
- `freshquant/util/period.py` 与 Redis cache key 约定继续作为周期归一入口。

**不负责（Must Not）**

- 不在本 RFC 内修改 XTData Producer/Consumer 的缓存生成逻辑。
- 不在本 RFC 内新增实时推送协议。
- 不在本 RFC 内统一旧分支全部 `KlineSlim` 附属能力。

**依赖（Depends On）**

- `freshquant.market_data.xtdata.strategy_consumer` 已持续写入 `CACHE:KLINE:<code>:<period_backend>`。
- `freshquant.market_data.xtdata.chanlun_payload.build_chanlun_payload()` 生成的 payload 字段与旧前端可兼容。
- 前端已有 `echarts`、`@tanstack/vue-query`。

**禁止依赖（Must Not Depend On）**

- 旧仓库本地 `dataStore.js` 与 `websocket.js`。
- 新增数据库表、消息队列或第三方服务。

## 6. 对外接口（Public API）

### 6.1 前端路由

- 新增 `GET /kline-slim?symbol=<code>&period=<optional>&endDate=<optional>`
- 默认行为：
  - `period` 缺省时按 `5m` 处理；
  - `endDate` 缺省时启用实时轮询；
  - 默认叠加 `30m` 缠论结构。

### 6.2 HTTP API

- 复用现有 `GET /api/stock_data?symbol=<code>&period=<period>&endDate=<optional>&realtimeCache=<optional>`
- 行为调整：
  - 当 `realtimeCache in {1, true, yes}`、`endDate` 为空、且 `period in {1m, 5m, 15m, 30m}` 时，优先读 Redis 缓存；
  - Redis 命中则直接返回缓存 payload；
  - Redis miss、Redis 异常、或非实时/非支持周期请求时，回退到 `get_data_v2()`；
  - 当 `realtimeCache` 缺省或为假值时，保持旧行为，直接走 `get_data_v2()`；
  - 返回 JSON 结构维持兼容，不新增强制字段。

### 6.3 错误语义

- Redis 读取失败不改变 HTTP 返回码，记录 warning 后回退数据库/计算路径。
- 前端轮询失败不清空图表，保持上一次成功数据并等待下次轮询。
- 旧页面不需要感知 `realtimeCache`；只有 `KlineSlim` 的实时模式默认带上该参数。

## 7. 数据与配置（Data / Config）

- Redis Key：`CACHE:KLINE:<code_lower>:<period_backend>`
- 支持实时缓存周期：`1m/5m/15m/30m`
- `realtimeCache=1` 仅由 `KlineSlim` 在“未指定 `endDate` 的实时模式”下默认发送；历史模式不发送。
- 前端轮询策略：
  - 主图 `5m` 默认每 `5s` 轮询一次；
  - 叠加 `30m` 默认每 `15s` 轮询一次；
  - 页面不可见时暂停轮询。
- 前端图表状态：
  - 保留 dataZoom；
  - 保留 legend 选中状态；
  - 仅在数据版本变化时调用 `setOption()`。

## 8. 破坏性变更（Breaking Changes）

- 本 RFC 不引入对调用方可见的破坏性变更。
- `/api/stock_data` 的 Redis-first 仅在 `realtimeCache=1` 时启用，默认调用契约保持不变。
- 回滚方案：移除 `realtimeCache` 分支，恢复全部请求走 `get_data_v2()`；前端可继续保留页面代码但改为纯接口轮询。

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- `morningglory/fqwebui/src/views/KlineSlim.vue`
  → `morningglory/fqwebui/src/views/KlineSlim.vue`
- `morningglory/fqwebui/src/views/js/kline-slim.js`
  → 裁剪迁移为目标仓库 `morningglory/fqwebui/src/views/js/kline-slim.js`
- `morningglory/fqwebui/src/views/js/draw-slim.js`
  → 裁剪迁移为目标仓库 `morningglory/fqwebui/src/views/js/draw-slim.js`
- 旧分支默认 `120m` 叠加策略
  → 目标仓库改为默认 `30m` 叠加
- 旧分支 WebSocket + Local/Redis/DB store
  → 目标仓库 MVP 仅保留 HTTP 轮询 + Redis-first API

## 10. 测试与验收（Acceptance Criteria）

- [ ] 访问 `/kline-slim?symbol=sh510050` 时，页面默认展示 `5m` K 线。
- [ ] 页面默认可见 `30m` 缠论叠加结构，且图例处于选中状态。
- [ ] `KlineSlim` 在 `endDate` 为空时，对 `/api/stock_data` 的请求默认携带 `realtimeCache=1`。
- [ ] `KlineSlim` 在带 `endDate` 的历史模式下，不发送 `realtimeCache=1`。
- [ ] `realtimeCache=1` 且 Redis 命中时，`/api/stock_data` 返回缓存 payload。
- [ ] `realtimeCache=1` 且 Redis miss 时，`/api/stock_data` 能正确回退到 `get_data_v2()`。
- [ ] 未携带 `realtimeCache` 的旧页面请求，仍走原 `get_data_v2()` 路径。
- [ ] 轮询刷新时不出现明显闪屏，不因失败轮询清空已有图表。
- [ ] 用户手动缩放/切换 legend 后，下次轮询仍保持状态。

## 11. 风险与回滚（Risks / Rollback）

- 风险点：旧 `draw-slim.js` 体量较大，裁剪不当可能引入无用依赖或渲染回归。
- 缓解：只迁移单图叠加所需能力，去掉 WebSocket、侧边栏、MACD 扩展等非 MVP 部分。
- 风险点：Redis 缓存 payload 与 `splitData.js` 的兼容边界存在历史差异。
- 缓解：优先复用旧 `draw-slim.js` 中 `extraChanlunMap` 与 `buildChanlunDataFromPayload()` 逻辑。
- 回滚：后端去掉 `realtimeCache` 分支，前端暂时下线路由 `/kline-slim`。

## 12. 里程碑与拆分（Milestones）

- M1：RFC Approved
- M2：后端 `/api/stock_data` Redis-first 完成
- M3：前端 `KlineSlim` 页面与 `draw-slim.js` MVP 完成
- M4：轮询无闪屏验证完成，进度状态更新为 Done
