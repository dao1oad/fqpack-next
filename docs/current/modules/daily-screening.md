# 每日选股

## 职责

每日选股模块把原来只在 CLI 可用的两条盘后选股链路正式收口到 Web UI：

- `stock screen clxs`
- `stock screen chanlun`

它既负责直接发起扫描，也负责把扫描过程通过 SSE 实时推到页面，并把页面来源稳定落库到共享 `stock_pre_pools`。

当前页面默认入口是“全链路”模式：

- 先一键跑完 `CLXS` 全模型
- 再用本次 `CLXS` 落库结果作为 `chanlun` 输入源
- 最后在页面内按“分支按钮 + 模型按钮”做二次筛选，不重新发起扫描

## 入口

- 前端路由
  - `/daily-screening`
- 前端页面
  - `DailyScreening.vue`
- 后端接口
  - `/api/daily-screening/schema`
  - `/api/daily-screening/runs`
  - `/api/daily-screening/runs/<run_id>`
  - `/api/daily-screening/runs/<run_id>/stream`
  - `/api/daily-screening/pre-pools`
  - `/api/daily-screening/pre-pools/stock-pools`
  - `/api/daily-screening/pre-pools/delete`
- 后端服务
  - `freshquant.daily_screening.service`
  - `freshquant.daily_screening.session_store`

## 依赖

- `freshquant.screening.strategies.clxs.ClxsStrategy`
- `freshquant.screening.strategies.chanlun_service.ChanlunServiceStrategy`
- `stock_pre_pools`
- `stock_pools`
- 可选 `stock_signals`

## 数据流

`页面参数 -> /api/daily-screening/runs -> DailyScreeningService -> all / CLXS / chanlun strategy`

`strategy hooks -> session store -> /stream SSE -> 页面事件流 / 本次结果`

`accepted results -> DailyScreeningService 自定义落库 -> stock_pre_pools`

`页面预选池行 -> /pre-pools/stock-pools -> stock_pools`

## 页面行为

- 参数由 `/schema` 动态返回，前端不把模型参数写死。
- 页面支持三种运行模式：
  - `全链路`
  - `CLXS`
  - `chanlun`
- `全链路` 支持：
  - `days`
  - `code`
  - `wave_opt`
  - `stretch_opt`
  - `trend_opt`
  - `clxs_model_opts`
  - `chanlun_signal_types`
  - `chanlun_period_mode`
  - `chanlun_max_concurrent`
  - `save_pre_pools`
- `CLXS` 支持：
  - `days`
  - `code`
  - `wave_opt`
  - `stretch_opt`
  - `trend_opt`
  - `model_opts`
  - `save_pre_pools`
  - `output_category`
- `chanlun` 支持：
  - `days`
  - `input_mode`
    - `single_code`
    - `all_pre_pools`
    - `category_filtered_pre_pools`
    - `remark_filtered_pre_pools`
  - `period_mode`
  - `pre_pool_category`
  - `pre_pool_remark`
  - `signal_types`
  - `max_concurrent`
  - `save_signal`
  - `save_pools`
  - `save_pre_pools`
  - `pool_expire_days`
- 页面会显示等效 CLI 预览，但 `remark / SSE / 全链路编排 / 预选池来源过滤 / pre_pool_run_id` 属于页面扩展，不是原 CLI 自带参数。
- 页面里的模型切换、结果过滤、`本次 run / 当前来源` 切换，统一使用 Element Plus 当前 `radio value` 绑定方式，不依赖旧版 `label` 充当值的兼容模式。
- “本次结果”和“已落库预选池”都支持：
  - 先按 `分支` 过滤
  - 再按 `模型` 过滤
  - 模型按钮会显示当前结果数量
  - `全链路 + 当前来源` 只会拉取：
    - `daily-screening:clxs`
    - `daily-screening:chanlun`
    不会直接扫全量历史 pre_pool

## 当前实现细节

- `CLXS` 页面模式支持多模型并行编排，但底层仍逐个 `model_opt` 调用 `ClxsStrategy.screen()`。
- `CLXS` 默认模型集合：
  - `8`
  - `9`
  - `12`
  - `10001`
- `CLXS` 未显式设置 `output_category` 时，pre_pool `category` 会跟随结果自身 `signal_type`，例如 `CLXS_8`、`CLXS_10001`。
- `chanlun` 页面模式默认启用 6 个固定信号，并保留 `signal_type + period` 粒度，避免不同信号在页面二次筛选时被提前合并。
- `全链路` 的 `save_pre_pools` 在页面上是只读开启状态。原因是：
  - `CLXS` 中间结果必须先写入 `stock_pre_pools`
  - `chanlun` 才能按 `remark + run_id` 只消费本次 CLXS 输出
- `全链路` 模式下，如果不是单票扫描，`chanlun` 会自动追加：
  - `remark = daily-screening:clxs`
  - `extra.screening_run_id = 当前 run_id`
  只消费本次 CLXS 结果，不混入旧 pre_pool 数据。

## 共享 pre_pool 语义

- 共享集合仍然是 `stock_pre_pools`。
- 页面来源真值写在顶层 `remark`：
  - `daily-screening:clxs`
  - `daily-screening:chanlun`
- 当 `remark` 非空时，`save_a_stock_pre_pools()` 的 upsert 语义是：
  - `code + category + remark`
- 当 `remark` 为空时，仍保持旧语义：
  - `code + category`
- 额外上下文写在 `extra`：
  - `screening_run_id`
  - `screening_model`
  - `screening_branch`
  - `screening_model_key`
  - `screening_model_label`
  - `screening_input_mode`
  - `screening_source_scope`
  - `screening_signal_type`
  - `screening_signal_name`
  - `screening_period`
  - `screening_params`

## SSE 事件

当前页面消费这些事件：

- `started`
- `universe`
- `progress`
- `hit_raw`
- `accepted`
- `persisted`
- `phase_started`
- `phase_completed`
- `summary`
- `completed`
- `error`
- `heartbeat`

## 当前边界

- 会话保存在 API 进程内存，只保证当前 API 进程存活期间有效。
- 页面落库 `stock_pre_pools` 时，会显式写入 remark 与 extra，不复用旧 CLI 的默认 `save_pre_pools` 行为。
- `chanlun` 在页面模式下支持按 `category` 或 `remark` 过滤共享 `stock_pre_pools` 输入范围。
- `全链路` 模式下，CLXS 与 chanlun 结果仍共用同一张页面结果表，但区分依赖 `branch/model_key/model_label`，不是只看 `category`。

## 部署/运行

- 后端改动后，重建 API Server。
- 前端改动后，重建 Web UI。
- 若要实际从页面发起扫描，运行环境仍需具备原 `clxs / chanlun_service` 依赖。

## 排障点

### 页面能打开但无法开始扫描

- 先看 `/api/daily-screening/schema` 是否正常返回。
- 再看 `/api/daily-screening/runs` 返回的是 400 还是 202。
- 如果是 `model must be all, clxs or chanlun`、`code required`、`pre_pool_remark required` 一类报错，说明是页面参数校验失败。

### SSE 没有事件或很快断开

- 先看 `/api/daily-screening/runs/<run_id>` 的 `status`。
- 如果已经是 `completed/failed`，SSE 自动结束属于预期。
- 如果 run 还在 `running`，检查 API 进程日志里是否有策略依赖缺失或回调异常。
- 如果只有 `started` 没有后续事件，优先检查底层 `clxs` 或 `chanlun_service` 依赖是否可用。

### 结果写进 pre_pool 后来源混在一起

- 检查顶层 `remark` 是否已写成 `daily-screening:clxs` 或 `daily-screening:chanlun`。
- 再检查该行是否带 `extra.screening_run_id`。
- 如果顶层 `remark` 缺失，说明不是新页面写入的数据，而是旧链路或历史记录。
