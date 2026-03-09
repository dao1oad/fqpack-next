# Gantt Shouban30 盘后缠论快照设计

## 背景

当前 `/gantt/shouban30` 已经支持：

- `xgb / jygs / agg` 三视图
- `30 / 45 / 60 / 90` 标的窗口
- 左侧板块 / 中间标的 / 右侧历史热门理由三栏展示

但默认缠论筛选目前是在前端页面内现算：

- 首次打开页面时，对候选标的逐个调用 `/api/stock_data_chanlun_structure`
- 结果只缓存在页面内存中
- 刷新页面或重新打开后需要再次计算

这导致两个问题：

- 首次打开等待时间明显，候选股越多越慢
- `shouban30` 页面是按 `as_of_date` 消费盘后快照，但缠论筛选却变成了读时计算，语义不一致

本次设计改为：把 30 分钟默认缠论筛选收口到盘后 Dagster 构建阶段，页面只读取盘后快照，不再前端现算。

## 目标

- 将默认 30m 缠论筛选结果固化到现有 `shouban30_plates / shouban30_stocks` 读模型
- 保持现有 `/api/gantt/shouban30/plates` 与 `/api/gantt/shouban30/stocks` 路径不变
- 盘后一次性构建 `30 / 45 / 60 / 90` 四档窗口
- 同一 `code6 + as_of_date + 30m` 在单次盘后构建中只 fullcalc 一次
- 页面删除前端现算链路，只消费盘后快照

## 非目标

- 不新增新的公共路由
- 不保留“页面读时现算”兼容兜底
- 不把右侧详情改成缠论详情面板
- 不引入新页面或新调度任务

## 方案选择

### 方案 A：扩展现有 `shouban30` 读模型并在盘后预计算

- 在 `persist_shouban30_for_date()` 内直接为候选股计算 30m 缠论结构
- 结果写入现有 `shouban30_plates / shouban30_stocks`
- Dagster 四窗口共用一次内存缓存

优点：

- 页面查询最快
- 不新增新路由
- 与 `as_of_date` 快照语义一致

缺点：

- 需要扩展现有读模型 schema 和返回字段语义

### 方案 B：新增独立 `shouban30_chanlun_daily` 集合，再由路由 join

优点：

- 缠论结果表更独立，可被别的页面复用

缺点：

- 多一张集合和一层 join
- 改动面更大，不是本轮最小解

### 结论

采用方案 A。

## 默认筛选规则

固定为 30 分钟周期，按 `as_of_date` 计算：

- `higher_segment.end_price / higher_segment.start_price <= 3.0`
- `segment.end_price / segment.start_price <= 3.0`
- `bi.price_change_pct <= 30`

任一结构缺失、fullcalc 失败或接口语义为 `ok=false`，统一视为“不通过”。

## 板块过滤

板块黑名单不再留在页面层，而是在盘后构建期直接过滤：

- `其他`
- `公告`
- `ST股`
- `ST板块`

黑名单板块不进入 `shouban30_plates`，也不进入对应 `shouban30_stocks` 快照。

## 数据模型

### `shouban30_stocks`

继续沿用唯一键：

- `provider + plate_key + code6 + as_of_date + stock_window_days`

保留现有字段，并新增：

- `chanlun_passed`
- `chanlun_reason`
- `chanlun_higher_multiple`
- `chanlun_segment_multiple`
- `chanlun_bi_gain_percent`
- `chanlun_filter_version`

其中：

- `chanlun_passed` 表示是否通过默认 30m 筛选
- `chanlun_reason` 用于记录失败语义，如 `passed / structure_unavailable / higher_multiple_exceed`
- `chanlun_filter_version` 首版固定为 `30m_v1`

### `shouban30_plates`

继续沿用唯一键：

- `provider + plate_key + as_of_date + stock_window_days`

保留现有字段，但调整 `stocks_count` 语义并新增：

- `stocks_count`：通过默认 30m 缠论筛选后的唯一标的数
- `candidate_stocks_count`
- `failed_stocks_count`
- `chanlun_filter_version`

## 盘后计算链路

Dagster 仍然只通过现有 `job_gantt_postclose` 构建。

`_build_shouban30_snapshots_for_date()` 改为：

1. 为单个 `trade_date` 创建共享 `chanlun_result_cache`
2. 依次构建 `30 / 45 / 60 / 90` 四档窗口
3. 每个窗口调用 `persist_shouban30_for_date(..., chanlun_result_cache=cache)`

`persist_shouban30_for_date()` 改为：

1. 先按现有逻辑得到板块候选与标的候选
2. 应用黑名单板块过滤
3. 对候选股按 `code6 + as_of_date + 30m` 去重
4. 对 cache 未命中的股票调用 `get_chanlun_structure(symbol, period='30m', end_date=as_of_date)`
5. 按默认规则得出逐股缠论结果
6. 将逐股结果写入 `shouban30_stocks`
7. 将按板块聚合后的通过数 / 候选数 / 失败数写入 `shouban30_plates`

这样同一股票即使出现在多个板块或多个窗口里，在单日构建内也只 fullcalc 一次。

## 查询接口语义

### `GET /api/gantt/shouban30/plates`

路径和 query 参数保持不变。

返回调整：

- `items[].stocks_count` 语义改为“通过数”
- `items[]` 新增 `candidate_stocks_count / failed_stocks_count / chanlun_filter_version`
- `data.meta` 新增 `chanlun_filter_version`

### `GET /api/gantt/shouban30/stocks`

路径和 query 参数保持不变。

返回调整：

- `items[]` 新增 `chanlun_passed / chanlun_reason / chanlun_higher_multiple / chanlun_segment_multiple / chanlun_bi_gain_percent / chanlun_filter_version`
- 页面默认只展示 `chanlun_passed === true` 的项

## 页面行为

`/gantt/shouban30` 页面直接替换为新方案，不再兼容前端现算：

- 删除 `getChanlunStructure` 请求链路
- 删除页面级 `chanlunStructureCache`
- 删除 `loadChanlunStructures()` 及其并发控制
- 左栏直接使用后端返回的 `stocks_count`
- 中栏直接消费后端返回的 `chanlun_*` 字段
- `agg` 视图继续前端聚合，但聚合输入改为后端已带 `chanlun_*` 字段的 stock rows

## 旧快照与构建未完成语义

部署后，历史快照可能缺少新的缠论字段。

本次不保留前端现算 fallback。处理方式为：

- 如果查询到的 `shouban30` 快照缺少 `chanlun_filter_version`，视为 legacy snapshot
- 后端直接返回“快照未构建完成”错误
- 页面显示明确错误，不再退回慢路径

Dagster legacy 判定也同步升级：

- 缺少 `stock_window_days`
- 或缺少 `chanlun_filter_version`

任一命中都视为旧 schema，自动重建最新交易日四档窗口。

## 测试策略

### 后端

- `freshquant/tests/test_gantt_readmodel.py`
  - 黑名单板块不入快照
  - `stocks_count` 变为通过数
  - `candidate_stocks_count / failed_stocks_count` 正确
  - `shouban30_stocks` 写入 `chanlun_*`
  - 四窗口共享缓存，同一股票单日只计算一次
  - legacy 判定升级

- `freshquant/tests/test_gantt_routes.py`
  - `plates/stocks` 返回新增字段
  - legacy snapshot 返回明确错误

### 前端

- `morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs`
- `morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs`

重点覆盖：

- 页面不再包含前端现算链路
- 左栏显示通过数
- 中栏显示缠论三列
- `agg` 视图按后端预计算结果聚合

## 风险

- 盘后 Dagster 单次运行耗时会上升
- `fullcalc` 失败会直接影响次日页面可见结果
- 查询语义变化属于 breaking change，必须配套 RFC 和迁移记录

## 验收标准

- 页面首次打开不再逐股请求 `/api/stock_data_chanlun_structure`
- Dagster 在单日内对同一股票的 30m 结构只计算一次
- `/api/gantt/shouban30/plates` 返回的 `stocks_count` 等于通过数
- `/api/gantt/shouban30/stocks` 返回预计算好的 `chanlun_*` 字段
- `xgb / jygs / agg` 三视图都不再出现黑名单板块
- legacy 快照不会触发页面现算，而是显式报未构建完成
