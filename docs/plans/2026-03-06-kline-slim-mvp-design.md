# KlineSlim MVP 设计稿

**目标**：在目标仓库恢复旧分支 `KlineSlim` 的核心能力，只交付“单图跨周期叠加”最小可用版本：`5m` 主图 + `30m` 缠论结构叠加，使用 HTTP 轮询刷新且无明显闪屏。

## 1. 设计结论

- 路由新增 `/kline-slim`，参数风格延续现有 `KlineBig`。
- 页面默认主周期固定为 `5m`，不再沿用旧分支默认 `120m`。
- 默认叠加周期固定为 `30m`，原因是目标仓库实时缓存只维护 `1m/5m/15m/30m`。
- 不引入 WebSocket，实时数据完全依赖 `/api/stock_data` + 轮询。

## 2. 前端方案

- 新增 `KlineSlim.vue` 与 `views/js/kline-slim.js`。
- 图表层迁移旧 `draw-slim.js`，但只保留：
  - 单图 K 线绘制；
  - `extraChanlunMap` 跨周期叠加；
  - `remapChanlunToAxis` 时间映射；
  - legend 分组与默认选中；
  - dataZoom / legend 状态继承。
- 不迁移：
  - WebSocket 逻辑；
  - 股票池/持仓/网格/备注/信号等侧栏；
  - 多股票 grid 模式；
  - 非实时周期集。

## 3. 轮询与无闪屏策略

- `5m` 主图数据使用 `vue-query` 每 `5s` 轮询。
- `30m` 叠加数据使用独立 query 每 `15s` 轮询。
- 页面隐藏时暂停轮询，避免后台无意义请求。
- 渲染时只创建一次 ECharts 实例；后续刷新不 `dispose()`、不 `clear()`、不 `showLoading()`。
- 用“版本号”判定是否需要重绘，版本号由以下字段组成：
  - `date.length`
  - 最后一根 `date`
  - `_bar_time | updated_at | dt`
- 两路 query 更新统一进入一次 `requestAnimationFrame` 合帧渲染，避免主图和叠加图先后返回造成双重重绘。
- 请求失败时保持上一帧图表，不执行空数据覆盖。

## 4. 后端方案

- 仅增强现有 `/api/stock_data`。
- 条件命中：
  - `endDate` 为空；
  - `period` 属于 `1m/5m/15m/30m`。
- 命中后：
  - 将前端周期转成 backend period；
  - 用 `get_redis_cache_key()` 读取 Redis；
  - JSON 解析成功则原样返回。
- 其他情况继续调用 `get_data_v2()`。

## 5. 风险控制

- 旧 `draw-slim.js` 很大，优先保留兼容路径而不是重写算法，减少缠论图形回归。
- 目标仓库现有 `splitData.js` 已能处理 Redis payload 字段，跨周期叠加重点复用旧逻辑中的 payload-to-series 转换。
- 前端只支持 `1m/5m/15m/30m` legend，避免暴露不可用周期。

## 6. 验收口径

- 默认进入页面即看到 `5m` K 线。
- `30m` 笔/段/中枢默认叠加。
- 拖动缩放后等待轮询刷新，视图不跳回默认区间。
- 人为断开 Redis 或让缓存 miss 时，页面仍能通过 fallback 正常显示。
