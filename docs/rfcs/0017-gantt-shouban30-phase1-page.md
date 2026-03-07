# RFC 0017: Gantt Shouban30 首期页面迁移

- **状态**：Approved
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-07
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

旧分支 `D:\fqpack\freshquant` 已具备完整 `/gantt/shouban30` 页面能力，但该页面实际上是一套完整闭环，而非单纯列表页：

- `30天首板` 导出
- 热点标的窗口切换（`30 / 45 / 60 / 90`）
- 缠论计算 / 缠论筛选
- 预选池 / 自选池
- blk 同步
- 标的详情

目标仓库 `D:\fqpack\freshquant-2026.2.23` 当前只迁入了该专题的最小盘后读模型与列表接口：

- `GET /api/gantt/shouban30/plates`
- `GET /api/gantt/shouban30/stocks`
- `GET /api/gantt/stocks/reasons`

现状问题：

- 还没有 `/gantt/shouban30` 页面入口与页面骨架。
- 现有 `shouban30` 读模型没有承接旧页第二窗口维度，即热点标的窗口 `30 / 45 / 60 / 90`。
- 当前 `shouban30` 字段命名仍是最小版本，不足以作为首期页面稳定契约。
- 旧页中的“标的详情”现已确认应定义为“历史全量热门理由”，这与 `shouban30` 列表上下文不同，需要明确边界。

用户要求本轮只完成首期页面迁移设计，不编码，且范围严格限定为：

- 页面骨架
- 30天首板列表
- 标的详情

## 2. 目标（Goals）

- 为目标仓库定义 `/gantt/shouban30` 首期页面的正式术语与数据边界。
- 明确 `30天首板` 与 `热点标的窗口` 的正式定义。
- 将旧页中的热点标的窗口 `30 / 45 / 60 / 90` 迁移为目标仓库正式 schema 维度。
- 扩展现有 `freshquant_gantt` 读模型，使其承载首期页面所需字段。
- 明确首期页面正式接口契约与错误语义。
- 将“标的详情”定义为历史全量热门理由，并复用目标仓库现有全局详情能力。
- 明确本期不进入缠论、池子、SSE、blk 闭环。

## 3. 非目标（Non-Goals）

- 不实现缠论计算。
- 不实现缠论筛选。
- 不实现预选池。
- 不实现自选池。
- 不实现 blk 同步。
- 不实现 SSE。
- 不保留旧页中的“页面触发导出 / 重算”行为。
- 不把旧分支 `DBpipeline + export + chanlun + pool + blk` 全闭环原样迁回目标仓库。

## 4. 范围（Scope）

**In Scope**

- `/gantt/shouban30` 页面首期骨架设计
- `xgb / jygs` 双 provider 切换
- `30 / 45 / 60 / 90` 热点标的窗口切换
- `30天首板` 板块列表
- 板块下标的列表
- 标的详情（历史全量热门理由）
- `shouban30_plates / shouban30_stocks` 读模型 schema 扩展
- 首期接口契约定义

**Out of Scope**

- 缠论计算 / 筛选
- 预选池 / 自选池
- blk 文件交互
- 页面发起导出 / 重算
- 旧页 UI 全量复刻

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- `freshquant_gantt.shouban30_plates` 承载 30天首板板块列表的正式盘后读模型。
- `freshquant_gantt.shouban30_stocks` 承载板块下标的列表的正式盘后读模型。
- `freshquant_gantt.stock_hot_reason_daily` 承载“标的详情”的历史全量热门理由。
- `/api/gantt/shouban30/*` 只负责页面首期列表查询。
- `/api/gantt/stocks/reasons` 负责标的历史全量热门理由查询。
- 页面只查询读模型，不做导出和重算。

**不负责（Must Not）**

- 不在请求期做 `shouban30` 导出。
- 不在请求期做缠论 fullcalc。
- 不在首期页面内引入池子和 blk 操作。
- 不在首期页面中兼容旧分支的完整 API 面。

**依赖（Depends On）**

- RFC 0006：`freshquant_gantt` 分库与盘后读模型体系
- `freshquant/data/gantt_readmodel.py`
- `freshquant/rear/gantt/routes.py`
- 全局历史理由读模型 `stock_hot_reason_daily`
- 旧分支参考：
  - `D:\fqpack\freshquant\morningglory\fqwebui\src\views\GanttShouban30.vue`
  - `D:\fqpack\freshquant\freshquant\data\gantt_shouban30_service.py`
  - `D:\fqpack\freshquant\freshquant\rear\gantt\shouban30_routes.py`

**禁止依赖（Must Not Depend On）**

- 旧分支 `DBpipeline` 作为目标仓库页面事实源
- 旧页 `POST /api/gantt/shouban30/export`
- 旧页 `chanlun/*`
- 旧页 `pool/*`
- 旧页 `watchlist/*`
- 旧页 `sync_blk`

## 6. 对外接口（Public API）

### 6.1 术语定义

- `30天首板`
  - 定义为：按单一数据源、按完整交易日序列，在最近 30 个完整交易日窗口内，某板块只出现 1 段连续命中区间。
- `热点标的窗口`
  - 正式命名为 `stock_window_days`
  - 允许值：`30 | 45 | 60 | 90`
  - 作用于板块窗口标的数、标的列表与命中次数统计
- `标的详情`
  - 定义为：某标的的历史全量热门理由
  - 不受 `as_of_date`、`stock_window_days`、当前板块约束

### 6.2 HTTP API

- `GET /api/gantt/shouban30/plates`
  - query：
    - `provider=xgb|jygs`
    - `stock_window_days=30|45|60|90`
    - `as_of_date=YYYY-MM-DD` 可选
  - 返回：
    - `data.items[]`
    - `data.meta.as_of_date`
    - `data.meta.stock_window_days`
    - `data.meta.available_as_of_dates` 可选

- `GET /api/gantt/shouban30/stocks`
  - query：
    - `provider=xgb|jygs`
    - `plate_key`
    - `stock_window_days=30|45|60|90`
    - `as_of_date=YYYY-MM-DD` 可选
  - 返回：
    - `data.items[]`
    - `data.meta.as_of_date`
    - `data.meta.stock_window_days`

- `GET /api/gantt/stocks/reasons`
  - query：
    - `code6`
    - `provider=all|xgb|jygs`
    - `limit=0`
  - 返回：
    - `data.items[]`
  - 说明：
    - 作为 `shouban30` 首期标的详情接口
    - 不单独增加 `shouban30` 专属详情 API

### 6.3 错误语义

- 参数非法：HTTP `400`
  - 如 `provider` 非法、`stock_window_days` 非法、`plate_key` 缺失、`code6` 非法
- 数据不存在：HTTP `200 + 空 items`
- 盘后读模型缺失：页面空态，不在请求期现算

### 6.4 兼容策略

- 不兼容旧页 `POST /api/gantt/shouban30/export`
- 不兼容旧页 `chanlun/*`
- 不兼容旧页 `pool/*`
- 不兼容旧页 `watchlist/*`
- 沿用目标仓库现有 `/api/gantt/*` 风格

## 7. 数据与配置（Data / Config）

### 7.1 数据存储

继续使用独立分库：

- `freshquant_gantt`

### 7.2 读模型 schema

#### `shouban30_plates`

唯一键：

- `provider + plate_key + as_of_date + stock_window_days`

字段：

- `provider`
- `as_of_date`
- `stock_window_days`
- `plate_key`
- `plate_name`
- `appear_days_30`
- `seg_from`
- `seg_to`
- `stocks_count`
- `window30_from`
- `window30_to`
- `stock_window_from`
- `stock_window_to`
- `reason_text`
- `reason_ref`
- `updated_at`

#### `shouban30_stocks`

唯一键：

- `provider + plate_key + code6 + as_of_date + stock_window_days`

字段：

- `provider`
- `as_of_date`
- `stock_window_days`
- `plate_key`
- `plate_name`
- `code6`
- `name`
- `hit_count_window`
- `hit_count_30`
- `latest_trade_date`
- `latest_reason`
- `updated_at`

### 7.3 标的详情数据源

首期标的详情直接复用：

- `stock_hot_reason_daily`

不为 `shouban30` 额外新增一套详情集合。

### 7.4 配置

- 不新增新的配置项
- 继续复用：
  - `FRESHQUANT_MONGODB__GANTT_DB`

## 8. 破坏性变更（Breaking Changes）

本 RFC 目前只冻结首期设计，不落地代码，因此本节记录的是预期影响，而非已落地行为。

### 影响面

- 现有 `shouban30_plates / shouban30_stocks` 读模型 schema 将扩展 `stock_window_days` 维度。
- 现有 `shouban30` 接口在实现后将新增必选查询语义 `stock_window_days`。
- 首期页面将不再沿用旧页“进入页面自动导出 / 切按钮自动重算”的行为。

### 迁移步骤

1. 盘后任务扩展 `shouban30` 读模型 schema
2. 查询接口增加 `stock_window_days`
3. 页面 `/gantt/shouban30` 接入新接口
4. 标的详情直接复用全局热门理由接口

### 回滚方案

- 回退 `stock_window_days` 维度扩展
- 停用 `/gantt/shouban30` 首期页面
- 保持现有最小 `shouban30` 列表能力

> 若后续实现中产生额外不兼容变化，落地时再同步更新 `docs/migration/breaking-changes.md`。

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- `D:\fqpack\freshquant\morningglory\fqwebui\src\views\GanttShouban30.vue`
  - 旧页页面结构与按钮语义
  - 映射到目标仓库首期 `/gantt/shouban30` 页面

- `D:\fqpack\freshquant\freshquant\data\gantt_shouban30_service.py`
  - `30天首板` 单段判定
  - `days30 + days90` 双窗口语义
  - 映射到目标仓库 `gantt_readmodel` 的盘后构建逻辑

- `D:\fqpack\freshquant\freshquant\rear\gantt\shouban30_routes.py`
  - 旧页查询接口划分参考
  - 映射到目标仓库 `/api/gantt/shouban30/plates`、`/api/gantt/shouban30/stocks`

- `D:\fqpack\freshquant\freshquant\data\gantt_shouban30_service.py:list_stock_reasons`
  - 旧页“标的详情”排序与展示语义参考
  - 映射到目标仓库全局详情接口 `/api/gantt/stocks/reasons`

## 10. 测试与验收（Acceptance Criteria）

- [ ] `/gantt/shouban30` 页面存在首期路由入口
- [ ] 页面支持 `xgb / jygs` 切换
- [ ] 页面支持 `30 / 45 / 60 / 90` 热点标的窗口切换
- [ ] 板块列表只展示 `30天首板` 结果
- [ ] 板块列表包含：板块名、30天出现次数、连续区间、板块理由、窗口标的数
- [ ] 点击板块后能展示对应标的列表
- [ ] 标的列表命中次数会随 `stock_window_days` 变化
- [ ] 点击标的后，详情区能展示历史全量热门理由
- [ ] 页面不触发导出、重算、缠论、池子、SSE、blk 逻辑

## 11. 风险与回滚（Risks / Rollback）

- 风险点：现有目标仓库 `shouban30` 读模型过于最小，扩展时容易与 RFC 0006 现有实现冲突。
  - 缓解：在实现前先以纯函数测试锁定 schema 与窗口语义。

- 风险点：如果把标的详情错误地继续限制在 `shouban30` 页面上下文内，会与用户确认口径冲突。
  - 缓解：明确直接复用全局热门理由接口。

- 风险点：首期页面如果继续保留旧页“自动导出”思路，会破坏目标仓库读模型边界。
  - 缓解：RFC 明确禁止页面触发导出 / 重算。

- 回滚：回退新增路由、接口与读模型扩展，保持现有最小 `shouban30` 列表能力。

## 12. 里程碑与拆分（Milestones）

- M1：RFC 0017 通过
- M2：扩展 `shouban30` 读模型 schema 与盘后构建
- M3：补齐 `plates / stocks` 查询接口
- M4：补齐 `/gantt/shouban30` 首期页面
- M5：进入二期 RFC（缠论 / 池子 / blk）
