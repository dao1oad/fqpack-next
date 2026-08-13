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
- `POST /api/pools/must/sync-from-tdx`（按 `blocknew.cfg` 解析「待买」分组真实文件名，回退 `待买.blk`）
  - `/api/subject-management/<symbol>`
  - `/api/subject-management/<symbol>/guardian-buy-grid`
  - `/api/tpsl/takeprofit/<symbol>`
  - `/api/tpsl/takeprofit/<symbol>/rearm`
  - `/api/position-review/symbols/<symbol>/chart`
  - `/api/position-review/events/<event_id>/conditions`
  - `/api/clx-daily-selection/batches`
  - `/api/clx-daily-selection/batches/latest`
  - `/api/clx-daily-selection/batches/<batch_id>/results`
  - `/api/clx-daily-selection/history/signals`
  - `/api/clx-daily-selection/model-catalog`

## 当前订单相关语义

- 止损绑定、全仓止损价与单笔止损编辑已随 Issue #603 整体下线
- 标的设置浮层详情返回 `entries`，不再依赖 `buy_lots`
- 标的设置浮层当前固定合并三组卡片：
  - `止盈价格`
  - `Guardian 买入仓位上限`
  - `Guardian 买入价格`
- 图表页不再保留独立的“画线编辑”浮层；工具栏只保留一个 `标的设置` 入口
- 标的设置浮层不再暴露 `must_pool`、首笔金额和常规金额输入区
- `Guardian 买入仓位上限` 按 `CAP-1 / CAP-2 / CAP-3` 编辑 BUY-1/2/3 到价前允许达到的最大仓位金额；仅在服务端值缺失或非法时用 `200000 / 350000 / 500000` 初始化前端草稿，页面加载不会自动写库
- 标的总仓位上限直接读写 Position Management 的 `pm_configs.thresholds.single_symbol_position_limit` / `symbol_position_limits.overrides.<symbol>` 真值，不建立第二份配置；该值独立保存、独立恢复默认，不并入 Guardian 顶部保存操作
- “剩余市值”当前优先显示后端按有效 `latest_price * remaining_quantity` 计算的结果；若 `latest_price <= 0` 或缺失，则先用 `xt_positions.market_value / quantity` 推导有效最新价；若仍不可用，再回退到均价口径
- `KlineSlim` 只保留 entry 摘要，不在浮层内展开完整 `aggregation_members / entry_slices`；完整切片检查当前仍依赖 `subject-management` 读模型与组件文件，但独立前端路由已移除
- 图表价格引导里的持仓参考线已经改成 `entry` 语义，对外文案是“持仓入口线”
- 持仓股侧边栏排序与 SubjectManagement、PositionManagement 保持一致，按持仓金额从大到小排序
- 可选“交易复盘”覆盖层消费 `/api/position-review/symbols/<symbol>/chart` 只读投影，在唯一 K 线主图价格层渲染订单 marker：
  - 颜色只表达方向：买入红色、卖出绿色（同时带 `B` / `S` 文字）
  - 形状只表达信号类型：由服务端 `signal_type_registry` 提供 `signal_type / signal_family / signal_label / marker_symbol`
  - verdict 只以边框/透明度/`!` 编码：`FAIL` 深色加粗描边并显示 `!`，`INSUFFICIENT_EVIDENCE` 降透明度，`NOT_APPLICABLE` 低透明度空心
  - marker 锚定首次成交 bar 与订单加权成交均价；跨 bar fill 用同方向颜色细区间线表示成交跨度
  - hover 一次性展示全部信息（订单摘要、信号完整详情、全部条件阈值、成交、持仓影响、数据质量），conditions 懒加载并缓存；点击 marker 固定订单并进入 `/position-review` 右侧证据面板
  - 不再在 K 线下方绘制策略应有量 / 实际成交量 / 连续持仓三轨附图；旧 `/timeline` 接口已移除

## 当前页面结构

- 工具栏首位提供 `← 返回运维` 按钮，跳转到 `/ops-console`（包含全局导航栏），保证图表页可随时回到导航入口
- 三栏统一布局
  - 左栏：持仓、`stock_pools`、`must_pool`、预选池和 CLX 批次/scope、完整筛选条件、cursor 结果列表；分组标题点击即展开/收起，不再额外展示“展开/收起”文字；`stock_pools` 分组提供 `同步自选股` 按钮，可从当前 TDX home 的 `T0002/blocknew/ZXG.blk` 去重追加到 `freshquant.stock_pools`，`must_pool` 分组提供 `同步待买` 按钮，可从 `T0002/blocknew/待买.blk` 导入到 `freshquant.must_pool`，并在左栏展示时与持仓股去重
  - 中栏：当前标的主图与多周期结构
  - 右栏：CLX 信号显示控制、时间轴和证据详情
- 标的设置浮层
  - 止盈价
  - Guardian BUY-1/2/3 仓位上限与对应买入价
  - 单标的总仓位上限
  - entry row hover slice 明细
- 缠论结构浮层
- 可选交易复盘模式
  - 主 K 线保留为唯一价格图；关联信号和订单聚合成交标记叠加在价格层
  - 不再在 K 线下方绘制策略应有量 / 实际成交量 / 连续持仓三轨附图
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

- 缠论结构线（笔/段/高级别段及其中枢边框）统一使用固定粗细 `1.2px`，与 1m 白色笔线一致，不再按颜色或周期区分线宽。
- 中枢边框宽度与结构线宽一致；颜色、z-index、数据点、中枢填充透明度、价格辅助线、CLX marker 和订单复盘线保持各自既有语义。
- K 线主周期切换时，缠论结构 legend 只保留当前主周期打开，其他周期全部关闭；用户手动点击其他周期 legend 后才加载并叠加对应周期。价格辅助线、订单复盘和 CLX 信号 legend 不随主周期切换重置。

## 当前数据流

- `symbol -> /api/subject-management/<symbol>`
  - 读取标的设置浮层 detail，其中仍带 `mustPool` / `positionLimit` 只读信息
- `保存标的设置`
  - Guardian 配置
  - takeprofit profile / rearm
- `保存 Guardian 买入仓位上限`
  - `max_position_amounts` 仍以“元”为单位提交，不使用“万元”作为 v-model
- `保存/恢复单标的总仓位上限`
  - 复用 Position Management 现有接口与同一 Mongo 真值；恢复默认时先刷新系统默认值，再提交并刷新当前生效值
- `交易复盘模式`
  - K 线加载完成后请求 `/api/position-review/symbols/<symbol>/chart` 只读投影（不传窗口参数，主图自行按可视窗口过滤 marker）
  - marker 悬浮框一次性展示全部信息（订单摘要、信号完整详情、全部条件阈值、成交、持仓影响、数据质量）；conditions 按 `event_id` 通过 `/api/position-review/events/<event_id>/conditions` 懒加载并缓存
  - 服务未部署或返回 `404` 时，复盘层显示明确的不可用状态，不会退回旧请求级 `reviews` 并伪装为订单级复盘
- `stock_pools` 左栏
  - 列表来自 `/api/get_stock_pools_list`，前端会按 6 位代码过滤掉已在“持仓股”分组展示的标的；点击任一标的后使用同一 K 线加载链路，因此 `15min / 30min` 兼容别名与实时缓存 QFQ 未就绪回退对所有左侧列表标的生效
  - `同步自选股` 调用 `POST /api/sync_stock_pools_from_tdx_self_select?days=30`，以后端读取的 TDX `ZXG.blk` 有效标的减去当前持仓作为唯一集合，覆盖 `stock_pools`；旧集合外记录会删除，同步完成后刷新列表并提示同步、移除旧标的和持仓去重数量
- `must_pool` 左栏
  - 列表来自 `/api/get_stock_must_pools_list`，点击任一标的后使用同一 K 线加载链路
- `同步待买` 调用 `POST /api/pools/must/sync-from-tdx?days=30`，以后端读取的 TDX「待买」分组（经 `blocknew.cfg` 解析真实文件名，当前宿主机为 `DM.blk`）有效标的减去当前持仓覆盖刷新 `must_pool`；已存在记录保留交易参数并合并 `tdx_must_pool` provenance，分组外既有记录会被删除，新代码资金参数由 `import_pool` 兜底解析（不阻断同步），同步完成后刷新列表并提示同步、删除、持仓排除、无效与失败数量
- `#589`：分组有效代码为 0 时默认返回 `400 + code=empty_group` 阻断；前端（KlineSlim 与
  `/daily-screening` 必选股票池）识别后弹确认框，确认后带 `allow_empty=1` 重试清空
  `must_pool`；文件缺失/编码失败仍直接失败提示，不进入确认流程
- `CLX 信号工作台`
  - 按当前 symbol、asset type、日线 endDate（缺省时由服务端解析最新交易日）、barCount、模型/条件请求 `/api/clx-daily-selection/history/signals`
  - 只在 `profile=production_v1`、`switch_opt=1` 且 `future_function_guard.passed=true` 时把 marker 交给 chart renderer
  - URL 以共享 `clxScope`、左栏 `clxFilter*`、当前 symbol/asset type、period/endDate 与右栏 `clxModels / clxConditions / clxMarkerMode` 分别保存状态；cursor 只属于当前列表请求链，刷新后按已恢复的筛选从首批重新加载
  - 右栏模型/条件只改变已经计算的 marker 可见性，不重新定义或重算服务端信号，也不改写左栏的结果筛选；左栏模型/条件改变时同样保留右栏显示选择

## 当前边界

- `KlineSlim` 继续负责 Guardian / takeprofit 的编辑入口
- 图表页不再直接展示长 `buy_lot_id`
- 交易复盘是可选只读覆盖层，不改变 K 线主图、订单账本、持仓真值或策略执行逻辑
- Kline 图表页不写 batch、partition、选股结果或策略参数；CLX 18 模型的批次、筛选与“导入通达信”能力由图表页内 `ClxSelectionPanel` 承载，结果行“看图”回到 `/kline-slim` 查看单标的图表。
- `/kline-slim` 是图表正式入口；`/daily-screening` 是 CLX 基本面评价工作台（排序 / 详情 / 统计三区），不展示主体 K 线；`/clx-daily-screening` 只执行兼容 query 映射并重定向到 `/daily-screening?tab=clx`。
- partial 只允许明确展示已完成 partition，不能冒充 final；跨资产统计仍由 CLX finalizer 的完整 batch 提供
- `/daily-screening` 基本面评价产物（`/data/clx-evaluator/**`）不混入 Kline CLX marker 图层；marker 只消费 CLX 日线选股信号服务
- 信号仅在后端给出明确关联时显示；无关联信号不依据时间或价格补配
- 同一策略请求无法把应有量可靠分给多个订单时，数量轨显示证据不足而非重复的策略数量；同秒跨订单的仓位先后无法证实时也明确标记为不确定

## 排障

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
