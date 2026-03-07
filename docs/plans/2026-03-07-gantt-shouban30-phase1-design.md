# Gantt Shouban30 首期页面迁移设计稿

**目标**：在目标仓库为旧分支 `/gantt/shouban30` 落地首期页面设计，只覆盖“页面骨架 + 30天首板列表 + 标的详情（历史全量热门理由）”，不进入缠论、预选池、自选池、SSE、blk 闭环。

## 1. 背景

旧分支 `D:\fqpack\freshquant` 中的 `/gantt/shouban30` 已经不是简单列表页，而是一套完整闭环：

- `30天首板` 导出
- 热点标的窗口切换（`30 / 45 / 60 / 90`）
- 缠论计算 / 缠论筛选
- 预选池 / 自选池
- blk 同步
- 标的详情

目标仓库 `D:\fqpack\freshquant-2026.2.23` 当前只承接了盘后读模型最小子集：

- `GET /api/gantt/shouban30/plates`
- `GET /api/gantt/shouban30/stocks`
- `GET /api/gantt/stocks/reasons`

但现有 `shouban30` 读模型仍然是“最小列表能力”，还没有完整对齐旧页面语义，尤其缺少：

- 旧页第二窗口维度（`30 / 45 / 60 / 90` 热点标的窗口）
- 与旧页一致的字段命名和列表契约
- `/gantt/shouban30` 页面本身

本轮设计只处理首期页面迁移，不把旧页完整闭环一次性搬回目标仓库。

## 2. 已确认范围

### In Scope

- `/gantt/shouban30` 页面骨架
- `30天首板` 板块列表
- 板块下标的列表
- 标的详情面板
- `provider` 切换：`xgb / jygs`
- 热点标的窗口切换：`30 / 45 / 60 / 90`
- 盘后读模型 schema 与接口契约设计

### Out of Scope

- 缠论计算
- 缠论筛选
- 预选池
- 自选池
- blk 同步
- SSE
- 页面触发导出 / 重算

## 3. 术语定义

### 3.1 30天首板

定义为：按单一数据源、按完整交易日序列，在最近 30 个完整交易日窗口内，某板块只出现 1 段连续命中区间。

说明：

- “连续”按该数据源的完整交易日序列判断，不按自然日判断。
- 这是旧仓库 `freshquant/data/gantt_shouban30_service.py` 中 `single segment` 的正式语义。
- 该判定窗口固定 30，不随热点标的窗口按钮变化。

### 3.2 热点标的窗口

旧页里的第二窗口不是固定 90 天，而是可切换的 `30 / 45 / 60 / 90` 四档。

为了避免继续沿用误导性的 `days90` 命名，目标仓库统一命名为：

- `stock_window_days`

其作用范围：

- 板块列表中的“窗口标的数”
- 板块 hover 标的列表
- 板块下标的列表
- 标的命中次数统计

本期允许值严格对齐旧页：

- `30`
- `45`
- `60`
- `90`

### 3.3 标的列表

定义为：当前 `provider + as_of_date + stock_window_days` 语境下，属于某个 `30天首板` 板块的热点标的集合。

这不是缠论筛选结果，也不是预选池结果。

### 3.4 标的详情

本期将“标的详情”定义为：

- 某标的的历史全量热门理由

明确不受以下条件约束：

- 当前 `30天首板` 板块
- 当前 `stock_window_days`
- 当前 `as_of_date`

因此“标的详情”与 `shouban30` 上下文是“页面入口触发关系”，而不是“数据范围收缩关系”。

## 4. 迁移方案对比

### 方案 A：继续扩展现有读模型

- 继续使用目标仓库现有 `freshquant_gantt` 分库
- 扩展现有 `shouban30_plates` / `shouban30_stocks`
- 详情复用全局 `stock_hot_reason_daily`

优点：

- 最符合 RFC 0006 已建立的盘后读模型方向
- 不重新引入旧仓库 `DBpipeline + export + SSE + blk` 形态
- 页面首期依赖清晰

缺点：

- 需要修正现有 `shouban30` schema

### 方案 B：新增页面专用 facade

- 底层仍然基于读模型
- 但再包一层 `/api/gantt/shouban30/page/*`

优点：

- 页面接口更统一
- 二期功能可更平滑扩展

缺点：

- 首期过重
- 引入一层薄封装但没有实际必要

### 方案 C：复刻旧页后再阉割

- 直接迁旧页路由、service、API
- 再手动删掉缠论和池子功能

优点：

- 前端改动最少

缺点：

- 与目标仓库当前架构冲突最大
- 会把旧闭环重新带回目标仓库

### 推荐方案

采用 **方案 A**。

理由：

- 本期只迁首期页面，不应顺带迁回旧仓库整套闭环。
- 目标仓库已有 `freshquant_gantt` 读模型基础，扩展它比新建一套并行体系更稳。
- “标的详情”已经能与现有 `stock_hot_reason_daily` 对齐，无需为 `shouban30` 重复建模。

## 5. 数据边界

### 5.1 单一事实源

首期页面的数据来源固定为：

- `freshquant_gantt.shouban30_plates`
- `freshquant_gantt.shouban30_stocks`
- `freshquant_gantt.stock_hot_reason_daily`

页面禁止：

- 请求期重算
- 回退到旧仓库 `DBpipeline`
- 依赖旧页 `POST /api/gantt/shouban30/export`

### 5.2 盘后产出原则

所有 `shouban30` 列表数据必须由盘后任务预先产出。

页面只查询，不负责导出或重算。

## 6. 读模型设计

### 6.1 `shouban30_plates`

建议唯一键：

- `provider + plate_key + as_of_date + stock_window_days`

建议字段：

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

说明：

- 不再使用 `stocks_count_90` 命名
- 第二窗口成为正式 schema 维度，而不是 UI 临时状态

### 6.2 `shouban30_stocks`

建议唯一键：

- `provider + plate_key + code6 + as_of_date + stock_window_days`

建议字段：

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

说明：

- 不再使用 `hit_count_90` 命名
- `hit_count_window` 对应当前按钮选中的第二窗口
- `hit_count_30` 保留，因为它属于 `30天首板` 主上下文

### 6.3 不进入首期读模型的字段

本期不进入 `shouban30_stocks` 的字段：

- `reasons[]` 明细
- 缠论 `calc_meta`
- 预选池状态
- 自选池状态
- blk 状态

原因：

- 标的详情已改为历史全量热门理由，直接复用 `stock_hot_reason_daily`
- 这些字段分别属于二期能力

### 6.4 标的详情数据源

标的详情直接复用现有全局热门理由读模型：

- `stock_hot_reason_daily`

因此详情接口无需再为 `shouban30` 建专门集合。

## 7. API 契约

### 7.1 `GET /api/gantt/shouban30/plates`

参数：

- `provider=xgb|jygs`
- `stock_window_days=30|45|60|90`
- `as_of_date=YYYY-MM-DD` 可选

返回：

- `data.items[]`
- `data.meta.as_of_date`
- `data.meta.stock_window_days`
- `data.meta.available_as_of_dates` 可选

### 7.2 `GET /api/gantt/shouban30/stocks`

参数：

- `provider=xgb|jygs`
- `plate_key`
- `stock_window_days=30|45|60|90`
- `as_of_date=YYYY-MM-DD` 可选

返回：

- `data.items[]`
- `data.meta.as_of_date`
- `data.meta.stock_window_days`

### 7.3 `GET /api/gantt/stocks/reasons`

参数：

- `code6`
- `provider=all|xgb|jygs`
- `limit=0`

返回：

- `data.items[]`

每条详情记录字段：

- `date`
- `time`
- `provider`
- `plate_name`
- `plate_reason`
- `stock_reason`

说明：

- 该接口不是 `shouban30` 专属接口
- 但会作为 `shouban30` 首期“标的详情”的正式接口

## 8. 页面交互设计

### 8.1 页面入口

新增路由：

- `/gantt/shouban30`

### 8.2 默认行为

首次进入页面：

- 默认 `provider=xgb`
- 默认 `stock_window_days=30`
- 默认取该条件下最新 `as_of_date`

### 8.3 交互行为

- 切换 `provider`
  - 刷新板块列表
  - 清空当前板块、标的、详情选中态
- 切换 `stock_window_days`
  - 刷新板块列表
  - 清空当前板块、标的、详情选中态
- 点击板块
  - 加载板块下标的列表
- 点击标的
  - 加载历史全量热门理由详情

### 8.4 页面不做的事情

- 不触发导出
- 不触发重算
- 不加载缠论结果
- 不显示预选池 / 自选池操作

## 9. 错误语义

- 参数非法：HTTP `400`
  - 如 `provider` 非法
  - `stock_window_days` 非法
  - `plate_key` 缺失
  - `code6` 非法
- 数据不存在：HTTP `200 + 空 items`
- 盘后读模型未构建：
  - 页面为空态
  - 不在请求期兜底现算
- 标的详情接口失败：
  - 不影响左侧板块和标的列表
  - 仅详情区显示错误或空态

## 10. 验收标准

- 能访问 `/gantt/shouban30`
- 能在 `xgb / jygs` 间切换
- 能在 `30 / 45 / 60 / 90` 热点标的窗口间切换
- 板块列表只展示 `30天首板` 结果，不是普通热点板块列表
- 板块列表展示：
  - 板块名
  - 30天出现次数
  - 连续区间
  - 板块理由
  - 窗口标的数
- 点击板块后能展示对应标的列表
- 标的列表计数字段会随 `stock_window_days` 变化
- 点击标的后，详情区展示该标的历史全量热门理由
- 页面全过程不触发导出 / 重算 / 缠论 / SSE / blk / 池子逻辑

## 11. 后续 RFC 留口

本设计故意为后续阶段保留术语，但不进入实现范围：

- 缠论计算
- 缠论筛选
- 预选池
- 自选池
- blk 同步

这些能力需要独立 RFC，不在本期首期页面迁移中一起绑定。
