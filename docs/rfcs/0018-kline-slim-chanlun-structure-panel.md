# RFC 0018: KlineSlim 缠论结构面板

- **状态**：Review
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-07
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

RFC 0005 已经在目标仓库恢复 `KlineSlim` 的主图能力，但当前页面只消费 `/api/stock_data` 返回的兼容字段，用于展示 K 线与缠论线条叠加。这些字段足够画图，但不足以稳定支撑以下明细需求：

- 最后一个高级段、段、笔的方向
- 起点与终点时间、价格
- 价格比例
- 高级段内包含几个段
- 段内包含几个笔
- 高级段对应的段中枢明细
- 段对应的笔中枢明细

同时，`/api/stock_data` 当前是双轨：

- 实时模式下可优先读取 Redis 中 consumer 基于 `fullcalc` 推送的缓存 payload；
- 历史模式或缓存 miss 时回退 `get_data_v2()`。

这两条链路对前端画图字段做了兼容，但并不保证“缠论结构明细”完全同源、完全一致。对于新的结构表格，如果继续复用 `/api/stock_data`，会把“实时 `fullcalc`”和“历史 `get_data_v2()`”混成一个事实源，后续难以解释和维护。

旧分支 `D:\fqpack\freshquant` 的 `gantt/shouban30` 缠论筛选后端已经验证过 `fullcalc` 的段结构用法：它直接基于 `duan_high`、`duan` 信号序列提取最后一段，并结合 `pivots`、`pivots_high` 进行结构筛选。这说明新的缠论结构表格应直接复用 `fullcalc`，而不是继续从兼容 payload 逆推。

## 2. 目标（Goals）

- 在 `KlineSlim` 页面新增“缠论结构”按钮。
- 点击后在 K 线上方展示半透明结构面板。
- 面板展示最后一个高级段、段、笔的结构摘要。
- 面板展示高级段对应的段中枢明细，段对应的笔中枢明细。
- 结构数据统一来自 `fullcalc`。
- 同时支持实时模式与历史模式。
- 不影响现有 `/api/stock_data` 契约和 `KlineSlim` 主图轮询逻辑。

## 3. 非目标（Non-Goals）

- 不改造 consumer 的 Redis payload 契约。
- 不把“缠论结构表格”直接塞进 `/api/stock_data` 返回体。
- 不引入新的持久化集合、消息队列或后台预计算作业。
- 不恢复旧分支 `KlineSlim` 的其他工作台能力。
- 不新增自动轮询刷新该面板；面板保持手动打开、手动刷新。

## 4. 范围（Scope）

**In Scope**

- 新增专用后端接口 `GET /api/stock_data_chanlun_structure`
- 新增独立服务模块，统一基于 `fullcalc` 提取高级段、段、笔和中枢明细
- 实时模式优先复用 Redis 中 consumer 缓存的 OHLCV bar
- 历史模式按 `symbol + period + endDate` 取 K 线后现场执行 `fullcalc`
- `KlineSlim` 新增 `缠论结构` 按钮、半透明面板、手动刷新和错误态
- 新增后端与前端测试覆盖本需求行为

**Out of Scope**

- 修改 `/api/stock_data` 的返回结构
- 修改 consumer 缓存内容
- 为结构表格新增 Mongo/Redis 独立快照存储
- 恢复旧 `KlineSlim` 其他专题功能

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- `freshquant/rear/stock/routes.py` 负责暴露专用 HTTP 接口
- 新服务模块负责取 bar、重建 `DataFrame`、执行 `fullcalc` 并提取结构
- `morningglory/fqwebui` 负责按钮、面板、错误态与表格展示
- 前后端测试负责固定结构字段语义和页面关键文案

**不负责（Must Not）**

- 不修改现有 `/api/stock_data` 双轨逻辑
- 不在前端自己推导段/笔/中枢关系
- 不在本 RFC 中统一历史 `get_data_v2()` 与实时 `fullcalc` 的算法实现

**依赖（Depends On）**

- RFC 0003：XTData Producer/Consumer + `fullcalc`
- RFC 0005：`KlineSlim` MVP 与 `/api/stock_data` Redis-first 实时查询
- 旧分支参考能力：
  - `D:\fqpack\freshquant\freshquant\data\gantt_shouban30_service.py`
  - `D:\fqpack\freshquant\freshquant\tdx\toolkit\volume_turnover_screener.py`

**禁止依赖（Must Not Depend On）**

- 不依赖新的数据库集合
- 不依赖新的 WebSocket 或 Pub/Sub 前端订阅协议
- 不依赖旧分支 `KlineSlim` 的完整页面实现

## 6. 对外接口（Public API）

### 6.1 HTTP API

- 新增 `GET /api/stock_data_chanlun_structure`
- 参数：
  - `symbol`：必填
  - `period`：必填
  - `endDate`：可选

返回结构：

```json
{
  "ok": true,
  "symbol": "sz000001",
  "period": "5m",
  "endDate": null,
  "source": "realtime_cache_fullcalc",
  "bar_count": 8000,
  "asof": "2026-03-07 10:30",
  "message": "",
  "structure": {
    "higher_segment": null,
    "segment": null,
    "bi": null
  }
}
```

结构区字段：

- `higher_segment`
  - `direction`
  - `start_idx`
  - `start_time`
  - `start_price`
  - `end_idx`
  - `end_time`
  - `end_price`
  - `price_change_pct`
  - `contained_duan_count`
  - `pivot_count`
  - `pivots[]`
- `segment`
  - `direction`
  - `start_idx`
  - `start_time`
  - `start_price`
  - `end_idx`
  - `end_time`
  - `end_price`
  - `price_change_pct`
  - `contained_bi_count`
  - `pivot_count`
  - `pivots[]`
- `bi`
  - `direction`
  - `start_idx`
  - `start_time`
  - `start_price`
  - `end_idx`
  - `end_time`
  - `end_price`
  - `price_change_pct`

### 6.2 错误语义

- 参数缺失或非法：返回 400
- `fullcalc` 不可用、bar 不足或结构为空：
  - HTTP 仍返回 200
  - 通过 `ok` 与 `message` 表达业务状态
- “结构不存在”按空业务结果处理，不作为接口异常

### 6.3 兼容策略

- 不修改现有 `/api/stock_data` 返回结构
- 新需求全部通过独立接口实现

## 7. 数据与配置（Data / Config）

- 不新增新的持久化 schema
- 实时模式读 Redis 现有缓存 key：
  - `CACHE:KLINE:<code>:<period_backend>`
- 历史模式继续复用现有 K 线查询链路
- 新服务模块内部统一构造带以下列的 `DataFrame`：
  - `datetime`
  - `open`
  - `high`
  - `low`
  - `close`
  - `volume`
  - `amount`

## 8. 破坏性变更（Breaking Changes）

本 RFC 不计划修改现有对外契约，不引入破坏性变更。

如果后续实现中发现必须修改 `/api/stock_data`、consumer payload、或 `KlineSlim` 已有行为语义，则需追加更新 `docs/migration/breaking-changes.md`。

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- `D:\fqpack\freshquant\freshquant\tdx\toolkit\volume_turnover_screener.py`
  - `_extract_last_segment_from_signal()` → 新服务模块中的段/笔提取逻辑
- `D:\fqpack\freshquant\freshquant\data\gantt_shouban30_service.py`
  - `_calc_period_last_segments_meta()` → 新服务模块中的“最后高级段/段摘要”提取思路
- `D:\fqpack\freshquant\morningglory\fqwebui\src\views\KlineSlim.vue`
  - 页面交互参考 → 当前仓库 `KlineSlim` 面板扩展

## 10. 测试与验收（Acceptance Criteria）

- [x] 后端服务测试能固定最后一个高级段、段、笔的方向和端点提取语义
- [x] 后端服务测试能固定中枢归属和包含数量统计语义
- [x] 路由测试能验证 `/api/stock_data_chanlun_structure` 调用新服务并返回 JSON
- [x] `KlineSlim` 页面存在 `缠论结构` 按钮
- [x] 打开面板后能看到 `高级段 / 段 / 笔` 三个区块
- [x] 面板具备 `刷新 / 关闭 / 重试` 交互
- [x] 实时模式可基于 Redis bar 重建 `fullcalc` 结构
- [x] 历史模式可基于 `symbol + period + endDate` 返回同一结构语义

已验证：

- `py -m pytest freshquant/tests/test_chanlun_structure_service.py freshquant/tests/test_stock_data_chanlun_structure_route.py -q`
- `node --test tests/kline-slim-chanlun-structure.test.mjs`
- `npm install --no-package-lock`
- `npm run build`

## 11. 风险与回滚（Risks / Rollback）

- 风险：接口侧重新执行一次 `fullcalc`，如果输入窗口和 consumer 使用的窗口不一致，实时图表与结构表格可能出现边界差异。
  - 缓解：实时模式优先复用 Redis bar 数据，并通过测试固定重建 `DataFrame` 语义。
- 风险：历史模式 `endDate` 截止语义与主图展示范围可能出现认知偏差。
  - 缓解：返回体明确包含 `endDate` 与 `asof`。
- 风险：包含数量与中枢归属的边界处理不稳定。
  - 缓解：先写失败测试，固定“完整落在区间内”的规则。

回滚方式：

- 删除新接口和新服务模块
- 删除 `KlineSlim` 面板相关前端代码
- 保持现有 `/api/stock_data` 与主图逻辑不变

## 12. 里程碑与拆分（Milestones）

- M1：RFC 0018 起草并进入 Implementing
- M2：后端 `fullcalc` 结构服务完成
- M3：专用接口完成
- M4：`KlineSlim` 面板完成
- M5：测试通过并同步迁移进度
