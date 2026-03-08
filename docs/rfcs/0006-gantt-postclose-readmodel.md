# RFC 0006: XGB / JYGS / Gantt / Shouban30 盘后读模型与独立分库

- **状态**：Done
- **负责人**：TBD
- **评审人**：TBD
- **创建日期**：2026-03-06
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

目标仓库 `D:\fqpack\freshquant-2026.2.23` 当前尚未承接旧分支 `D:\fqpack\freshquant` 中 XGB / JYGS / Gantt / Shouban30 这一组专题能力。旧分支的页面数据主要依赖以下链路：

- XGB 甘特页：
  - 后端路由：`freshquant/rear/xgt/cache_routes.py`
  - 服务：`freshquant/data/xgb_cache_service.py`
  - 数据源：`xgb_top_gainer_history`，并注入 `xgb_top_gainer_snapshot`
- JYGS 甘特页：
  - 后端路由：`freshquant/rear/jygs/gantt_routes.py`
  - 服务：`freshquant/data/jygs_gantt_service.py`
  - 数据源：`jygs_yidong`
- Shouban30：
  - 后端路由：`freshquant/rear/gantt/shouban30_routes.py`
  - 服务：`freshquant/data/gantt_shouban30_service.py`
  - 数据源：`xgb_top_gainer_history`、`jygs_yidong`、`jygs_action_fields`

旧分支存在三个核心问题：

1. 页面查询强依赖“读取原始表时现算”，聚合逻辑分散在多个 service 中。
2. XGB 还混入 `xgb_top_gainer_snapshot` 的盘中实时逻辑，不符合目标仓库本期“只做盘后更新”的要求。
3. “热门板块理由”字段设计不稳定：
   - XGB 板块理由在 `xgb_top_gainer_history.description`
   - JYGS 板块理由在 `jygs_action_fields.reason`
   - Shouban30 还会从个股 reasons 做 fallback 聚合，导致来源混杂且不可审计

本 RFC 的目标是把这组能力迁移为“盘后 Dagster 同步 + 标准化读模型 + 独立分库”，并把“板块理由”提升为逐日、可追溯的数据资产。

## 2. 目标（Goals）

- 只保留盘后数据更新，不迁移盘中实时快照与实时注入逻辑。
- 新建 MongoDB 独立数据库 `freshquant_gantt`，保存该专题域的原始层与读模型层数据。
- 迁移 XGB / JYGS 原始同步能力到目标仓库。
- 构建标准化读模型：
  - `plate_reason_daily`
  - `gantt_plate_daily`
  - `gantt_stock_daily`
  - `shouban30_plates`
  - `shouban30_stocks`
- 统一板块主键：
  - XGB 使用稳定 `plate_id`
  - JYGS 使用稳定 `board_key`
- 严格要求板块理由存在，不允许 fallback。
- 提供最小 HTTP 查询接口，供后续页面迁移使用。

## 3. 非目标（Non-Goals）

- 不迁移旧分支的盘中实时链路（如 `xgb_top_gainer_snapshot` 页面注入）。
- 不迁移 WebSocket、Redis Pub/Sub 或其他 intraday refresh 机制。
- 不在本 RFC 内恢复旧分支完整前端页面。
- 不兼容旧分支的多数据库命名方式（如 `DBxuangugong` / `DBjiuyangongshe` / `DBpipeline`）。
- 不从个股 reasons 聚合板块理由作为兜底。

## 4. 范围（Scope）

**In Scope**

- 盘后同步 XGB 历史板块榜到 `freshquant_gantt.xgb_top_gainer_history`
- 盘后同步 JYGS action 数据到 `freshquant_gantt.jygs_yidong` 与 `freshquant_gantt.jygs_action_fields`
- 构建 `plate_reason_daily`
- 构建 Gantt 与 Shouban30 所需读模型
- 新增最小 HTTP 查询接口
- 在 Dagster 中增加盘后 job / op / schedule
- 在 dynaconf 中新增 `mongodb.gantt_db`

**Out of Scope**

- 盘中实时更新
- 前端页面迁移
- 基于 Redis 的缓存、推送与通知
- 个股缠论筛选、BLK 同步、预选池联动等旧分支后续闭环能力

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- 原始同步层负责：
  - 从上游接口获取 XGB / JYGS 数据
  - 标准化并写入 `freshquant_gantt` 原始集合
- 读模型层负责：
  - 生成稳定主键
  - 生成逐日板块理由
  - 生成页面直接可读的甘特与 Shouban30 数据
- API 层负责：
  - 提供最小查询接口
  - 不再在请求期重扫原始表做复杂聚合

**不负责（Must Not）**

- 不负责盘中增量刷新
- 不负责前端图表渲染
- 不负责旧分支的 fallback 兼容逻辑
- 不负责把专题数据写回 `freshquant` 主库

**依赖（Depends On）**

- Dynaconf 配置
- MongoDB
- `morningglory/fqdagster`
- XGB / JYGS 上游 HTTP 数据源

**禁止依赖（Must Not Depend On）**

- 盘中 snapshot 注入
- Redis 作为本专题的主数据源
- JYGS `action_field_id` 作为跨日板块主键

## 6. 对外接口（Public API）

新增最小接口：

- `GET /api/gantt/plates`
  - 参数：`provider=xgb|jygs`、`days`
  - 返回：板块甘特数据
- `GET /api/gantt/stocks`
  - 参数：`provider=xgb|jygs`、`plate_key`、`days`
  - 返回：板块内个股甘特数据
- `GET /api/gantt/shouban30/plates`
  - 参数：`provider=xgb|jygs`、`as_of_date`
  - 返回：30 日首板板块列表
- `GET /api/gantt/shouban30/stocks`
  - 参数：`provider=xgb|jygs`、`plate_key`、`as_of_date`
  - 返回：30 日首板个股列表

错误语义：

- 参数非法：HTTP 400
- 数据不存在：HTTP 404 或返回空列表（需在实现时统一）
- 板块理由缺失：不由 API 降级处理，应在 Dagster 构建阶段失败

兼容策略：

- 这是新接口面，不承诺兼容旧分支 `/api/xgb/*`、`/api/jygs/*`、`/api/gantt/shouban30/*` 的具体返回结构

## 7. 数据与配置（Data / Config）

配置新增：

- `mongodb.gantt_db`
  - 默认值：`freshquant_gantt`
  - 环境变量：`FRESHQUANT_MONGODB__GANTT_DB`

数据库：

- 新库：`freshquant_gantt`

原始集合：

- `xgb_top_gainer_history`
- `jygs_yidong`
- `jygs_action_fields`

读模型集合：

- `plate_reason_daily`
- `gantt_plate_daily`
- `gantt_stock_daily`
- `shouban30_plates`
- `shouban30_stocks`

关键 schema 约束：

- `plate_reason_daily`
  - 唯一键：`provider + plate_key + trade_date`
  - `reason_text` 必填
- `gantt_plate_daily`
  - 唯一键：`provider + plate_key + trade_date`
- `gantt_stock_daily`
  - 唯一键：`provider + plate_key + code6 + trade_date`
- `shouban30_plates`
  - 唯一键：`provider + plate_key + as_of_date`
- `shouban30_stocks`
  - 唯一键：`provider + plate_key + code6 + as_of_date`

板块理由来源：

- XGB：`xgb_top_gainer_history.description`
- JYGS：`jygs_action_fields.reason`

严格规则：

- 不做 fallback
- 缺失板块理由即构建失败

## 8. 破坏性变更（Breaking Changes）

- 本 RFC 引入新的查询接口面，不承诺兼容旧分支相同页面的历史接口结构。
- 该专题域数据不再进入 `freshquant` 主库，而是单独放入 `freshquant_gantt`。

影响面：

- 后续迁移该专题页面时，需要切换到新接口与新数据库结构。
- 运维与数据备份策略需要额外覆盖 `freshquant_gantt`。

迁移步骤：

1. 配置 `mongodb.gantt_db`
2. 部署 Dagster 盘后 job
3. 先构建原始层，再构建读模型层
4. 页面或调用方切换到新接口

回滚方案：

- 停用新 Dagster job / schedule
- 停止使用 `/api/gantt/*` 新接口
- 保留原始同步逻辑与 `freshquant_gantt` 数据以便后续重试

> 实际落地时如产生额外不兼容变化，再同步更新 `docs/migration/breaking-changes.md`。

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- `freshquant/data/xgb_cache_service.py`
  - XGB 原始历史同步能力 → 迁移为目标仓库的 XGB 原始同步模块
- `freshquant/signal/astock/job/monitor_jygs_action_yidong.py`
  - JYGS action / reason 同步能力 → 迁移为目标仓库的 JYGS 原始同步模块
- `freshquant/data/jygs_gantt_service.py`
  - JYGS 甘特矩阵计算 → 迁移为目标仓库读模型构建逻辑的一部分
- `freshquant/data/gantt_shouban30_service.py`
  - 30 日首板导出逻辑 → 迁移为目标仓库读模型构建逻辑的一部分
- `freshquant/rear/xgt/cache_routes.py` / `freshquant/rear/jygs/gantt_routes.py` / `freshquant/rear/gantt/shouban30_routes.py`
  - 多套旧 API → 收敛为目标仓库统一 `/api/gantt/*`

## 10. 测试与验收（Acceptance Criteria）

- [ ] 单元测试：`plate_key`、`board_key`、`reason_text` 归一化规则可验证
- [ ] 单元测试：缺失板块理由时，`build_plate_reason_daily` 或下游构建明确失败
- [ ] 单元测试：Gantt / Shouban30 读模型的唯一键与窗口逻辑可验证
- [ ] 集成测试：Dagster 盘后 job 能写入 `freshquant_gantt` 原始层与读模型层
- [ ] 集成测试：`/api/gantt/*` 最小接口可返回预期结构
- [ ] 手工验证：Mongo 中不存在专题数据写入 `freshquant` 主库

## 11. 风险与回滚（Risks / Rollback）

- 风险点：上游接口字段不稳定，尤其是 JYGS action 返回结构
- 缓解：把字段抽取与归一化做成独立函数，并补纯函数单测

- 风险点：JYGS 同名板块归一化后冲突
- 缓解：保留 `source_ref` 与原始字段，先以 `board_key` 为唯一主键实现，必要时再追加冲突检测

- 风险点：历史数据量增长导致索引与构建时长上升
- 缓解：严格限制页面字段、对唯一键与查询键建索引、按交易日增量构建

- 回滚：停用新调度与接口，不删除已生成的 `freshquant_gantt` 数据

## 12. 里程碑与拆分（Milestones）

- M1：RFC 评审通过
- M2：原始同步层落地（XGB / JYGS）
- M3：板块理由与 Gantt 读模型落地
- M4：Shouban30 读模型与查询接口落地
- M5：页面接入与旧逻辑下线（后续 RFC）
