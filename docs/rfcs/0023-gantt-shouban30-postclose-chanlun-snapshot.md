# RFC 0023: Gantt Shouban30 盘后缠论快照

- **状态**：Approved
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-09
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

当前目标仓库已经有：

- `shouban30_plates / shouban30_stocks` 盘后读模型
- `/api/gantt/shouban30/plates`
- `/api/gantt/shouban30/stocks`
- `/gantt/shouban30` 首期页面

但默认 30 分钟缠论筛选是页面读时计算：

- 页面按候选股逐个请求 `/api/stock_data_chanlun_structure`
- 结果只缓存在页面内存
- 刷新页面或重新打开后会再次计算

这和 `shouban30` 的盘后快照语义不一致，也导致页面首次打开明显变慢。

本 RFC 将默认缠论筛选收口到盘后 Dagster 构建阶段，并直接扩展现有 `shouban30` 读模型和现有 `/api/gantt/shouban30/*` 返回语义。

## 2. 目标（Goals）

- 将默认 30m 缠论筛选结果预计算并落入 `shouban30_plates / shouban30_stocks`
- 保持现有 `/api/gantt/shouban30/plates|stocks` 路径不变
- 在盘后一次性构建 `30 / 45 / 60 / 90` 四档窗口
- 同一 `code6 + as_of_date + 30m` 在单次 Dagster 构建中只 fullcalc 一次
- 页面删除前端现算链路，只读取盘后快照

## 3. 非目标（Non-Goals）

- 不新增新的公共 HTTP 路由
- 不保留前端读时现算 fallback
- 不新增独立的 `shouban30_chanlun_daily` 集合
- 不改造右侧详情为缠论详情面板
- 不新增新的 Dagster job 或 schedule

## 4. 范围（Scope）

**In Scope**

- 扩展 `shouban30_plates / shouban30_stocks` schema
- 扩展 `persist_shouban30_for_date()` 盘后构建逻辑
- 在 Dagster 四窗口构建中共享单日缠论计算缓存
- 将板块黑名单下沉到盘后构建期
- 调整 `/api/gantt/shouban30/plates|stocks` 返回语义
- 替换前端页面为“只读盘后快照”模式

**Out of Scope**

- KlineSlim 或其他页面复用该批缠论结果
- 盘中实时更新 `shouban30` 缠论快照
- 引入新的 Redis/Mongo 持久缓存层
- 保留旧页面“导出/重算/池子/blk/SSE”行为

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- `freshquant/data/gantt_readmodel.py` 负责构建和查询盘后缠论快照
- `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py` 负责按交易日构建四窗口快照
- `freshquant/rear/gantt/routes.py` 负责对外暴露已构建完成的快照结果
- `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue` 负责消费快照并展示

**不负责（Must Not）**

- 请求期重新计算 fullcalc
- 页面侧逐股调用 `/api/stock_data_chanlun_structure`
- 保留 legacy snapshot 的前端兼容慢路径

**依赖（Depends On）**

- RFC 0006：Gantt / Shouban30 盘后读模型与独立分库
- RFC 0017：Gantt Shouban30 首期页面迁移
- RFC 0018：KlineSlim 缠论结构接口与 fullcalc 链路
- 现有 `get_chanlun_structure(symbol, period, end_date)` 服务

**禁止依赖（Must Not Depend On）**

- 旧分支 `gantt_shouban30_service.py` 的导出/缓存/SSE/blk 闭环
- 新增页面专用路由

## 6. 对外接口（Public API）

### 6.1 `GET /api/gantt/shouban30/plates`

路径与 query 参数保持不变：

- `provider`
- `stock_window_days`
- `as_of_date`

返回 shape 保持顶层不变，但字段语义调整：

- `items[].stocks_count` 从“原始热门标的数”改为“通过默认 30m 缠论筛选后的唯一标的数”
- `items[]` 新增：
  - `candidate_stocks_count`
  - `failed_stocks_count`
  - `chanlun_filter_version`
- `data.meta` 新增：
  - `chanlun_filter_version`

### 6.2 `GET /api/gantt/shouban30/stocks`

路径与 query 参数保持不变：

- `provider`
- `plate_key`
- `stock_window_days`
- `as_of_date`

返回 shape 保持顶层不变，但 `items[]` 新增：

- `chanlun_passed`
- `chanlun_reason`
- `chanlun_higher_multiple`
- `chanlun_segment_multiple`
- `chanlun_bi_gain_percent`
- `chanlun_filter_version`

### 6.3 错误语义

- 参数非法：HTTP `400`
- 快照不存在：HTTP `200` + 空 `items`
- 命中 legacy snapshot（缺少新 schema 字段）：HTTP `409`
  - message：`shouban30 chanlun snapshot not ready`

### 6.4 兼容策略

- 不兼容前端继续依赖 `stocks_count` 旧语义
- 不兼容页面继续读时调用 `/api/stock_data_chanlun_structure`
- 通过升级 Dagster 重建快照完成迁移

## 7. 数据与配置（Data / Config）

### 7.1 `shouban30_stocks`

继续沿用唯一键：

- `provider + plate_key + code6 + as_of_date + stock_window_days`

新增字段：

- `chanlun_passed`
- `chanlun_reason`
- `chanlun_higher_multiple`
- `chanlun_segment_multiple`
- `chanlun_bi_gain_percent`
- `chanlun_filter_version`

### 7.2 `shouban30_plates`

继续沿用唯一键：

- `provider + plate_key + as_of_date + stock_window_days`

字段调整：

- `stocks_count` 语义改为“通过数”

新增字段：

- `candidate_stocks_count`
- `failed_stocks_count`
- `chanlun_filter_version`

### 7.3 板块过滤

盘后构建期直接过滤：

- `其他`
- `公告`
- `ST股`
- `ST板块`

### 7.4 版本字段

首版固定：

- `chanlun_filter_version = '30m_v1'`

### 7.5 配置

不新增新的动态配置项，继续复用现有 Dagster 和 `freshquant_gantt` 分库配置。

## 8. 破坏性变更（Breaking Changes）

- `shouban30_plates.stocks_count` 语义变化
- `/api/gantt/shouban30/plates` 返回字段语义变化
- `/api/gantt/shouban30/stocks` 返回新字段
- 页面从“前端现算”切换到“只读盘后快照”
- legacy snapshot 不再前端兜底，而是显式返回未就绪错误

**影响面**

- 任何依赖 `stocks_count` 旧语义的前端或脚本
- 任何假设页面会在读时现算缠论筛选的调用方

**迁移步骤**

1. 部署包含 RFC 0023 的代码
2. 运行 `job_gantt_postclose` 重建最新交易日四档窗口
3. 前端切换为只消费 `/api/gantt/shouban30/*` 返回的 `chanlun_*` 字段
4. 停止页面调用 `/api/stock_data_chanlun_structure` 做 `shouban30` 默认筛选

**回滚方案**

1. 回退 `gantt_readmodel.py`、Dagster `gantt.py`、`rear/gantt/routes.py`、`GanttShouban30Phase1.vue`
2. 重新构建不带 `chanlun_*` 的 `shouban30` 快照
3. 恢复页面前端现算方案

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- 旧 `morningglory/fqwebui/src/views/GanttShouban30.vue`
  - 默认缠论筛选与按板块显示思路
  - 映射到目标仓库 `GanttShouban30Phase1.vue` 与盘后快照字段

- 旧 `freshquant/data/gantt_shouban30_service.py`
  - 页面相关缠论筛选经验
  - 不迁移其导出/流式/blk/pool 闭环，只迁移默认筛选口径

## 10. 测试与验收（Acceptance Criteria）

- [ ] `persist_shouban30_for_date()` 会写入 `chanlun_*` 字段
- [ ] 黑名单板块不会进入 `shouban30` 快照
- [ ] 四窗口共享单日缠论计算缓存，同一股票只 fullcalc 一次
- [ ] `/api/gantt/shouban30/plates` 的 `stocks_count` 等于通过数
- [ ] `/api/gantt/shouban30/stocks` 返回预计算的 `chanlun_*`
- [ ] legacy snapshot 返回 `409 shouban30 chanlun snapshot not ready`
- [ ] 页面不再逐股请求 `/api/stock_data_chanlun_structure`
- [ ] `npm run build` 与目标测试通过

## 11. 风险与回滚（Risks / Rollback）

- 盘后任务耗时上升
- `fullcalc` 失败会直接影响快照可见结果
- schema 升级后，旧快照需要显式重建

缓解：

- 单日四窗口共享缓存
- legacy snapshot 自动判定并重建最新交易日
- 对 `chanlun_reason` 统一记录失败语义，便于排障

## 12. 里程碑与拆分（Milestones）

- M1：RFC 0023 批准
- M2：读模型 schema 与 Dagster 构建落地
- M3：路由与页面切换到只读盘后快照
- M4：测试、构建与迁移记录完成
