# RFC 0022: KlineSlim 多周期缠论图层显示

- **状态**：Done
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-09
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

RFC 0005 已在目标仓库恢复 `KlineSlim` 的主图能力，但当前实现仍停留在 MVP：

- 默认固定展示 `5m` 主图 + `30m` 缠论叠加；
- 前端 renderer 只稳定消费 `bidata / duandata / zsdata`；
- 旧仓 `D:\fqpack\freshquant\morningglory\fqwebui\src\views\js\draw-slim.js` 中多周期缠论层、按周期配色、按周期线宽与 legend 分组联动没有迁回；
- 当前生产者/消费者链路推送到 Redis 的分钟周期只有 `1m / 5m / 15m / 30m`，旧仓更宽的周期集合在目标仓没有实时数据来源。

这直接导致两个用户可见问题：

- 各级别中枢无法完整显示；
- 缠论结构的配色和线条粗细没有对齐旧仓。

## 2. 目标（Goals）

- 在不改 `KlineSlim` 页面整体布局的前提下，恢复旧仓多周期缠论图层能力。
- 前端周期范围收敛到 `1m / 5m / 15m / 30m`。
- 首屏默认只加载 `5m` K 线和 `5m` 缠论结构。
- 其他周期只在用户通过图例打开时懒加载。
- 恢复旧仓按周期映射的配色和线宽规则。
- 支持每周期 `笔 / 段 / 高级别段 / 中枢 / 段中枢 / 高级段中枢`。
- 保留全局 `中枢` / `段中枢` 图例分组。

## 3. 非目标（Non-Goals）

- 不迁移旧仓 MACD 联动。
- 不迁移旧仓日线均线联动。
- 不迁移旧仓网格多图、搜索抽屉、信号筛选、成交标记等工作台能力。
- 不新增后端接口。
- 不为缺失的 `higher_duan_zsdata` 额外补请求或补算。

## 4. 范围（Scope）

**In Scope**

- `morningglory/fqwebui/src/views/KlineSlim.vue` 的状态文案调整；
- `morningglory/fqwebui/src/views/js/kline-slim.js` 的多周期缓存、懒加载与轮询联动；
- `morningglory/fqwebui/src/views/js/draw-slim.js` 的多周期 renderer；
- 新增轻量周期 helper：`morningglory/fqwebui/src/views/js/kline-slim-chanlun-periods.mjs`。

**Out of Scope**

- 后端 `freshquant/rear/stock/routes.py` 接口语义调整；
- Redis 生产者/消费者周期扩展到四个之外；
- 右侧 `缠论结构` 面板接口与显示语义；
- 旧仓其他 KlineSlim 工作台能力。

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- 前端在图表层消费 `/api/stock_data` 已有 fullcalc payload；
- 把高周期线段和中枢 remap 到当前主图时间轴；
- 保持 legend 状态跨重绘不丢失；
- 只刷新当前可见周期集合。

**不负责（Must Not）**

- 生成新的 fullcalc 字段；
- 修改 Redis payload 的字段结构；
- 为没有数据的高级段中枢做兜底查询。

**依赖（Depends On）**

- `/api/stock_data`
- Redis fullcalc payload
- 现有 `KlineSlim` 页面壳子和右侧结构面板

**禁止依赖（Must Not Depend On）**

- 新增 HTTP API
- WebSocket/SSE
- 旧仓完整 `KlineSlim` 页面直接整页回迁

## 6. 对外接口（Public API）

无新增对外 API。

现有接口保持：

- `GET /api/stock_data?symbol=<symbol>&period=<period>&endDate=<optional>&realtimeCache=<optional>`

兼容性语义：

- 不修改 `/api/stock_data` 参数和返回契约；
- 仅修改 `KlineSlim` 对图例和默认显示周期的前端行为。

## 7. 数据与配置（Data / Config）

- 不新增 Mongo / Redis collection。
- 不新增环境变量或 Dynaconf 配置。
- 前端内建固定周期常量：
  - `1m`
  - `5m`
  - `15m`
  - `30m`
- 当前已知 `higher_duan_zsdata` 为空数组时，前端按空层处理。

## 8. 破坏性变更（Breaking Changes）

- `KlineSlim` 默认显示语义从“`5m` 主图 + 固定 `30m` 叠加”调整为“仅默认显示 `5m`，其他周期由图例显式打开”。
- 用户如果依赖旧默认可见的 `30m` 叠加，需要在页面图例中手动打开 `30m`。
- 该变更已在 `docs/migration/breaking-changes.md` 记录。

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- `D:\fqpack\freshquant\morningglory\fqwebui\src\views\js\draw-slim.js`
  -> `morningglory/fqwebui/src/views/js/draw-slim.js`
- `D:\fqpack\freshquant\morningglory\fqwebui\src\views\js\kline-slim.js`
  -> `morningglory/fqwebui/src/views/js/kline-slim.js`
- `D:\fqpack\freshquant\morningglory\fqwebui\src\views\KlineSlim.vue`
  -> `morningglory/fqwebui/src/views/KlineSlim.vue`

迁移策略：

- 不整页拷贝旧仓；
- 只迁移多周期缠论图层、样式映射和 legend 可见性逻辑；
- 周期范围按目标仓 Redis 实时能力收敛为四个。

## 10. 测试与验收（Acceptance Criteria）

- [x] 默认进入 `/kline-slim` 时，只显示 `5m` K 线和 `5m` 缠论结构。
- [x] 图例中 `1m / 15m / 30m` 初始不请求，首次打开时才发请求。
- [x] 已打开周期再次开关时优先走缓存。
- [x] 每周期支持 `笔 / 段 / 高级别段 / 中枢 / 段中枢 / 高级段中枢`。
- [x] `higher_duan_zsdata` 为空时，高级段中枢不显示但不报错。
- [x] 全局 `中枢` / `段中枢` 图例分组生效。
- [x] 已通过 `node --test tests/kline-slim-default-symbol.test.mjs tests/kline-slim-sidebar.test.mjs tests/kline-slim-chanlun-structure.test.mjs tests/kline-slim-multi-period-chanlun.test.mjs`
- [x] 已通过 `npm run build`
- [x] 已通过 `py -3.12 -m pytest freshquant/tests/test_stock_data_route_cache.py freshquant/tests/test_stock_data_chanlun_structure_route.py -q`

## 11. 风险与回滚（Risks / Rollback）

- 风险：图例与重绘状态联动不一致时，可能出现周期显示与缓存状态错位。
- 风险：当前 `higher_duan_zsdata` 无数据，用户会看到该层长期为空。
- 缓解：通过独立 Node 文本测试锁定 helper、controller、renderer 和模板语义。
- 回滚：回退 `KlineSlim.vue`、`kline-slim.js`、`draw-slim.js`、`kline-slim-chanlun-periods.mjs` 与对应测试，并恢复 RFC 0005 的固定 `30m` overlay 实现。

## 12. 里程碑与拆分（Milestones）

- M1：设计评审通过
- M2：四周期 helper 与状态模型完成
- M3：多周期 renderer 完成
- M4：legend 懒加载联动完成
- M5：构建、测试、文档同步完成
