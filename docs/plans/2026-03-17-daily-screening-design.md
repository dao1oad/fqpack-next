# 每日选股工作台设计

## 背景

当前仓库里同时存在两条“盘后选股”能力：

- `stock screening --model clxs`
- `stock screening --model chanlun`

它们已经能实际运行，但当前只暴露 CLI 入口，缺少正式前端页面。用户希望新增一个“每日选股”页面，既能直接发起每日扫描，又能在同一页面里理解两种模型的输入、参数、实时进度、命中结果和落库结果。

另外，`stock_pre_pools` 是共享集合。当前不同来源的选股结果主要靠 `category` 区分，但现有 `save_a_stock_pre_pools()` 没有稳定的顶层 `remark` 写入能力，也不能在相同 `code + category` 下继续按来源隔离记录。这会导致：

- 页面来源和现有 CLI 来源难以区分
- `chanlun` 从共享 `stock_pre_pools` 再次扫描时，输入来源容易混杂
- 同一 `code + category` 可能被不同来源互相覆盖

## 目标

- 新增一个正式前端页面 `/daily-screening`，支持实际发起 `clxs` 和 `chanlun` 每日选股扫描。
- 页面通过 SSE 实时接收扫描进度、命中结果、错误和最终摘要。
- 页面按后端返回 schema 动态渲染参数，不把模型参数写死在前端。
- 页面能展示“本次扫描结果”和“已落库 pre_pool 结果”，并支持打开 K 线、加入 `stock_pools`、删除预选结果。
- `stock_pre_pools` 对页面新增来源使用 `remark` 作为来源真值，并在 `extra` 中保存更细的运行上下文。
- `chanlun` 页面必须明确区分输入来源，避免默认把共享 `stock_pre_pools` 全量混扫当成唯一入口。

## 非目标

- 不在第一期做定时调度、自动每日运行或自动归档历史会话。
- 不在第一期做跨进程任务恢复；扫描会话只保证当前 API 进程存活期间有效。
- 不在第一期把 CLI 的所有输出（如 HTML 报表）一比一搬到前端。
- 不在第一期做多用户隔离。
- 不在第一期直接编辑 `must_pool` 高级参数；相关操作只保留“加入 stock_pools”和删除 `pre_pool` 结果。

## 当前真值边界

### 1. CLXS 选股

入口：

- [freshquant.command.stock.stock_screen_command](/D:/fqpack/freshquant-2026.2.23/.worktrees/stock-selection-analysis-20260317/freshquant/command/stock.py#L141)
- [freshquant.screening.strategies.clxs.ClxsStrategy](/D:/fqpack/freshquant-2026.2.23/.worktrees/stock-selection-analysis-20260317/freshquant/screening/strategies/clxs.py#L34)

当前真实逻辑：

- 数据源是全市场股票列表，且过滤掉名称包含 `ST` 的股票。
- 单票模式按 `code` 过滤，不需要完整 `symbol`。
- 每只股票取日线数据。
- 调用 `fqcopilot.fq_clxs` 和 `fqchan04.fq_recognise_bi`。
- 仅当最新信号 `sigs[-1] > 0` 时命中。
- 止损价来自最近笔底的最低价。
- 结果按 `code + fire_date` 去重。
- 默认可写入 `stock_pre_pools`，默认分类是 `CLXS_<model_opt>`。

### 2. Chanlun Service 选股

入口：

- [freshquant.command.stock.stock_screen_command](/D:/fqpack/freshquant-2026.2.23/.worktrees/stock-selection-analysis-20260317/freshquant/command/stock.py#L141)
- [freshquant.analysis.select_cli.select_stock](/D:/fqpack/freshquant-2026.2.23/.worktrees/stock-selection-analysis-20260317/freshquant/analysis/select_cli.py#L14)
- [freshquant.screening.strategies.chanlun_service.ChanlunServiceStrategy](/D:/fqpack/freshquant-2026.2.23/.worktrees/stock-selection-analysis-20260317/freshquant/screening/strategies/chanlun_service.py#L25)

当前真实逻辑：

- 单票模式直接扫描一个 `symbol`。
- 批量模式默认从共享 `stock_pre_pools` 读取股票输入，并按 `code` 去重。
- 默认周期是 `30m / 60m / 1d`。
- 当前真正启用的信号类型只有 6 个，定义在 [CHANLUN_SIGNAL_TYPES](/D:/fqpack/freshquant-2026.2.23/.worktrees/stock-selection-analysis-20260317/freshquant/screening/signal_types.py#L17)。
- 原始信号既有 `BUY_LONG` 也有 `SELL_SHORT`。
- 最终每日选股口径只保留最近 N 天且 `position == BUY_LONG` 的结果。
- 结果按 `code + fire_date` 去重。
- 若启用写入，可写入 `stock_signals`、`stock_pools`、`stock_pre_pools`。

### 3. stock_pre_pools 共享集合

现状：

- 主要共享集合为 `stock_pre_pools`。
- 旧逻辑的写入 helper 是 [save_a_stock_pre_pools](/D:/fqpack/freshquant-2026.2.23/.worktrees/stock-selection-analysis-20260317/freshquant/signal/a_stock_common.py#L100)。
- 该 helper 当前以 `code + category` 为 upsert 真值。
- 该 helper 会写 `extra`，但当前不会稳定写顶层 `remark`。

影响：

- 不能仅靠 `remark` 区分来源。
- 页面新增来源如果继续只按 `code + category` 写，会和现有记录互相覆盖。

## 页面结构

新增页面：`/daily-screening`

前端入口：

- 在 [MyHeader.vue](/D:/fqpack/freshquant-2026.2.23/.worktrees/stock-selection-analysis-20260317/morningglory/fqwebui/src/views/MyHeader.vue#L1) 增加“每日选股”

页面采用高密度工作台布局，单屏固定 4 个区域：

1. 顶部摘要条
2. 左侧参数配置区
3. 中间 SSE 实时扫描流
4. 右侧结果与规则说明区

### 顶部摘要条

展示：

- 当前模型
- 当前扫描状态
- `scan_id`
- 已扫描 / 总数
- 命中数
- 开始时间 / 结束时间 / 耗时
- 当前来源 remark

### 左侧参数配置区

由后端 schema 驱动渲染。

#### 公共参数

- `model`
- `days`
- `save_pre_pools`
- `output_category`

#### CLXS 参数

- `code`
- `wave_opt`
- `stretch_opt`
- `trend_opt`
- `model_opt`

页面会动态展示这些参数的含义，例如：

- `8` = MACD 背驰
- `9` = 中枢回拉
- `12` = V 反
- `10001` = 默认 CLXS

#### Chanlun 参数

- `input_mode`
  - `single_code`
  - `all_pre_pools`
  - `category_filtered_pre_pools`
  - `remark_filtered_pre_pools`
- `code`
- `period_mode`
  - `all`
  - `30m`
  - `60m`
  - `1d`
- `pre_pool_category`
- `pre_pool_remark`
- `max_concurrent`
- `save_signal`
- `save_pools`
- `pool_expire_days`

前端根据当前模型和当前输入模式动态显示或隐藏字段。

### 中间实时扫描流

通过 SSE 展示结构化事件流，不直接展示原始 stdout。

实时区包含：

- 当前进度
- 当前股票
- 非致命错误
- 原始命中
- 进入本次结果表的有效命中
- 最终完成摘要

### 右侧结果区

分成三个部分：

1. 本次结果
2. 已落库 pre_pool
3. 模型规则说明

#### 本次结果

实时展示当前 `scan_id` 的有效命中结果，字段按模型统一归一：

- `code`
- `name`
- `model`
- `period`
- `signal_type`
- `signal_name`
- `fire_time`
- `price`
- `stop_loss_price`
- `category`
- `remark`

#### 已落库 pre_pool

展示本页来源写入到 `stock_pre_pools` 的结果，支持按以下条件过滤：

- `remark`
- `model`
- `category`
- `run_id`

支持操作：

- 打开 K 线
- 加入 `stock_pools`
- 删除该记录

#### 模型规则说明

固定展示当前模型的真实逻辑、输入来源、去重规则、落库规则。

## 后端架构

新增独立 daily-screening 控制层，不混入旧 `stock` / `gantt` 路由：

- `freshquant/daily_screening/session_store.py`
- `freshquant/daily_screening/service.py`
- `freshquant/rear/daily_screening/routes.py`

并在 API Server 注册新蓝图。

### 1. Schema 接口

`GET /api/daily-screening/schema`

返回：

- 模型列表
- 每个模型的字段 schema
- 默认值
- 枚举选项
- 当前可用 `pre_pool_categories`
- 当前可用 `pre_pool_remarks`

### 2. Run 创建接口

`POST /api/daily-screening/runs`

职责：

- 校验参数
- 创建 `scan_id`
- 初始化会话状态
- 启动后台线程

### 3. SSE 接口

`GET /api/daily-screening/runs/<scan_id>/stream`

职责：

- 输出 `text/event-stream`
- 回放已产生事件
- 持续推送新事件
- 会话完成后关闭连接

### 4. 结果查询接口

- `GET /api/daily-screening/runs/<scan_id>`
- `GET /api/daily-screening/pre-pools`

其中 `pre-pools` 支持：

- `remark`
- `model`
- `category`
- `run_id`

## SSE 事件模型

统一事件类型：

- `started`
- `universe`
- `progress`
- `hit_raw`
- `accepted`
- `dedup_skipped`
- `persisted`
- `summary`
- `completed`
- `error`
- `heartbeat`

说明：

- `hit_raw` 表示模型原始命中
- `accepted` 表示进入“本次每日选股结果”的有效命中
- `persisted` 表示已经落到 `stock_pre_pools` / `stock_signals` / `stock_pools`

## 结果写入与来源隔离

### 顶层 remark

页面新增来源统一写：

- `daily-screening:clxs`
- `daily-screening:chanlun`

### extra 字段

页面新增来源写入：

- `screening_run_id`
- `screening_model`
- `screening_params`
- `screening_input_mode`
- `screening_signal_type`
- `screening_signal_name`
- `screening_period`
- `screening_source_scope`

### save_a_stock_pre_pools 修改原则

需要补齐：

- 支持写入顶层 `remark`
- 当传入 `remark` 时，upsert query 改为 `code + category + remark`
- 不传 `remark` 时保持现有 `code + category` 行为不变

这样可以同时满足：

- 旧 CLI / 老页面行为不变
- 新页面来源可隔离
- 相同 `code + category` 但不同页面来源可以共存

## 扫描执行策略

页面不直接包 `subprocess` 调 CLI，而是直接调用策略类：

- `ClxsStrategy`
- `ChanlunServiceStrategy`

原因：

- 可以拿到结构化 `ScreenResult`
- 可以逐条把命中通过 SSE 推给前端
- 可以在页面中准确解释每条结果来自哪个模型和信号

为支持 SSE，需要给策略增加可选运行回调，不改变现有 CLI 默认行为。

## 风险与约束

### 1. Chanlun 输入来源混扫

风险：

- 默认共享 `stock_pre_pools` 里来源复杂

约束：

- 页面推荐默认使用 `remark` 或 `category` 过滤模式
- “全量 pre_pool 扫描”只作为高级模式保留

### 2. 长任务占用 API 进程

风险：

- 全市场 `CLXS` 扫描可能耗时较长

约束：

- 第一阶段接受单会话内存态管理
- 后续若需要再做队列化或外部 worker

### 3. SSE 断线

约束：

- 前端断线后可以通过 `GET /runs/<scan_id>` 拉当前快照
- 真正长期真值是落库结果，不是 SSE 会话

## 测试策略

后端：

- `save_a_stock_pre_pools` remark 行为
- schema 接口
- run 创建与参数校验
- pre_pool 查询过滤
- SSE 事件输出

策略：

- `CLXS` 回调与结果归一
- `Chanlun` 回调、输入过滤与结果归一

前端：

- schema 驱动表单
- 模型切换与参数动态显隐
- SSE 事件驱动状态更新
- Header 导航
- 结果过滤与表格动作

文档：

- `docs/current/**` 新增“每日选股”当前事实文档
- 同步路由和接口文档
