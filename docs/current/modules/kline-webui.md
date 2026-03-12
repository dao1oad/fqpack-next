# Kline Web UI

## 职责

Kline Web UI 负责展示单标的多周期行情、缠论结构摘要和侧边栏股票列表，是当前最直接的实时/历史结构查看页面。

## 入口

- 前端路由
  - `/kline-slim`
- 前端页面
  - `KlineSlim.vue`
- 后端接口
  - `/api/stock_data`
  - `/api/stock_data_v2`
  - `/api/stock_data_chanlun_structure`

## 依赖

- `get_data_v2`
- Redis realtime cache
- Chanlun structure service
- stock pool / must_pool / positions 等列表接口
- Gantt 热点理由接口

## 数据流

`symbol + period + endDate -> /api/stock_data -> KlineSlim 主图`

`symbol + period + endDate -> /api/stock_data_chanlun_structure -> 缠论结构面板`

`sidebar section -> 相关列表接口 / 热门理由接口 -> 侧边栏与 hover popover`

`holding -> /api/get_stock_position_list -> get_stock_positions() -> 优先按当前 instrument 信息补全/刷新名称 -> sidebar 标题`

## 存储

Kline 页面不维护自己的事实源，读取的主要是：

- QuantAxis 历史数据
- Redis realtime cache
- 结构计算结果
- stock pool / must_pool / xt_positions

## 配置

- `symbol`
- `period`
- `endDate`
- `realtimeCache`

页面当前支持：

- 周期按钮切换
- 历史日期回看
- 缠论结构面板
- 多个侧边栏分组
- 热门理由 hover 展示

## 部署/运行

- 前端改动：重建 `fq_webui`
- `stock_data` 或结构接口改动：重建 `fq_apiserver`
- 实时展示异常时，通常需要同时核对 XTData 链和页面接口

## 排障点

### 页面空白

- 检查 `/api/stock_data` 是否 500
- 检查路由参数是否为空

### 图层残影或主图不刷新

- 检查 realtime cache 是否还在更新
- 检查前端 period 切换后是否真的重新请求

### 结构面板与主图时间不一致

- 检查 `endDate` 是否一致
- 检查结构接口是否拿到了旧缓存
