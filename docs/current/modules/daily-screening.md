# 每日选股

## 职责

每日选股模块把原来只在 CLI 可用的两条盘后选股链路正式收口到 Web UI：

- `stock screen clxs`
- `stock screen chanlun`

它既负责直接发起扫描，也负责把扫描过程通过 SSE 实时推到页面，并把页面来源稳定落库到共享 `stock_pre_pools`。

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

`页面参数 -> /api/daily-screening/runs -> DailyScreeningService -> CLXS / chanlun strategy`

`strategy hooks -> session store -> /stream SSE -> 页面事件流 / 本次结果`

`accepted results -> DailyScreeningService 自定义落库 -> stock_pre_pools`

`页面预选池行 -> /pre-pools/stock-pools -> stock_pools`

## 页面行为

- 参数由 `/schema` 动态返回，前端不把模型参数写死。
- `CLXS` 支持：
  - `days`
  - `code`
  - `wave_opt`
  - `stretch_opt`
  - `trend_opt`
  - `model_opt`
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
  - `max_concurrent`
  - `save_signal`
  - `save_pools`
  - `save_pre_pools`
  - `pool_expire_days`
- 页面会显示等效 CLI 预览，但 `remark / SSE / 预选池来源过滤` 属于页面扩展，不是原 CLI 自带参数。

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
- `summary`
- `completed`
- `error`
- `heartbeat`

## 当前边界

- 会话保存在 API 进程内存，只保证当前 API 进程存活期间有效。
- 页面落库 `stock_pre_pools` 时，会显式写入 remark 与 extra，不复用旧 CLI 的默认 `save_pre_pools` 行为。
- `chanlun` 在页面模式下支持按 `category` 或 `remark` 过滤共享 `stock_pre_pools` 输入范围。

## 部署/运行

- 后端改动后，重建 API Server。
- 前端改动后，重建 Web UI。
- 若要实际从页面发起扫描，运行环境仍需具备原 `clxs / chanlun_service` 依赖。

## 排障点

### 页面能打开但无法开始扫描

- 先看 `/api/daily-screening/schema` 是否正常返回。
- 再看 `/api/daily-screening/runs` 返回的是 400 还是 202。
- 如果是 `model must be clxs or chanlun`、`code required`、`pre_pool_remark required` 一类报错，说明是页面参数校验失败。

### SSE 没有事件或很快断开

- 先看 `/api/daily-screening/runs/<run_id>` 的 `status`。
- 如果已经是 `completed/failed`，SSE 自动结束属于预期。
- 如果 run 还在 `running`，检查 API 进程日志里是否有策略依赖缺失或回调异常。

### 结果写进 pre_pool 后来源混在一起

- 检查顶层 `remark` 是否已写成 `daily-screening:clxs` 或 `daily-screening:chanlun`。
- 再检查该行是否带 `extra.screening_run_id`。
- 如果顶层 `remark` 缺失，说明不是新页面写入的数据，而是旧链路或历史记录。
