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
  - `/api/subject-management/<symbol>/must-pool`
  - `/api/position-management/symbol-limits/<symbol>`
  - `/api/order-management/stoploss/bind`
  - `/api/subject-management/<symbol>/guardian-buy-grid`
  - `/api/guardian_buy_grid_state`
  - `/api/tpsl/takeprofit/<symbol>`
  - `/api/tpsl/takeprofit/<symbol>/rearm`

## 依赖

- `get_data_v2`
- Redis realtime cache
- Chanlun structure service
- stock pool / must_pool / positions 等列表接口
- subject-management 聚合详情与 Guardian 配置/激活接口
- TPSL 止盈配置与 rearm 接口
- Gantt 热点理由接口

## 数据流

`symbol + period + endDate -> /api/stock_data -> KlineSlim 主图`

`symbol + period + endDate + barCount -> /api/stock_data -> realtime cache 命中时按 barCount 截尾，未命中时走历史拉取并尽量补足同样窗口`

`symbol + period + endDate -> /api/stock_data_chanlun_structure -> 缠论结构面板`

`symbol -> /api/subject-management/<symbol> -> 画线编辑浮层 + 标的设置浮层`

`Guardian / 止盈价格保存 -> subject-management / tpsl 接口 -> 图表价格横线重绘`

`Guardian / 止盈开关切换或全部开启/关闭 -> subject-management / tpsl 接口 -> 图表价格横线重绘`

`画线编辑拖拽 -> 本地价格草稿 -> subject-management / tpsl 接口 -> 图表价格横线重绘`

`标的设置保存 -> must-pool / symbol-limit / stoploss bind -> 刷新标的设置浮层`

`sidebar section -> 相关列表接口 / 热门理由接口 -> 侧边栏与 hover popover`

`holding -> /api/get_stock_position_list -> get_stock_positions() -> 优先按当前 instrument 信息补全/刷新名称 -> sidebar 标题`

当前图表渲染面已经拆成：

- `kline-slim.js`
  - 页面状态、路由、侧边栏、主图/多周期数据请求
  - 画线编辑浮层的 symbol 级加载、保存和重绘触发；首屏进入 `/kline-slim?symbol=...` 时就会立刻请求 `/api/subject-management/<symbol>`
  - 标的设置浮层的 symbol 级加载、保存和 stoploss 行内更新
  - `画线编辑` 模式切换、拖拽草稿更新和拖拽结束自动保存
- `kline-slim-price-panel.mjs`
  - Guardian / 止盈草稿状态、价格保存校验、批量开关保存与接口动作封装
- `kline-slim-subject-panel.mjs`
  - 标的设置浮层 detail 归一、草稿初始化与接口动作封装
- `kline-slim-chart-controller.mjs`
  - 维护显式 viewport 状态，统一同步 `xRange + yRange + yMode(auto|manual)`
  - scene 级更新使用完整 option 替换；datazoom 时会按当前 viewport 重建图层，确保 `xRange + yRange + series` 同步
  - 鼠标滚轮在主图 grid 内会按鼠标位置同时缩放 `X/Y` 两轴，并把 `yMode` 切到 `manual`
  - `yMode=auto` 时，Y 轴默认只根据当前可见主图 candles / 笔段 / 结构框 auto-fit；仅 `画线编辑` 模式或主图值为空时才把 Guardian / 止盈价格线并入 Y 轴范围
  - 第一次滚轮缩放进入 `manual` 时，会先按缩放后的可见主图重算 Y 基线，再按鼠标价格锚点同步缩放，避免远离主图的价格线把 Y 轴长期撑宽
  - 通过 `graphic` overlay 命中可编辑价格线，按当前 grid + viewport 做像素/价格坐标换算
- `kline-slim-chart-renderer.mjs`
  - 负责主 K 线、多周期笔/段/高级段图层以及结构框 overlay
  - 负责 Guardian / 止盈价格横线 overlay，并在 legend 中提供默认开启的独立开关
  - 负责 Guardian / 止盈可编辑横线 overlay 与拖拽把手绘制
  - 结构框不再使用 `markArea`，改为独立 custom overlay series
  - 图表只渲染当前 viewport 覆盖的 candles / line points / structure boxes，降低缩放和平移时的重绘成本
  - 主图使用连续交易槽位轴压缩午休/隔夜空白，同时保留真实时间戳做结构裁剪
  - 主图禁用 ECharts 默认 hover tooltip / axisPointer，改为自定义十字星 overlay
  - 自定义十字星保留横线、竖线、价格标签、日期标签；鼠标移出图表后停留在最后位置，重新移入后按当前位置实时更新且不保留残影
- `subject-price-guides.mjs`
  - 统一归一化 Guardian / 止盈草稿、校验规则以及价格线 / legend 分组生成逻辑
  - 统一提供价格草稿回填、顺序夹紧（Guardian `BUY-1 > BUY-2 > BUY-3`、止盈 `L1 < L2 < L3`）和编辑态横线数据

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
- Guardian 倍量价格三层编辑，支持逐层启停；激活层与仅展示层保留不同横线样式
- 止盈价格三层编辑，按低到高蓝 / 红 / 绿虚线展示
- `标的设置` 浮层编辑 `must_pool`、单标的仓位上限设置和 open buy lot 止损
- `must_pool` 基础配置当前只编辑止损价、首笔金额和常规金额；分类继续沿用当前真值，`forever` 固定写 `true`，页面不再暴露这两个项
- 单标的仓位上限当前只保留一个“单标的上限设置”输入；默认回填当前生效值 `effective_limit`
- 若保存值与系统默认值相同，后端会自动删除 symbol override；浮层不再提供 `use_default / 恢复默认 / 默认-单独切换`
- `画线编辑` 头部按钮当前为 `保存`，只保存 Guardian / 止盈 6 个价格值，不改运行态
- `Guardian 倍量价格` 与 `止盈价格` 区域各自提供 `全部开启 / 全部关闭`，批量保存三层 `开/关` 配置
- Guardian `buy_active` 与止盈 `armed_levels` 仍由系统维护，前端仅展示其影响，不提供手动设置入口
- `Guardian 倍量价格` 与 `止盈价格` 区块头部都会显示运行态汇总 `运行态 X/3`
- Guardian / 止盈每一层行内都会显示只读运行态；Guardian 文案为 `激活 / 未激活`，止盈文案为 `已布防 / 未布防`
- Guardian 摘要里的 `最近命中价` 表示最近一次真实命中的运行价，不是当前编辑框中的目标价；如果从未命中，摘要显示 `最近命中 未命中`
- 图上默认直接显示 Guardian / 止盈价格横线
- `画线编辑` 模式下可直接拖拽 Guardian / 止盈价格横线设置价格，拖拽结束自动保存
- `画线编辑` 的 Guardian / 止盈价格输入、拖拽草稿、图上标签和保存回写当前统一按小数点后三位处理
- 工具栏当前只保留 `画线编辑` 作为价格面板入口；不再单独提供 `价格层级` 按钮，浮层标题也统一为 `画线编辑`
- `重置视图` 会把当前图表从手动双轴缩放恢复到默认 `auto viewport`
- 图例控制主图缠论层、额外周期叠加和价格横线分组
- 价格层级面板以覆盖在主图上的浮层显示，不再挤占图表布局
- 价格层级浮层头部不再提供独立刷新按钮，也不再显示 symbol 下方的周期标签；Guardian / 止盈区也不再展示“蓝 / 红 / 绿实/虚线”等说明文字，行内状态字样与底部说明区也已移除，只保留价格输入、`开/关` 开关、分区批量开关和头部 `保存`
- 价格层级每一行当前使用独立的颜色 badge 列和编辑列；中等宽度下输入区会整行下移，避免价格输入框遮挡“蓝线 / 红线 / 绿线”标签
- 标的设置面板也以覆盖在主图上的浮层显示，不再挤占图表布局
- 标的设置浮层头部只保留 `保存/关闭` 动作；`按 buy lot 止损` 区不再直接裸露长 `buy_lot_id`，而是展示“第 N 笔买入”中文摘要、买入时间、当前系统 `avg_price`、当前系统仓位市值真值和剩余百分比，并把原始 ID 降级为辅助标签
- 缠论结构面板以覆盖在主图上的浮层显示
- `价格层级`、`标的设置` 与 `缠论结构` 按钮都支持再次点击关闭；三个大面板当前按互斥方式打开，避免彼此重叠
- 多个侧边栏分组统一使用两行紧凑布局：第一行显示 `名称(代码)`，第二行显示单条摘要信息
- `持仓股` 分组第二行只显示仓位金额，展示口径与 `/subject-management` 运行态列一致；不再显示持仓股数
- `must_pool / stock_pools / stock_pre_pools` 第二行显示来源/分类等单条摘要，不再堆叠多个标签块
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
- 检查 `chartViewport.yMode` 是否已经因为滚轮缩放切到 `manual`
- 检查 Guardian / 止盈价格线是否已经并入 `priceGuideLines`
- 检查页面首屏是否已经请求 `/api/subject-management/<symbol>` 并拿到真实价格线，而不是还停留在占位草稿
- 检查隐藏、未启用、inactive 或缺失运行态的价格线是否仍被误算进 Y 轴 auto-fit
- 如果不是 `画线编辑` 模式，确认默认 Y auto-fit 是否仍被远离主图的价格线主导；当前设计应优先贴合主图数据
- 若需要回到自动视图，使用页面上的 `重置视图`

### 多周期结构边界错位

- 检查额外周期 payload 的时间戳是否合法且落在同一真实时间线上
- 检查 structure overlay data 的起止时间是否已经被裁剪到主图窗口左右边界

### 结构面板与主图时间不一致

- 检查 `endDate` 是否一致
- 检查结构接口是否拿到了旧缓存
- 检查当前是否同时打开了另一个浮层；现状是价格层级与缠论结构面板互斥显示

### 默认 5 分钟图只显示最近几天

- 检查 `/api/stock_data` 请求是否带了 `barCount=20000`
- 检查对应 `CACHE:KLINE:<symbol>:5min` 是否存在
- realtime cache 命中时会直接显示缓存尾部窗口；未命中时会回退到历史查询
- 如果两个标的显示范围差异明显，优先确认是不是一个命中 Redis realtime cache、另一个走了历史回退

### 价格层级不显示或保存后没刷新

- 检查 `/api/subject-management/<symbol>` 是否返回了 `guardian_buy_grid_config` / `guardian_buy_grid_state`
- 检查 `/api/tpsl/takeprofit/<symbol>` 保存后是否成功回写三层价格
- 检查 `/api/guardian_buy_grid_state` 和 `/api/tpsl/takeprofit/<symbol>/rearm` 是否返回成功
- 检查 `kline-slim-price-panel.mjs` 的校验是否拦截了非法价格顺序
- 检查 renderer scene 是否带上了 `priceGuideLines` 和 `editablePriceGuideLines`
- 检查 legend 里 `Guardian 价格线` / `止盈价格线` 是否被手动关闭
- 检查 `画线编辑` 按钮是否被再次点击关闭；当前行为应为 toggle 而不是单向打开

### 标的设置浮层保存后未刷新

- 检查 `/api/subject-management/<symbol>` 是否返回了 `must_pool / position_limit_summary / buy_lots`
- 检查 `/api/position-management/symbol-limits/<symbol>` 是否成功写入当前希望生效的单标的上限；若保存值等于系统默认值，后端应删除 override
- 检查 `/api/order-management/stoploss/bind` 是否成功写入 buy lot 级止损
- 检查当前是否切换了 symbol；现状是 symbol 变化后会清空旧浮层 detail 并按当前 symbol 重新加载
- 如果 `按 buy lot 止损` 区再次出现长 ID 挤压布局，检查前端是否仍直接渲染 `row.buy_lot_id`，而不是 `buyLotDisplayLabel / buyLotMetaLabel / buyLotIdLabel`

### 价格线拖拽无效或拖拽后没保存

- 检查 `画线编辑` 是否已开启；当前只有编辑态 overlay 支持拖拽
- 检查 `subjectDetailLoading` / `savingPriceGuides` / `savingGuardianPriceGuides` / `savingTakeprofitGuides` 是否使编辑态被锁定
- 检查 `kline-slim-chart-controller.mjs` 是否命中了 `editablePriceGuideLines`，以及像素位置是否仍在当前主图 grid 内
- 检查 `subject-price-guides.mjs` 的顺序夹紧是否把目标价格限制在相邻层级之间
