# RFC 0027: Gantt Shouban30 筛选按钮与理由悬浮框

- **状态**：Approved
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-09
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

当前目标仓库的 `/gantt/shouban30` 已经切换为“只读盘后快照”的语义：

- 页面不再前端现算缠论结构
- 板块和标的列表来自 `/api/gantt/shouban30/plates|stocks`
- `shouban30` 由 Dagster 在盘后构建

但页面仍有两个明显缺口：

1. 板块理由和标的理由仍使用 Element 默认 `show-overflow-tooltip`，表现为黑色背景、长条形、长文本时横跨整个页面，阅读体验很差。
2. 页面缺少在“默认缠论通过股”基础上的进一步筛选能力，无法快速收缩到更可交易的子集。

来自旧分支 `D:\fqpack\freshquant` 的相关事实有两类：

- `KlineSlim` 页已经验证过更适合阅读的 `el-popover` 样式。
- `run_xgt_plate_screener_loop.py` 的“获取热门板块股票”阶段定义了一组稳定的优质 `block_names`，可作为“优质标的”的来源。

本 RFC 的目标是在不破坏 `/gantt/shouban30` 快照页定位的前提下，补齐“理由展示可读性”和“三类额外筛选”能力。

## 2. 目标（Goals）

- 将 `/gantt/shouban30` 的理由悬浮展示统一改为卡片式 popover。
- 在现有默认缠论通过股基础上新增三个筛选条件：
  - `融资标的`
  - `均线附近`
  - `优质标的`
- 三个筛选条件支持多选、单个取消，多选时取交集。
- 保持 `/gantt/shouban30` 继续只读取盘后快照，不新增页面散调链路。
- 将三类筛选标记直接固化到 `shouban30_stocks`，供页面直接消费。
- 为“优质标的”新增本项目自己的基础集合，并由 Dagster 每天盘后更新。

## 3. 非目标（Non-Goals）

- 不新增新的页面路由。
- 不把筛选状态写入 URL。
- 不为理由悬浮框新增异步 hover 请求。
- 不改变当前 `shouban30` 默认缠论筛选口径。
- 不把三类按钮的组合计数预先写入 `shouban30_plates`。

## 4. 范围（Scope）

**In Scope**

- `/gantt/shouban30` 页的理由悬浮框展示层改造。
- `shouban30_stocks` 快照新增三类筛选标记与均线辅助字段。
- 新增 `quality_stock_universe` 基础集合。
- Dagster 盘后在构建 `shouban30` 前更新优质标的基础集合。
- `/api/gantt/shouban30/stocks` 返回新增筛选字段。
- 前端在当前快照数据上执行多按钮交集过滤和板块重算。

**Out of Scope**

- 新增专用筛选 API。
- 盘中实时更新优质标的或均线筛选结果。
- 非 `/gantt/shouban30` 页面复用这三类筛选结果。
- 旧分支 `blk/pool/export/SSE` 行为迁回当前页。

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- `freshquant/data/quality_stock_universe.py` 负责构建和读取优质标的基础集合。
- `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py` 负责将“优质标的基础集合更新”接入现有盘后链路。
- `freshquant/data/gantt_readmodel.py` 负责将三类筛选标记写入 `shouban30_stocks`。
- `freshquant/rear/gantt/routes.py` 负责对外暴露扩展后的快照字段。
- `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue` 负责消费快照字段、执行交集过滤、重算板块列表。
- `morningglory/fqwebui/src/views/components/*` 负责 popover 展示层。

**不负责（Must Not）**

- 页面读时去查询融资名单、均线数据或优质名单。
- 页面读时去调用 `/api/stock_data` 或其他散接口临时计算筛选结果。
- 为任意按钮组合预生成后端聚合统计。

**依赖（Depends On）**

- RFC 0006：Gantt / Shouban30 盘后读模型
- RFC 0017：Shouban30 首期页面
- RFC 0023：Shouban30 盘后缠论快照
- RFC 0025：排除北交所标的后的 A 股候选语义
- 当前账户 `om_credit_subjects`
- 当前仓库的 `stock_block` 数据

**禁止依赖（Must Not Depend On）**

- 旧分支 `run_xgt_plate_screener_loop.py` 的运行时结果作为页面直接数据源
- 页面级别的散调组合查询
- 新增 Redis 实时缓存层

## 6. 对外接口（Public API）

### 6.1 `GET /api/gantt/shouban30/stocks`

路径与 query 参数保持不变：

- `provider`
- `plate_key`
- `stock_window_days`
- `as_of_date`

返回 `items[]` 新增：

- `is_credit_subject`
- `credit_subject_snapshot_ready`
- `near_long_term_ma_passed`
- `near_long_term_ma_basis`
- `close_price`
- `ma250`
- `ma500`
- `ma1000`
- `ma250_distance_pct`
- `ma500_distance_pct`
- `ma1000_distance_pct`
- `is_quality_subject`
- `quality_subject_snapshot_ready`
- `quality_subject_source_version`

### 6.2 `GET /api/gantt/shouban30/plates`

路径和 query 参数不变。

不新增额外筛选组合字段，页面侧基于 `stocks` 结果本地重算。

### 6.3 页面交互语义

- 新增三个额外筛选按钮：
  - `融资标的`
  - `均线附近`
  - `优质标的`
- 可多选、可单个取消。
- 多选时取交集，条件越多结果越少。
- 全部取消时回到当前页原始“缠论通过”列表。

### 6.4 错误语义

- 继续保留已有 `shouban30 chanlun snapshot not ready -> HTTP 409`
- 若融资名单或优质名单未准备好：
  - 不使整个 `shouban30` 快照构建失败
  - 以 `*_snapshot_ready=false` 表达来源未就绪
- 若日线均线数据缺失：
  - `near_long_term_ma_passed=false`
  - 相关均线字段为 `null`

## 7. 数据与配置（Data / Config）

### 7.1 新集合：`quality_stock_universe`

建议字段：

- `code6`
- `block_names`
- `source_version`
- `updated_at`

用途：

- 保存固定优质 block 名单对应的股票基础集合
- 供 `persist_shouban30_for_date()` 快速判断 `is_quality_subject`

### 7.2 `shouban30_stocks`

在现有缠论快照字段基础上新增：

- `is_credit_subject`
- `credit_subject_snapshot_ready`
- `near_long_term_ma_passed`
- `near_long_term_ma_basis`
- `close_price`
- `ma250`
- `ma500`
- `ma1000`
- `ma250_distance_pct`
- `ma500_distance_pct`
- `ma1000_distance_pct`
- `is_quality_subject`
- `quality_subject_snapshot_ready`
- `quality_subject_source_version`

### 7.3 筛选口径

**融资标的**

- 以当前账户同步下来的 `om_credit_subjects` 为准。

**均线附近**

- 以 `as_of_date` 最近一个日线收盘价计算。
- 若 `close` 相对 `ma250 / ma500 / ma1000` 任一条均线的偏离处于 `0%~3%`，则命中。
- 不是“高于均线即可”，而是严格的靠近区间。

**优质标的**

- 固定复用旧分支“获取热门板块股票”阶段的 `block_names`：
  - `活跃ETF`
  - `宽基ETF`
  - `上证50`
  - `“中证央企”`
  - `沪深300`
  - `证金汇金`
  - `昨成交20`
  - `养老金`
  - `社保重仓`
  - `社保新进`
  - `大基金`
  - `基金重仓`
  - `基金增仓`
  - `基金独门`
  - `券商重仓`
  - `券商金股`
  - `高股息股`
  - `高分红股`
  - `自由现金`
  - `绩优股`
  - `行业龙头`

### 7.4 配置

- 不新增面向用户的动态配置项。
- `source_version` 由代码常量维护。

## 8. 破坏性变更（Breaking Changes）

- `/api/gantt/shouban30/stocks` 返回字段扩展。
- `/gantt/shouban30` 页面新增额外筛选行为，且筛选后的板块列表和数量改为前端基于当前结果重算。
- `shouban30` 构建链新增 `quality_stock_universe` 集合依赖。

**影响面**

- 任何直接消费 `/api/gantt/shouban30/stocks` 且假设字段稳定的调用方
- `/gantt/shouban30` 的截图、文档和操作习惯
- Dagster 盘后任务耗时

**迁移步骤**

1. 部署包含 RFC 0027 的后端、Dagster 和前端代码
2. 运行或等待 `job_gantt_postclose` 更新优质标的基础集合并重建目标交易日 `shouban30`
3. 调用方按新字段读取 `is_credit_subject / near_long_term_ma_passed / is_quality_subject`
4. 页面用户改用按钮交集过滤，而不是依赖旧的纯缠论列表

**回滚方案**

1. 回退 `quality_stock_universe`、`gantt_readmodel.py`、Dagster `gantt.py`、前端页面与组件改动
2. 停用新增的优质标的更新步骤
3. 重新构建不带新增筛选字段的 `shouban30` 快照

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- `D:\fqpack\freshquant\freshquant\screening\run_xgt_plate_screener_loop.py`
  - 旧“获取热门板块股票”阶段的固定 `block_names`
  - 映射到新集合 `quality_stock_universe`

- `D:\fqpack\freshquant\morningglory\fqwebui\src\views\KlineSlim.vue`
  - 理由 popover 的交互与样式思路
  - 映射到当前页新的理由悬浮框组件

- 旧分支其余 `blk/export/SSE/pool` 逻辑
  - 不迁移

## 10. 测试与验收（Acceptance Criteria）

- [ ] `quality_stock_universe` 能从固定 `block_names` 构建出去重基础集合
- [ ] Dagster 在构建 `shouban30` 前会先更新优质标的基础集合
- [ ] `shouban30_stocks` 正确写入三类筛选字段
- [ ] `均线附近` 严格按 `0%~3%` 距离口径判定
- [ ] 页面三个筛选按钮支持多选、单个取消，且多选取交集
- [ ] 左侧板块与中间标的列表基于筛选结果同步变化
- [ ] 理由悬浮框不再是默认黑色长条 tooltip
- [ ] `npm run build` 与相关 pytest / node tests 全部通过

## 11. 风险与回滚（Risks / Rollback）

- 风险：Dagster 盘后构建耗时增加。
- 缓解：优质名单单独维护基础集合；长均线计算做本地缓存；不新增读时散调。

- 风险：`om_credit_subjects` 或优质名单未准备好时，页面筛选结果偏空。
- 缓解：通过 `*_snapshot_ready` 明确表达来源状态。

- 风险：页面逻辑继续膨胀。
- 缓解：把额外筛选逻辑从 `GanttShouban30Phase1.vue` 拆成独立 helper。

- 回滚：回退本 RFC 涉及的读模型、Dagster、前端页面和基础集合改动，并重建对应快照。

## 12. 里程碑与拆分（Milestones）

- M1：RFC 0027 通过
- M2：`quality_stock_universe` 与 Dagster 链路打通
- M3：`shouban30_stocks` 扩展三类筛选字段
- M4：前端筛选按钮与理由 popover 完成
- M5：测试、构建与迁移记录收尾
