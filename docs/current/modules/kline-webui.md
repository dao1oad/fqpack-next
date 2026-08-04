# Kline Web UI

## 职责

`/kline-slim` 是唯一 K 线承载页，负责单标的多周期图表、缠论结构、标的设置浮层、价格辅助线、CLX marker 和订单复盘覆盖层。顶部“每日选股”不再进入 KlineSlim 的 CLX 三栏模式，而是进入 `/daily-screening`；`/kline-slim` 只通过“看图”等标的跳转承载图表查看。订单账本相关部分使用 `position entry` 语义，CLX marker 只读取 `production_v1 / switch_opt=1` 的服务端事实。

## 入口

- 前端路由
  - `/kline-slim`
- 后端接口
  - `/api/stock_data`
  - `/api/stock_data_v2`
  - `/api/stock_data_chanlun_structure`
  - `POST /api/sync_stock_pools_from_tdx_self_select`
  - `/api/subject-management/<symbol>`
  - `/api/subject-management/<symbol>/guardian-buy-grid`
  - `/api/order-management/stoploss/bind`
  - `/api/tpsl/takeprofit/<symbol>`
  - `/api/tpsl/takeprofit/<symbol>/rearm`
  - `/api/position-review/symbols/<symbol>/timeline`
  - `/api/clx-daily-selection/batches`
  - `/api/clx-daily-selection/batches/latest`
  - `/api/clx-daily-selection/batches/<batch_id>/results`
  - `/api/clx-daily-selection/history/signals`
  - `/api/clx-daily-selection/model-catalog`

## 当前订单相关语义

- 标的设置浮层中的单笔止损对象已经是 open `entries`
- 保存止损时只提交 `entry_id`
- 标的设置浮层详情返回 `entries`，不再依赖 `buy_lots`
- 标的设置浮层当前固定合并三组卡片：
  - `止盈价格`
  - `Guardian 倍量价格`
  - `单笔止损`
- 图表页不再保留独立的“画线编辑”或“单笔止损”浮层；工具栏只保留一个 `标的设置` 入口
- 标的设置浮层不再暴露 `must_pool`、止损价、首笔金额、常规金额和单标的仓位上限输入区
- 单笔止损卡片里的 entry 止损摘要当前显示买入价、原始数量、剩余数量与比例、该笔剩余市值以及买入时间；为节省横向空间，买入股数和剩余股数展示为 `万股`，且买入价不再显示 `买入价:` 标签
- 单笔止损卡片里的每个 entry 整行 hover 都会显示 `切片明细`；浮层只展示当前 entry 的 open slices，不增加额外按钮，也不展开 `aggregation_members`
- “剩余市值”当前优先显示后端按有效 `latest_price * remaining_quantity` 计算的结果；若 `latest_price <= 0` 或缺失，则先用 `xt_positions.market_value / quantity` 推导有效最新价；若仍不可用，再回退到均价口径
- `KlineSlim` 只保留 entry 摘要，不在浮层内展开完整 `aggregation_members / entry_slices`；完整切片检查当前仍依赖 `subject-management` 读模型与组件文件，但独立前端路由已移除
- 图表价格引导里的持仓参考线已经改成 `entry` 语义，对外文案是“持仓入口线”
- 持仓股侧边栏排序与 SubjectManagement、PositionManagement 保持一致，按持仓金额从大到小排序

## 当前页面结构

- 三栏统一布局
  - 左栏：持仓、`stock_pools`、`must_pool`、预选池和 CLX 批次/scope、完整筛选条件、cursor 结果列表；分组标题点击即展开/收起，不再额外展示“展开/收起”文字；`stock_pools` 分组提供 `同步自选股` 按钮，可从当前 TDX home 的 `T0002/blocknew/ZXG.blk` 去重追加到 `freshquant.stock_pools`，并在左栏展示时与持仓股去重
  - 中栏：当前标的主图与多周期结构
  - 右栏：CLX 信号显示控制、时间轴和证据详情
- 标的设置浮层
  - 止盈价
  - Guardian 阶梯价
  - entry stoploss
  - entry row hover slice 明细
- 缠论结构浮层
- 可选交易复盘模式
  - 主 K 线保留为唯一价格图；关联信号和订单聚合成交标记叠加在价格层
  - 策略应有量、实际成交量和连续持仓在同一时间轴的下方轨道显示
  - 可跳转到 `/position-review?symbol=<symbol>` 查看完整复盘工作台
- 右侧 `CLX 信号工作台`
  - `显示控制`：历史范围、同日 marker 聚合/逐条、模型和条件筛选
  - `信号时间轴`：按触发日列出当前可见 marker，点击后聚焦图表
  - `信号详情`：展示 raw、方向、entrypoint/条件和 `condition_evidence`
- CLX 图层
  - 日线信号按当前日/周/月 bar 重新锚定
  - renderer 生成独立 `clx-signal-<sceneScopeId>` ECharts scatter series
  - 同日聚合 marker 使用 count、方向和模型颜色生成 pin/diamond；controller 负责点击、highlight 与 tooltip


## 当前缠论图层行为

- 多周期结构线宽由周期 factor 推导，但所有结构线以约 `7.5px` 封顶，高级绿色等结构线不会超过当前红色基准宽度。
- 同色中枢边框宽度与同色结构线宽一致；颜色、z-index、数据点、中枢填充透明度、价格辅助线、CLX marker 和订单复盘线保持各自既有语义。
- K 线主周期切换时，缠论结构 legend 只保留当前主周期打开，其他周期全部关闭；用户手动点击其他周期 legend 后才加载并叠加对应周期。价格辅助线、订单复盘和 CLX 信号 legend 不随主周期切换重置。

## 当前数据流

- `symbol -> /api/subject-management/<symbol>`
  - 读取标的设置浮层里的单笔止损 detail，其中仍带 `mustPool` / `positionLimit` 只读信息
- `保存单笔止损`
  - `entry stoploss bind`
- `保存标的设置`
  - Guardian 配置
  - takeprofit profile / rearm
- `交易复盘模式`
  - K 线加载完成后，按当前主图时间窗请求 `/api/position-review/symbols/<symbol>/timeline`
  - 前端只消费订单级 `events` 和连续 `position_series`；成交笔数和均价仅作为订单聚合字段，不渲染逐笔 fill。窗口请求中的实际成交量只代表当前主图窗口内成交
  - 服务未部署或返回 `404` 时，复盘层显示明确的不可用状态，不会退回旧请求级 `reviews` 并伪装为订单级复盘
- `stock_pools` 左栏
  - 列表来自 `/api/get_stock_pools_list`，前端会按 6 位代码过滤掉已在“持仓股”分组展示的标的；点击任一标的后使用同一 K 线加载链路，因此 `15min / 30min` 兼容别名与实时缓存 QFQ 未就绪回退对所有左侧列表标的生效
  - `同步自选股` 调用 `POST /api/sync_stock_pools_from_tdx_self_select?days=30`，只把非持仓且未存在的新增标的写入 `stock_pools`，不写 `must_pool`，不触发下单；同步完成后刷新 `stock_pools` 列表并提示新增/已存在/持仓去重数量
- `CLX 信号工作台`
  - 按当前 symbol、asset type、日线 endDate（缺省时由服务端解析最新交易日）、barCount、模型/条件请求 `/api/clx-daily-selection/history/signals`
  - 只在 `profile=production_v1`、`switch_opt=1` 且 `future_function_guard.passed=true` 时把 marker 交给 chart renderer
  - URL 以共享 `clxScope`、左栏 `clxFilter*`、当前 symbol/asset type、period/endDate 与右栏 `clxModels / clxConditions / clxMarkerMode` 分别保存状态；cursor 只属于当前列表请求链，刷新后按已恢复的筛选从首批重新加载
  - 右栏模型/条件只改变已经计算的 marker 可见性，不重新定义或重算服务端信号，也不改写左栏的结果筛选；左栏模型/条件改变时同样保留右栏显示选择

## 当前边界

- `KlineSlim` 继续负责 Guardian / takeprofit 的编辑入口
- `entry stoploss` 当前合并在同一个标的设置浮层里编辑
- 图表页不再直接展示长 `buy_lot_id`
- 交易复盘是可选只读覆盖层，不改变 K 线主图、订单账本、持仓真值或策略执行逻辑
- Kline 图表页不写 batch、partition、选股结果或策略参数；每日选股的 CLX 18 模型工作区位于 `/daily-screening?tab=clx`，结果行“看图”跳转到 `/kline-slim` 查看单标的图表。
- `/kline-slim` 是图表正式入口；`/daily-screening` 是纯选股工作台，不展示主体 K 线；`/clx-daily-screening` 只执行兼容 query 映射并重定向到 `/daily-screening?tab=clx`。
- partial 只允许明确展示已完成 partition，不能冒充 final；跨资产统计仍由 CLX finalizer 的完整 batch 提供
- `/daily-screening` 综合交集的 12 模型结果不混入 Kline CLX marker 图层
- 信号仅在后端给出明确关联时显示；无关联信号不依据时间或价格补配
- 同一策略请求无法把应有量可靠分给多个订单时，数量轨显示证据不足而非重复的策略数量；同秒跨订单的仓位先后无法证实时也明确标记为不确定

## 排障

### 标的设置里的单笔止损保存后没刷新

- 查 `/api/subject-management/<symbol>` 是否返回 `entries`
- 查 `/api/order-management/stoploss/bind` 是否成功
- 查 `om_entry_stoploss_bindings`

### 持仓股侧边栏顺序异常

- 查返回的持仓金额字段
- 当前排序口径是 `position_amount -> market_value -> amount`

### 图表未显示持仓入口线

- 查 `/api/subject-management/<symbol>` 是否返回 `entries`
- 查 `subject-price-guides` 是否从 `entry_price / remaining_quantity` 生成价格线

### 左栏 CLX 标的为空

- 查 `/api/clx-daily-selection/batches/latest` 是否已有 `published/not_required` final
- 若只存在单侧完成，显式查 `/api/clx-daily-selection/batches/latest?include_partial=1`，确认页面显示的是 partial 而不是完整结果
- 查当前 scope 的 `/batches/<batch_id>/results` 是否包含目标资产 partition
- 查左栏“仅当前筛选”是否把模型或条件过滤为空

### 从旧 CLX 地址进入后没有恢复筛选

- 确认浏览器最终路由为 `/daily-screening?tab=clx`；`/clx-daily-screening` 只应短暂作为兼容入口。
- 核对旧 `scope_id / asset_types / model_keys / condition_keys` 是否映射到 CLX 18 模型工作区的 `scope_id / asset_types / model_keys / condition_keys`。
- 确认 redirect 保留无关 query，并移除旧 Kline 专用 `clxScreening / clxWorkbench / period` 参数。

### 点击筛选结果后 K 线日期不一致

- 查所选 scope 是否有规范 `tradeDate`
- 确认结果选择把 `scope.tradeDate` 写入 URL `endDate`，随后主 K 线与 `/history/signals` 请求都使用该值
- 若用户之后手工改变 `endDate`，只更新当前图表/历史窗口，不回写或伪造 scope 交易日

### 图上没有 CLX marker

- 直接请求 `/api/clx-daily-selection/history/signals?symbol=<symbol>&assetType=<stock|etf>&period=1d&endDate=<date>`
- 确认 `calculation_profile.id=production_v1`、`switch_opt=1`、`future_function_guard.passed=true`
- 确认 marker 的 `trigger_date` 落在当前 K 线日期范围，模型/条件筛选没有排除它
- 查 chart scene 的 `clxSignals.hasData` 和最终 option 是否包含 `clx-signal-<sceneScopeId>`；只加载了 marker 列表但没有 scatter series 不算已绘制

### marker 点击后时间轴或详情没有联动

- 查 series data 是否保留 `clxGroup`
- 查 controller 的 `handleChartClick` 是否收到 `seriesId` 以 `clx-signal-` 开头的事件
- 查 `clxSelectedMarkerId` 是否同时传回 renderer 与右侧工作台
