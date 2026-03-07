# KlineSlim 缠论结构面板设计

**日期**：2026-03-07

## 背景

当前 `KlineSlim` 页面已经能展示主图 K 线与 `30m` 缠论叠加，但页面只消费 `/api/stock_data` 的兼容字段，主要用于画图：

- `date/open/high/low/close`
- `bidata/duandata/higherDuanData`
- `zsdata/zsflag`

这套兼容字段足够支撑图形叠加，但不足以稳定展示以下明细：

- 最后一个高级段、段、笔的方向与端点
- 高级段内包含几个段
- 段内包含几个笔
- 高级段对应的段中枢明细
- 段对应的笔中枢明细

同时，`/api/stock_data` 当前是双轨：

- 实时模式下可优先读取 Redis 中 consumer 基于 `fullcalc` 推送的缓存 payload
- 历史模式或缓存 miss 时回退 `get_data_v2()`

这两条链路对前端画图字段做了兼容，但并不保证“缠论结构明细”完全同源、完全一致。对于新的结构表格，如果继续复用 `/api/stock_data`，会把“实时 fullcalc”和“历史 `get_data_v2()`”混成一个事实源，后续难以解释和维护。

旧分支 `gantt/shouban30` 的缠论筛选后端已经验证过 `fullcalc` 的段结构用法：它直接基于 `duan_high`、`duan` 信号序列提取最后一段，并配合 `pivots`、`pivots_high` 进行结构筛选。这说明“缠论结构表格”应该直接复用 `fullcalc`，而不是再从兼容 payload 逆推。

## 目标

- 在 `KlineSlim` 页面新增“缠论结构”按钮。
- 点击后在 K 线上方展示半透明结构面板。
- 面板展示最后一个高级段、段、笔的结构摘要。
- 面板展示高级段对应的段中枢明细，段对应的笔中枢明细。
- 结构数据统一来自 `fullcalc`。
- 同时支持实时模式与历史模式。

## 非目标

- 不改造 consumer 的 Redis payload 契约。
- 不把“缠论结构表格”直接塞进 `/api/stock_data` 返回体。
- 不引入新的持久化集合、消息队列或后台预计算作业。
- 不恢复旧分支 `KlineSlim` 的其他工作台能力。
- 不新增自动轮询刷新该面板；面板保持手动打开、手动刷新。

## 现状结论

- `KlineSlim` 当前通过 `futureApi.stockData()` 调 `/api/stock_data` 获取主图与叠加周期数据。
- 实时模式通过 `realtimeCache=1` 让 `/api/stock_data` 优先尝试 Redis 缓存；页面本身不直接读 Redis，也不直接订阅 Pub/Sub。
- consumer 缓存 payload 来源于 `fullcalc`，但它当前只保留画图需要的兼容字段，不含“最后段/高级段/中枢归属统计”这类表格明细。
- `get_data_v2()` 走的是 `Chanlun().analysis()` 与衍生信号链路，和 consumer 的 `fullcalc` 不是同一计算实现。
- 旧分支 `gantt/shouban30` 已经证明：`fullcalc` 原始结果中的 `duan_high`、`duan`、`bi`、`pivots_high`、`pivots` 足够支撑本需求。

## 方案比较

### 方案 A：新增专用接口，实时优先复用 Redis 缓存 bar，现场跑 `fullcalc` 后返回结构表格（推荐）

做法：

- 新增专用接口，例如 `GET /api/stock_data_chanlun_structure`
- 实时模式优先读 Redis 中 consumer 缓存的 OHLCV 数组，重建 `DataFrame`
- 历史模式直接按 `symbol + period + endDate` 取 K 线
- 统一在接口侧现场执行一次 `run_fullcalc(df, model_ids=[])`
- 返回直接可渲染的结构化表格数据

优点：

- 实时和历史都能支持
- 不改 consumer 主链路和缓存契约
- 结构面板与图表仍尽量共用同一批 bar 数据
- 数据真相源单一，后续定位问题简单

缺点：

- 面板每次打开或手动刷新都要跑一次 `fullcalc`

### 方案 B：直接扩展 consumer 缓存 payload，前端直接读取

优点：

- 查询最轻
- 实时模式展示最快

缺点：

- 改动 consumer 主链路和缓存契约，影响面扩大
- 历史模式仍需另一套逻辑
- 会把面向画图的 payload 变成重型结构对象

### 方案 C：新增结构快照存储，由后台预计算并查询

优点：

- 读性能最好

缺点：

- 需要新增存储与失效策略
- 需要定义历史回放与实时同步语义
- 超出本次最小需求边界

## 设计决策

采用方案 A：新增专用接口，统一以 `fullcalc` 为结构真相源；实时模式优先复用 Redis 缓存 bar，历史模式直接取 K 线后现场执行 `fullcalc`。

## 架构与数据流

### 1. 专用后端接口

- 新增 `GET /api/stock_data_chanlun_structure`
- 参数：
  - `symbol`
  - `period`
  - `endDate`（可选）

### 2. 数据来源规则

- 实时模式：`endDate` 为空，且 `period in {1m, 5m, 15m, 30m}`
  - 优先读取 Redis 中 consumer 已推送的缓存 payload
  - 从 `date/open/high/low/close/volume/amount` 重建 `DataFrame`
  - 现场执行 `run_fullcalc(df, model_ids=[])`
- 历史模式：`endDate` 非空
  - 不读 Redis
  - 直接按 `symbol + period + endDate` 读取 K 线
  - 现场执行 `run_fullcalc(df, model_ids=[])`

### 3. 服务边界

- 路由层只做参数解析、错误返回和 JSON 输出
- 新增独立服务模块负责：
  - 取 bar
  - 重建 `DataFrame`
  - 执行 `fullcalc`
  - 提取最后一个高级段、段、笔
  - 归属中枢与包含数量

## 结构提取规则

### 1. 最后一个高级段

- 信号来源：`fc_res["duan_high"]`
- 提取方法：
  - 取最后两个有效拐点
  - `1` 对应当前 bar 的 `high`
  - `-1` 对应当前 bar 的 `low`
  - 终点价大于起点价则方向为 `up`，否则为 `down`

### 2. 最后一个段

- 信号来源：`fc_res["duan"]`
- 提取规则同上

### 3. 最后一笔

- 信号来源：`fc_res["bi"]`
- 提取规则同上

### 4. 价格比例

- 统一返回涨跌幅百分比：
  - `price_change_pct = (end_price / start_price - 1) * 100`
- 前端显示为百分比文本，例如 `8.32%`

### 5. 包含数量

- 高级段的 `contained_duan_count`
  - 计算该高级段起止区间内完整包含的段数量
  - 以落在区间内的段拐点数减一得到数量
- 段的 `contained_bi_count`
  - 计算该段起止区间内完整包含的笔数量
  - 以落在区间内的笔拐点数减一得到数量

### 6. 中枢归属

- 高级段下挂段中枢：
  - 使用 `fc_res["pivots_high"]`
  - 只保留完整落在最后一个高级段起止区间内的中枢
- 段下挂笔中枢：
  - 使用 `fc_res["pivots"]`
  - 只保留完整落在最后一个段起止区间内的中枢

### 7. 中枢字段

每个中枢返回：

- `start_idx`
- `start_time`
- `end_idx`
- `end_time`
- `zg`
- `zd`
- `gg`
- `dd`
- `direction`

## 接口返回结构

接口直接返回前端可渲染结构，不向前端暴露 `fullcalc` 原始信号数组：

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
    "higher_segment": {
      "direction": "up",
      "start_idx": 120,
      "start_time": "2026-03-06 14:35",
      "start_price": 10.12,
      "end_idx": 168,
      "end_time": "2026-03-07 10:30",
      "end_price": 10.98,
      "price_change_pct": 8.50,
      "contained_duan_count": 4,
      "pivot_count": 2,
      "pivots": []
    },
    "segment": {
      "direction": "down",
      "start_idx": 150,
      "start_time": "2026-03-07 10:10",
      "start_price": 10.88,
      "end_idx": 168,
      "end_time": "2026-03-07 10:30",
      "end_price": 10.63,
      "price_change_pct": -2.30,
      "contained_bi_count": 5,
      "pivot_count": 1,
      "pivots": []
    },
    "bi": {
      "direction": "up",
      "start_idx": 164,
      "start_time": "2026-03-07 10:26",
      "start_price": 10.58,
      "end_idx": 168,
      "end_time": "2026-03-07 10:30",
      "end_price": 10.63,
      "price_change_pct": 0.47
    }
  }
}
```

约定：

- `higher_segment`、`segment`、`bi` 不存在时返回 `null`
- “结构不存在”作为空业务结果处理，不作为接口异常
- `source` 建议枚举：
  - `realtime_cache_fullcalc`
  - `history_fullcalc`
  - `fallback_fullcalc`

## 前端设计

### 1. 按钮

在 `KlineSlim` 工具栏新增按钮 `缠论结构`，放在 `刷新` 后、`大图` 前。

### 2. 面板布局

- 在 `.kline-slim-content` 中增加绝对定位覆盖层
- 面板在图表上方显示，保留半透明背景
- 不改变当前 sidebar 与 chart 的总体布局

### 3. 面板头部

显示：

- 标题：`缠论结构`
- 当前 `symbol / period / asof`
- 数据来源标签：`实时 fullcalc` 或 `历史 fullcalc`
- 按钮：`刷新`、`关闭`

### 4. 面板主体

固定三段：

- 高级段
- 段
- 笔

展示规则：

- 每段先显示摘要信息：
  - 方向
  - 起点时间
  - 起点价格
  - 终点时间
  - 终点价格
  - 价格比例
  - 包含数量
  - 中枢数量
- 高级段下方显示段中枢表格
- 段下方显示笔中枢表格
- 笔只显示摘要，不显示子表
- 某一级不存在时保留区块，显示 `暂无已完成高级段/段/笔`

### 5. 刷新策略

用户已确认该面板不跟随 `KlineSlim` 自动轮询刷新：

- 第一次打开面板时加载一次
- 点击面板头部 `刷新` 时重新加载
- 点击工具栏按钮仅负责打开面板

## 错误语义

- 第一次打开加载失败：
  - 面板保持打开
  - 主体显示错误提示和 `重试` 按钮
- 已有成功数据后刷新失败：
  - 保留上次成功结果
  - 头部显示 `刷新失败，保留上次结果`
- `fullcalc` 不可用、bar 不足或结构为空：
  - HTTP 返回 200
  - `ok` 与 `message` 表达结果语义

## 落地文件范围

- 后端接口：
  - `freshquant/rear/stock/routes.py`
- 后端服务：
  - 新增 `freshquant/chanlun_structure_service.py`
- 后端测试：
  - 新增 `freshquant/tests/test_chanlun_structure_service.py`
  - 新增 `freshquant/tests/test_stock_data_chanlun_structure_route.py`
- 前端 API 与页面：
  - `morningglory/fqwebui/src/api/futureApi.js`
  - `morningglory/fqwebui/src/views/KlineSlim.vue`
  - `morningglory/fqwebui/src/views/js/kline-slim.js`
- 前端测试：
  - 新增 `morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs`

## 验收标准

- `KlineSlim` 出现 `缠论结构` 按钮
- 点击按钮后出现半透明结构面板
- 面板包含 `高级段 / 段 / 笔` 三个区块
- 高级段与段区块能展示中枢表格
- 实时模式下接口可基于 Redis bar 重建 `fullcalc` 结构
- 历史模式下接口可基于 `symbol + period + endDate` 返回同一结构
- 结构字段语义稳定：
  - 方向
  - 起止时间
  - 起止价格
  - 百分比涨跌幅
  - 包含数量
  - 中枢数量与中枢列表

## 风险

- 实时模式虽然优先复用 Redis bar，但结构表格不是直接复用 consumer 的最终结果，而是接口侧重新执行一次 `fullcalc`；如果后续 consumer 与接口调用使用的输入窗口不一致，可能出现边界差异。
- 历史模式需要明确 `endDate` 截止语义，避免与主图显示范围产生认知偏差。
- 结构归属统计依赖“区间内完整包含”的定义，后续实现时需要用测试固定边界。

## 流程约束

本需求会新增一个对外 HTTP 入口。按照仓库规则，编码前必须先补 RFC 并通过评审。本文仅作为设计记录，不替代 RFC。

后续实施顺序必须是：

1. 起草 RFC
2. 更新 `docs/migration/progress.md`
3. RFC 进入 Approved 后再编码
4. 代码完成后同步更新进度记录
