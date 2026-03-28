# Kline Web UI

## 职责

`/kline-slim` 负责单标的多周期图表、缠论结构和标的配置浮层。当前与订单账本相关的部分已经切到 `position entry` 语义。

## 入口

- 前端路由
  - `/kline-slim`
- 后端接口
  - `/api/stock_data`
  - `/api/stock_data_v2`
  - `/api/stock_data_chanlun_structure`
  - `/api/subject-management/<symbol>`
  - `/api/subject-management/<symbol>/must-pool`
  - `/api/subject-management/<symbol>/guardian-buy-grid`
  - `/api/position-management/symbol-limits/<symbol>`
  - `/api/order-management/stoploss/bind`
  - `/api/tpsl/takeprofit/<symbol>`
  - `/api/tpsl/takeprofit/<symbol>/rearm`

## 当前订单相关语义

- 标的设置浮层中的止损对象已经是 open `entries`
- 保存止损时只提交 `entry_id`
- 浮层详情返回 `entries`，不再依赖 `buy_lots`
- 持仓股侧边栏排序与 SubjectManagement、PositionManagement 保持一致，按持仓金额从大到小排序

## 当前页面结构

- 主图与多周期结构
- 画线编辑浮层
  - Guardian 阶梯价
  - 止盈价
- 标的设置浮层
  - `must_pool` 基础配置
  - 单标的仓位上限
  - entry stoploss
- 缠论结构浮层

## 当前数据流

- `symbol -> /api/subject-management/<symbol>`
  - 读取标的设置浮层 detail
- `保存标的设置`
  - `must_pool`
  - `symbol-limit`
  - `entry stoploss bind`
- `保存画线编辑`
  - Guardian 配置
  - takeprofit profile / rearm

## 当前边界

- `KlineSlim` 继续负责 Guardian / takeprofit 的编辑入口
- `entry stoploss` 只在标的设置浮层编辑
- 图表页不再直接展示长 `buy_lot_id`

## 排障

### 标的设置浮层保存后没刷新

- 查 `/api/subject-management/<symbol>` 是否返回 `entries`
- 查 `/api/order-management/stoploss/bind` 是否成功
- 查 `om_entry_stoploss_bindings`

### 持仓股侧边栏顺序异常

- 查返回的持仓金额字段
- 当前排序口径是 `position_amount -> market_value -> amount`

### 浮层仍出现 `buy_lot` 文案

- 查 `subjectManagement` / `kline-slim-subject-panel` 的 detail 归一逻辑
- 当前页面只应使用 `entryDisplayLabel / entryMetaLabel / entryIdLabel`
