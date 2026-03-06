# Gantt / Shouban30 盘后读模型与独立分库设计稿

**目标**：迁移旧分支 `XGB / JYGS / Gantt / Shouban30` 的盘后数据能力，在目标仓库仅保留“盘后 Dagster 更新 + 页面/API 读模型查询”的模式，不保留盘中实时注入；同时把“热门板块理由”提升为逐日、可追溯的数据资产。

## 1. 调研结论

- 旧分支 XGB 甘特页通过 `/api/xgb/history/gantt/plates|stocks` 取数，后端主要读取 `xgb_top_gainer_history`，并在页面矩阵中额外注入 `xgb_top_gainer_snapshot` 的盘中快照。
- 旧分支 JYGS 甘特页通过 `/api/jygs/history/gantt/plates|stocks` 取数，后端主要读取 `jygs_yidong`，并使用从 `boards[].name` 归一化得到的 `board_key` 维持跨日稳定性。
- 旧分支 Shouban30 页面通过 `/api/gantt/shouban30/*` 取数，依赖 `gantt_shouban30_service` 从原始表导出 `plates/stocks` 结果，再写入 `DBpipeline`。
- 旧分支“板块理由”设计不稳定：
  - XGB 的板块理由散落在 `xgb_top_gainer_history.description`；
  - JYGS 的板块理由散落在 `jygs_action_fields.reason`；
  - Shouban30 还额外把个股 reasons 聚合作为板块理由兜底，导致来源混杂、难以审计。

## 2. 设计结论

- 目标仓库只保留盘后链路，不迁移盘中实时：
  - 不引入 `xgb_top_gainer_snapshot` 的页面注入逻辑；
  - 不依赖 WebSocket、Redis Pub/Sub 或 intraday snapshot。
- 新建独立 MongoDB 数据库：`freshquant_gantt`。
- `freshquant_gantt` 同时保存：
  - 该专题域的原始同步表；
  - 面向页面的标准化读模型。
- 页面/API 一律读取标准化读模型，不再直接扫原始表做重聚合。

## 3. 分库与集合规划

### 3.1 数据库

- 库名：`freshquant_gantt`
- 配置建议：
  - `mongodb.gantt_db: freshquant_gantt`
  - 环境变量覆盖：`freshquant_MONGODB__GANTT_DB`

### 3.2 原始层集合

- `xgb_top_gainer_history`
- `jygs_yidong`
- `jygs_action_fields`

说明：

- 这些集合迁入 `freshquant_gantt`，不再混放到 `freshquant` 主库。
- 本期不要求兼容旧分支的数据库命名方式（如 `DBxuangugong` / `DBjiuyangongshe` / `DBpipeline`）。

### 3.3 读模型集合

- `plate_reason_daily`
- `gantt_plate_daily`
- `gantt_stock_daily`
- `shouban30_plates`
- `shouban30_stocks`

## 4. 主键与稳定标识

- XGB 板块主键：`plate_key = str(plate_id)`
- JYGS 板块主键：`plate_key = board_key`
- 禁止把 JYGS `action_field_id` 当成跨日主键，因为该字段在旧分支中并不稳定。

## 5. 板块理由规则

### 5.1 唯一主来源

- XGB：
  - 来源字段：`xgb_top_gainer_history.description`
  - 写入：`plate_reason_daily.reason_text`
- JYGS：
  - 来源字段：`jygs_action_fields.reason`
  - 写入：`plate_reason_daily.reason_text`

### 5.2 严格约束

- 不做任何 fallback。
- 不允许从个股 reasons 聚合出板块理由。
- 若板块在目标日期进入 Gantt / Shouban30 计算窗口，但缺少板块理由：
  - 视为同步或建模错误；
  - `build_plate_reason_daily` 或下游构建任务必须失败，不能静默跳过。

### 5.3 `plate_reason_daily` 建议字段

- `provider`
- `plate_key`
- `plate_name`
- `trade_date`
- `reason_text`
- `reason_source`
- `source_ref`
- `updated_at`

唯一键：

- `provider + plate_key + trade_date`

## 6. 读模型结构

### 6.1 `gantt_plate_daily`

用途：

- 给 Gantt 板块视图直接查询，不再从原始表现算。

建议字段：

- `provider`
- `trade_date`
- `plate_key`
- `plate_name`
- `rank`
- `hot_stock_count`
- `limit_up_count`
- `stock_codes`
- `reason_text`
- `reason_ref`
- `updated_at`

唯一键：

- `provider + plate_key + trade_date`

### 6.2 `gantt_stock_daily`

用途：

- 给 Gantt drill-down 个股视图直接查询。

建议字段：

- `provider`
- `trade_date`
- `plate_key`
- `plate_name`
- `code6`
- `name`
- `is_limit_up`
- `hit_order`
- `stock_reason`
- `updated_at`

唯一键：

- `provider + plate_key + code6 + trade_date`

### 6.3 `shouban30_plates`

用途：

- 给 Shouban30 左侧板块列表直接查询。

建议字段：

- `provider`
- `as_of_date`
- `plate_key`
- `plate_name`
- `appear_days_30`
- `seg_from`
- `seg_to`
- `stocks_count_90`
- `reason_text`
- `reason_ref`
- `updated_at`

唯一键：

- `provider + plate_key + as_of_date`

### 6.4 `shouban30_stocks`

用途：

- 给 Shouban30 个股列表、hover 理由、后续筛选直接查询。

建议字段：

- `provider`
- `as_of_date`
- `plate_key`
- `plate_name`
- `code6`
- `name`
- `hit_count_30`
- `hit_count_90`
- `hit_dates`
- `stock_reasons`
- `updated_at`

唯一键：

- `provider + plate_key + code6 + as_of_date`

## 7. Dagster 盘后链路

建议拆成 5 个阶段：

1. `sync_xgb_history_daily`
   - 盘后同步 XGB 历史板块榜到 `freshquant_gantt.xgb_top_gainer_history`
2. `sync_jygs_action_daily`
   - 盘后同步 JYGS action 数据到 `freshquant_gantt.jygs_yidong` / `freshquant_gantt.jygs_action_fields`
3. `build_plate_reason_daily`
   - 从原始层产出 `plate_reason_daily`
   - 缺理由即失败
4. `build_gantt_daily`
   - 产出 `gantt_plate_daily` 与 `gantt_stock_daily`
5. `build_shouban30_daily`
   - 产出 `shouban30_plates` 与 `shouban30_stocks`

## 8. 对外 API 面

本期仅定义最小查询接口：

- `GET /api/gantt/plates`
  - 参数：`provider`、`days`
  - 读取 `gantt_plate_daily`
- `GET /api/gantt/stocks`
  - 参数：`provider`、`plate_key`、`days`
  - 读取 `gantt_stock_daily`
- `GET /api/gantt/shouban30/plates`
  - 参数：`provider`、`as_of_date`
  - 读取 `shouban30_plates`
- `GET /api/gantt/shouban30/stocks`
  - 参数：`provider`、`plate_key`、`as_of_date`
  - 读取 `shouban30_stocks`

## 9. 非目标

- 不迁移旧分支盘中实时快照与页面注入逻辑。
- 不迁移 WebSocket / intraday refresh。
- 不在本 RFC 内恢复旧分支完整前端页面。
- 不把缺失理由通过 fallback 掩盖掉。

## 10. 验收口径

- `freshquant_gantt` 分库建立成功，专题数据不进入 `freshquant` 主库。
- XGB / JYGS 原始同步与读模型构建全部通过 Dagster 盘后完成。
- Gantt 与 Shouban30 页面所需数据可以只通过读模型获取。
- 任一目标板块在目标日期缺少理由时，构建任务失败。
- JYGS 跨日板块主键稳定使用 `board_key`。
