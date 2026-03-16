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
  - `/api/subject-management/<symbol>`
  - `/api/subject-management/<symbol>/guardian-buy-grid`
  - `/api/tpsl/takeprofit/<symbol>`

## 依赖

- `get_data_v2`
- Redis realtime cache
- Chanlun structure service
- stock pool / must_pool / positions 等列表接口
- subject-management 聚合详情与 Guardian 保存接口
- TPSL 止盈配置接口
- Gantt 热点理由接口

## 数据流

`symbol + period + endDate -> /api/stock_data -> KlineSlim 主图`

`symbol + period + endDate + barCount -> /api/stock_data -> realtime cache 命中时按 barCount 截尾，未命中时走历史拉取并尽量补足同样窗口`

`symbol + period + endDate -> /api/stock_data_chanlun_structure -> 缠论结构面板`

`symbol -> /api/subject-management/<symbol> -> Guardian / 止盈价格层级面板`

`Guardian / 止盈保存 -> subject-management / tpsl 接口 -> 图表价格横线重绘`

`sidebar section -> 相关列表接口 / 热门理由接口 -> 侧边栏与 hover popover`

`holding -> /api/get_stock_position_list -> get_stock_positions() -> 优先按当前 instrument 信息补全/刷新名称 -> sidebar 标题`

当前图表渲染面已经拆成：

- `kline-slim.js`
  - 页面状态、路由、侧边栏、主图/多周期数据请求
  - 价格层级面板的 symbol 级加载、保存和重绘触发
- `kline-slim-price-panel.mjs`
  - Guardian / 止盈草稿状态、保存校验与接口动作封装
- `kline-slim-chart-controller.mjs`
  - 维护显式 viewport 状态，统一同步 `xRange + yRange`
  - scene 级更新使用完整 option 替换；datazoom 时会按当前 viewport 重建图层，确保 `xRange + yRange + series` 同步
  - Y 轴范围会把 Guardian / 止盈价格线一并纳入
- `kline-slim-chart-renderer.mjs`
  - 负责主 K 线、多周期笔/段/高级段图层以及结构框 overlay
  - 负责 Guardian / 止盈价格横线 overlay，并在 legend 中提供默认开启的独立开关
  - 结构框不再使用 `markArea`，改为独立 custom overlay series
  - 图表只渲染当前 viewport 覆盖的 candles / line points / structure boxes，降低缩放和平移时的重绘成本
  - 主图使用连续交易槽位轴压缩午休/隔夜空白，同时保留真实时间戳做结构裁剪
  - 主图禁用 ECharts 默认 hover tooltip / axisPointer，改为自定义十字星 overlay
  - 自定义十字星保留横线、竖线、价格标签、日期标签；鼠标移出图表后停留在最后位置，重新移入后按当前位置实时更新且不保留残影
- `subject-price-guides.mjs`
  - 统一归一化 Guardian / 止盈草稿、校验规则以及价格线 / legend 分组生成逻辑

当前 legend 语义是：

- legend 控制主周期缠论层和额外周期叠加层
- legend 同时控制 Guardian / 止盈价格横线分组，默认显示
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
- `barCount`

当前主图默认请求窗口：

- `KlineSlim` 默认 `barCount = 20000`
- 该默认值与 realtime cache 预热/保留窗口 `monitor.xtdata.prewarm.max_bars` 的默认值保持一致
- `/api/stock_data` 会把外部传入的 `barCount` 钳制到 `20000`，避免单次请求把 fallback 历史窗口无限放大
- realtime cache 命中时直接返回缓存尾部 `20000` 根；未命中时后端会按 `barCount` 放大历史查询窗口并在返回前截尾

页面当前支持：

- 周期按钮切换
- 历史日期回看
- 缠论结构面板
- Guardian 倍量价格三层编辑，按高到低蓝 / 红 / 绿实线展示
- 止盈价格三层编辑，按低到高蓝 / 红 / 绿虚线展示
- 图上默认直接显示 Guardian / 止盈价格横线
- 图例控制主图缠论层、额外周期叠加和价格横线分组
- 价格层级面板固定停靠在主图左侧，减少对最新 K 线的遮挡
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
- 检查十字星是否仍走自定义 `graphic` overlay；当前实现不应退回 ECharts 默认 axisPointer
- 检查十字星像素换算是否基于当前 grid + viewport；移出后应停留在最后位置，重新移入后应原位更新而不是叠加残影

### 缩放后 Y 轴不跟随

- 检查 chart option 里的 `dataZoom.start/end` 与 `chartViewport.xRange` 是否一致
- 检查 `chartViewport.yRange` 是否同步写回 `yAxis.min/max`
- 检查 Guardian / 止盈价格线是否已经并入 `priceGuideLines`

### 多周期结构边界错位

- 检查额外周期 payload 的时间戳是否合法且落在同一真实时间线上
- 检查 structure overlay data 的起止时间是否已经被裁剪到主图窗口左右边界

### 结构面板与主图时间不一致

- 检查 `endDate` 是否一致
- 检查结构接口是否拿到了旧缓存

### 默认 5 分钟图只显示最近几天

- 检查 `/api/stock_data` 请求是否带了 `barCount=20000`
- 检查对应 `CACHE:KLINE:<symbol>:5min` 是否存在
- realtime cache 命中时会直接显示缓存尾部窗口；未命中时会回退到历史查询
- 如果两个标的显示范围差异明显，优先确认是不是一个命中 Redis realtime cache、另一个走了历史回退

### 价格层级不显示或保存后没刷新

- 检查 `/api/subject-management/<symbol>` 是否返回了 `guardian_buy_grid_config` / `guardian_buy_grid_state`
- 检查 `/api/tpsl/takeprofit/<symbol>` 保存后是否成功回写三层价格
- 检查 `kline-slim-price-panel.mjs` 的校验是否拦截了非法价格顺序
- 检查 renderer scene 是否带上了 `priceGuideLines`
- 检查 legend 里 `Guardian 价格线` / `止盈价格线` 是否被手动关闭
