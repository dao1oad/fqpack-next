# Gantt Shouban30 筛选按钮与理由悬浮框设计

## 背景

当前 `/gantt/shouban30` 页面已经切换为“只读盘后快照”的语义：

- 页面不再前端现算缠论结构
- 板块与标的列表来自 `/api/gantt/shouban30/plates` 与 `/api/gantt/shouban30/stocks`
- `shouban30` 数据由 Dagster 盘后构建

但页面还有两个明显问题：

1. 理由悬浮框仍使用 Element 默认 `show-overflow-tooltip`，表现为黑色背景、长条形、长文本时横跨页面，阅读性很差。
2. 左侧列表缺少面向当前热门标的的组合筛选能力，无法在“缠论通过”的基础上继续收紧到更可操作的子集。

本次需求是：

- 将板块理由和标的理由悬浮框改造成更适合阅读的卡片式 popover，样式参考 `KlineSlim` 页持仓股列表悬浮框。
- 在左侧列表增加一组可多选的筛选按钮，并在当前列表上继续筛选。

## 目标

- 将 `/gantt/shouban30` 的三处“理由”悬浮展示统一替换为可读性更好的卡片式 popover。
- 在当前“缠论通过股”基础上增加三个可组合筛选条件：
  - `融资标的`
  - `均线附近`
  - `优质标的`
- 三个条件支持多选、单个取消，多选时取交集，条件越多结果越少。
- 保持 `/gantt/shouban30` 页面继续以盘后快照为事实来源，不回退到前端散调或读时临时计算。

## 非目标

- 不新增新的页面路由。
- 不将筛选状态写入 URL。
- 不把理由悬浮框改成新的数据请求链路；本次只消费页面已有理由字段。
- 不将三类按钮的各种组合计数预先固化到 `shouban30_plates`。
- 不改变现有 `shouban30` 默认缠论筛选口径。

## 当前实现事实

### 页面与 tooltip

当前 [`morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`](../../morningglory/fqwebui/src/views/GanttShouban30Phase1.vue) 在以下列上使用了 `show-overflow-tooltip`：

- 左侧板块表：`reason_text`
- 中间标的表：`latest_reason`
- 右侧详情表：`plate_name` 与“理由”列

这直接导致了默认黑色长条 tooltip。

### 参考页面

[`morningglory/fqwebui/src/views/KlineSlim.vue`](../../morningglory/fqwebui/src/views/KlineSlim.vue) 已有更适合阅读的 `el-popover` 样式：

- 浅底深字
- 固定最大宽度
- 文本换行
- 自定义 `popper-class`
- 窄屏下自动降级布局

本次 tooltip 设计以其交互与样式思路为参考，但不照搬异步 hover 请求链路。

### 当前 `shouban30` 读模型

当前 [`freshquant/data/gantt_readmodel.py`](../../freshquant/data/gantt_readmodel.py) 的 `shouban30_stocks` 已固化：

- 标的基础信息
- 热门命中信息
- 默认缠论快照字段

但还没有以下筛选字段：

- `融资标的`
- `均线附近`
- `优质标的`

## 筛选条件最终口径

### 1. 融资标的

- 以当前账户同步下来的 `om_credit_subjects` 为准。
- 数据来源是本项目现有 `order_management.credit_subjects` 同步链路，而不是交易所全市场静态名单。
- 命中规则以 `code6/symbol` 对应当前账户信用标的集合为准。

### 2. 均线附近

- 以 `as_of_date` 最近一个日线收盘价为准。
- 计算 `close` 相对 `ma250 / ma500 / ma1000` 的偏离百分比。
- 只要任意一条长均线满足“偏离处于 `0%~3%`”即命中。
- 这里的“附近”不是“高于均线即可”，而是严格的靠近区间判断。

建议固化以下辅助字段，便于页面展示与排障：

- `close_price`
- `ma250 / ma500 / ma1000`
- `ma250_distance_pct / ma500_distance_pct / ma1000_distance_pct`
- `near_long_term_ma_basis`

### 3. 优质标的

- 完全沿用旧分支 `run_xgt_plate_screener_loop.py` 中“获取热门板块股票”阶段的固定 `block_names` 语义。
- 初期名单以这组固定 block 的成员股票为准，不做增删。
- 初期导入允许先跑一次旧分支任务作为兜底基础名单，然后在本项目内查询使用。
- 后续由 Dagster 在本项目中每天盘后更新该名单。

固定 `block_names` 为：

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

## 方案选择

### 方案 A：前端只重做展示，筛选条件全部做进 `shouban30` 盘后快照

- tooltip 只改前端展示层
- 三个筛选条件都由 Dagster 盘后写入 `shouban30_stocks`
- 页面按钮只消费快照字段，本地做组合过滤

优点：

- 与当前“只读盘后快照”方向一致
- 页面打开性能稳定
- 筛选语义集中在后端
- `agg` 视图、本地分组、板块重算可以统一复用同一份字段

缺点：

- 需要扩展读模型和 Dagster 任务
- 需要补 RFC

### 方案 B：后端查询时临时富化

- 不改盘后落库
- 读取 `/api/gantt/shouban30/stocks` 时临时去查融资名单、日线数据、优质名单

优点：

- 少改盘后构建

缺点：

- 页面每次打开都要现查
- 语义不再是纯快照
- 比较容易把页面拖回慢路径

### 方案 C：前端散调多个接口本地计算

优点：

- 后端改动最少

缺点：

- 请求最散
- 首屏更慢
- 规则分散且难维护

### 结论

采用方案 A。

## 总体架构

### tooltip

- 当前页不再使用 `show-overflow-tooltip`
- 统一改为 `el-popover + 自定义 popper-class`
- 只消费页面已加载的本地理由文本，不新增 hover 请求

### 筛选

- `shouban30` 继续作为盘后快照页
- Dagster 盘后构建时，将三类筛选标记写入 `shouban30_stocks`
- 页面左侧新增三个筛选按钮
- 按钮组合过滤发生在前端，但只基于已返回的 stock rows

## 数据模型设计

### 新增基础集合：`quality_stock_universe`

用途：

- 维护“优质标的”基础集合，避免在每次构建 `shouban30` 时重新扫全部 block 库

建议字段：

- `code6`
- `block_names`
- `source_version`
- `updated_at`

语义：

- 一次性初始化时可由旧分支同口径任务导入
- 日常由本项目 Dagster 盘后更新覆盖

### 扩展 `shouban30_stocks`

新增字段：

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

说明：

- `credit_subject_snapshot_ready` 用于区分“未命中”和“融资名单未准备好”
- `quality_subject_snapshot_ready` 用于区分“未命中”和“优质名单未准备好”
- `near_long_term_ma_passed` 为单一布尔结果，但会保留距离与命中依据，便于前端展示

### `shouban30_plates`

- 不新增三类筛选按钮的聚合计数字段
- 仍保留当前缠论快照下的：
  - `stocks_count`
  - `candidate_stocks_count`
  - `failed_stocks_count`

原因：

- 按钮组合规则是多选取交集
- 组合结果更适合前端依据 `stock rows` 实时重算
- 不值得在库里预存多种按钮组合统计

## Dagster 与盘后更新链路

### 现有链路保留

`shouban30` 仍在现有 `job_gantt_postclose` 中构建，继续走：

- `job_gantt_postclose`
- `op_build_shouban30_daily`
- `_build_shouban30_snapshots_for_date()`
- `persist_shouban30_for_date()`

### 新增能力

在构建 `shouban30` 之前，补一段“优质标的基础集合更新”能力：

1. 读取固定 `block_names`
2. 基于本项目可直接访问的 `stock_block` 数据，生成去重后的 `quality_stock_universe`
3. 覆盖更新集合并打上 `source_version`
4. 再进入 `shouban30` 四档窗口构建

### `persist_shouban30_for_date()` 新职责

在现有缠论结果写入基础上，新增：

1. 读取当前账户 `om_credit_subjects`，构建信用标的 lookup
2. 读取 `quality_stock_universe`，构建优质标的 lookup
3. 获取股票 `as_of_date` 最近日线数据，计算 `close / ma250 / ma500 / ma1000` 与偏离百分比
4. 将三类筛选标记写入 `shouban30_stocks`

注意：

- 这轮不改变当前缠论口径，也不改变黑名单板块 / 北交所排除语义
- 四档窗口仍沿用同一条 `shouban30` 盘后构建链

## 接口语义

### `GET /api/gantt/shouban30/stocks`

- 路径与 query 参数保持不变
- 返回扩展：
  - `is_credit_subject`
  - `credit_subject_snapshot_ready`
  - `near_long_term_ma_passed`
  - `near_long_term_ma_basis`
  - `close_price`
  - `ma250 / ma500 / ma1000`
  - `ma250_distance_pct / ma500_distance_pct / ma1000_distance_pct`
  - `is_quality_subject`
  - `quality_subject_snapshot_ready`
  - `quality_subject_source_version`

### `GET /api/gantt/shouban30/plates`

- 路径保持不变
- 页面仍用其返回的 `stocks_count`
- 左侧按钮筛选后的板块数量不从后端取，而是前端基于筛选后的 `stock rows` 本地重算

## 前端交互设计

### 理由悬浮框

替换对象：

- 左侧板块理由
- 中间最近理由
- 右侧详情理由

展示要求：

- 浅色背景、深色文字
- 限制最大宽度，不横跨整页
- 文本自动换行，支持多行
- 移动端或窄屏自动降级布局

展示结构：

- 板块理由：标题 + 板块名 + 理由正文
- 最近理由：代码/名称 + 最近上榜日期 + 理由正文
- 详情理由：日期/时间/来源/板块 + 股票理由 + 板块理由

### 左侧筛选按钮

按钮：

- `融资标的`
- `均线附近`
- `优质标的`

语义：

- 可多选
- 可单个取消
- 多选取交集
- 全部取消时回到当前原始“缠论通过”列表
- 不写 URL，不跨页面保存

过滤流转：

1. 先取当前视图当前板块集合对应的原始“缠论通过股”
2. 对 stock rows 应用“满足全部已选条件”的交集过滤
3. 按过滤后的股票子集重算左侧板块列表与数量
4. 中间列表显示当前板块下的筛选结果

选择状态：

- 若当前选中板块在新结果里为空，自动切到筛选后第一个有结果的板块
- 若筛选后全空，左侧列表为空，中间显示“当前筛选条件下暂无标的”

## 异常语义

### 信用标的名单未准备好

- 不让整个 `shouban30` 构建失败
- `is_credit_subject = false`
- `credit_subject_snapshot_ready = false`
- 前端可显示轻量提示“融资标的名单未同步”

### 日线均线数据缺失

- `near_long_term_ma_passed = false`
- `close/ma/distance` 字段保留 `null`

### 优质名单基础集合缺失

- `is_quality_subject = false`
- `quality_subject_snapshot_ready = false`

### legacy snapshot

- 继续沿用现有 `shouban30 chanlun snapshot not ready` 语义
- 不新增前端兜底

## 测试策略

### 后端

- `freshquant/tests/test_gantt_readmodel.py`
  - `is_credit_subject` 计算正确
  - `near_long_term_ma_passed` 严格按 `0%~3%` 口径
  - `is_quality_subject` 命中固定 block 名单
  - 来源缺失时的 `*_snapshot_ready` 语义正确
- `freshquant/tests/test_gantt_routes.py`
  - `/api/gantt/shouban30/stocks` 返回新增字段
- `freshquant/tests/test_gantt_dagster_ops.py`
  - 盘后链路会在构建 `shouban30` 前更新优质名单
  - `quality_stock_universe` 更新与 `shouban30` 构建串联正确

### 前端

- `morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs`
  - 交集筛选逻辑正确
  - 板块重算正确
- 新增页面测试
  - 筛选按钮可多选和单独取消
  - 空结果下的板块与标的表现
  - popover 内容结构与文案

## 治理与实施前置

这轮变更会涉及：

- `shouban30_stocks` schema 扩展
- Dagster 盘后任务扩展
- 新增 `quality_stock_universe` 集合
- `/api/gantt/shouban30/stocks` 返回字段扩展
- 页面行为语义变化

因此在编码前必须补 RFC，并在实现时同步更新：

- `docs/migration/progress.md`
- `docs/migration/breaking-changes.md`

## 验收标准

- tooltip 不再是默认黑色长条，内容在桌面和窄屏都可读
- 三个按钮支持多选、单个取消，且多选取交集
- `融资标的` 以 `om_credit_subjects` 为准
- `均线附近` 严格按 `0%~3%` 距离口径
- `优质标的` 以固定 `block_names` 基础名单为准，并有盘后更新链路
- 左侧板块数量与中间标的列表都随筛选结果同步变化
- 页面不新增临时散调链路，仍以 `shouban30` 盘后快照为事实来源
