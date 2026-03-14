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

当前图表渲染面已经拆成：

- `kline-slim.js`
  - 页面状态、路由、侧边栏、主图/多周期数据请求
- `kline-slim-chart-controller.mjs`
  - 维护显式 viewport 状态，统一同步 `xRange + yRange`
  - scene 级更新使用完整 option 替换；datazoom 时会按当前 viewport 重建图层，确保 `xRange + yRange + series` 同步
- `kline-slim-chart-renderer.mjs`
  - 负责主 K 线、多周期笔/段/高级段图层以及结构框 overlay
  - 结构框不再使用 `markArea`，改为独立 custom overlay series
  - 图表只渲染当前 viewport 覆盖的 candles / line points / structure boxes，降低缩放和平移时的重绘成本
  - 主图使用连续交易槽位轴压缩午休/隔夜空白，同时保留真实时间戳做结构裁剪
  - 主图禁用 hover tooltip / axisPointer 十字线，避免整屏横线/纵线覆盖视口

当前 legend 语义是：

- legend 控制主周期缠论层和额外周期叠加层
- 当前主周期的 legend 只影响笔 / 段 / 高级段 / 结构框，主 K 线始终显示
- 不再提供独立的 `中枢` / `段中枢` 显示开关

当前跨周期结构定位规则是：

- 渲染坐标使用连续交易槽位轴，不保留非交易时段空白
- 中枢/段中枢仍按真实时间边界裁剪后，再映射到主图槽位窗口
- 越过主图窗口的矩形会按左/右时间边界裁剪，不再做最近 category 点 remap

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
- 图例控制主图缠论层与额外周期叠加
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
- 检查 `kline-slim-chart-controller.mjs` 是否收到了 legend / datazoom 事件
- 检查 scene 更新是否仍在走 viewport 对应的完整图层重建
- 检查 renderer 生成的 series id 是否带当前结构路由作用域
- 检查结构框是否仍被实现成 `markArea`；当前实现应为 custom overlay series

### 缩放后 Y 轴不跟随

- 检查 chart option 里的 `dataZoom.start/end` 与 `chartViewport.xRange` 是否一致
- 检查 `chartViewport.yRange` 是否同步写回 `yAxis.min/max`

### 多周期结构边界错位

- 检查额外周期 payload 的时间戳是否合法且落在同一真实时间线上
- 检查 structure overlay data 的起止时间是否已经被裁剪到主图窗口左右边界

### 结构面板与主图时间不一致

- 检查 `endDate` 是否一致
- 检查结构接口是否拿到了旧缓存
