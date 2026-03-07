# KlineSlim 左侧股票池与热门原因历史设计

**日期**：2026-03-07

## 背景

目标仓库当前的 `KlineSlim` 只有主图、周期切换和默认持仓解析，没有旧分支左侧股票池列表，也没有标的 hover 热门详情。用户要求：

- 对 `KlineSlim` 页面恢复最小左侧股票池列表；
- 左侧顺序固定为 `持仓股 -> must_pool -> stock_pools -> stock_pre_pools`；
- `stock_pre_pools` 展示所有分类合并后的结果；
- hover 改为显示该标的“从近到远的历史热门记录”，字段为：
  - 数据来源
  - 热门板块名字
  - 板块理由
  - 标的理由
- 该数据要跟 Dagster 现有每日热门板块 / 热门标的盘后同步链一起构建。

## 目标

- 用最小改动恢复 `KlineSlim` 的可用侧栏。
- 保持列表项信息密度足够，统一显示 `标的名称 + 代码`。
- 恢复旧分支核心工作流里“默认持仓展开 + 同时只展开一个列表”的行为。
- 为非持仓列表补单条删除入口，直接操作当前数据库池子。
- 不依赖盘中热门标的或旧快照板块链路。
- 用一个稳定的读模型和查询接口支撑 hover。

## 非目标

- 不恢复旧 `KlineSlim` 的完整侧边工作台、grid、多余池子和拖拽编辑。
- 不显示“所属板块快照”。
- 不新增新的 schedule、数据库或第三方服务。

## 现状结论

- 当前 [`KlineSlim.vue`](/D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/KlineSlim.vue) 与 [`kline-slim.js`](/D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/js/kline-slim.js) 是轻量版，没有左侧列表。
- 现有 4 个列表接口仍然在 [`routes.py`](/D:/fqpack/freshquant-2026.2.23/freshquant/rear/stock/routes.py) 中可用：
  - `/api/get_stock_position_list`
  - `/api/get_stock_must_pools_list`
  - `/api/get_stock_pools_list`
  - `/api/get_stock_pre_pools_list`
- 其中 [`freshquant.stock_service.get_stock_pre_pools_list`](/D:/fqpack/freshquant-2026.2.23/freshquant/stock_service.py) 目前把空 `category` 解释成 `category=""`，不符合“全分类合并展示”。
- 目标仓库当前已有 [`gantt_stock_daily`](/D:/fqpack/freshquant-2026.2.23/freshquant/data/gantt_readmodel.py) 与 [`plate_reason_daily`](/D:/fqpack/freshquant-2026.2.23/freshquant/data/gantt_readmodel.py)，但没有专门的“按股票聚合历史热门原因”读模型。
- 旧分支已有可参考实现：
  - [`/api/gantt/shouban30/stocks/reasons`](/D:/fqpack/freshquant/freshquant/rear/gantt/shouban30_routes.py)
  - [`list_stock_reasons()`](/D:/fqpack/freshquant/freshquant/data/gantt_shouban30_service.py)

## 方案比较

### 方案 A：新增 `stock_hot_reason_daily` 读模型并为 KlineSlim 提供专用接口（推荐）

- 盘后从 `gantt_stock_daily + plate_reason_daily` 构建按股票聚合的热门原因事实。
- 前端 hover 时只查 `/api/gantt/stocks/reasons?code6=...`。

优点：

- 数据来源清晰，和当前 `freshquant_gantt` 读模型体系一致。
- hover 读取轻，不需要临时 join。
- 不依赖 `shouban30` 导出页状态。

缺点：

- 需要补一个读模型、一个新接口和一个 Dagster op。

### 方案 B：hover 时现查 `gantt_stock_daily + plate_reason_daily`

优点：

- 后端少一个集合。

缺点：

- hover 请求变重，重复 join。
- 很难保证排序和历史聚合逻辑长期稳定。

### 方案 C：直接复用旧 `shouban30` 导出集合

优点：

- 旧逻辑已存在。

缺点：

- 依赖导出页专题数据，不适合作为 `KlineSlim` 常规事实源。
- 会把目标仓库重新绑回旧专题实现。

## 设计

### 1. 左侧侧栏

- 在 `KlineSlim` 页面增加固定左侧栏，右侧仍保留现有主图区域。
- 侧栏只恢复 4 组：
  - 持仓股
  - must_pool
  - stock_pools
  - stock_pre_pools
- 每组能力只保留：
  - 展示名称与代码
  - 点击切换当前标的
  - 当前标的高亮
  - hover 显示热门原因弹层
- 列表项统一用两行信息：
  - 第一行展示标的名称
  - 第二行展示 6 位代码
  - 名称缺失时第一行回退代码，避免空白
- 侧栏采用 accordion：
  - 默认仅展开 `持仓股`
  - 打开某个折叠列表时自动收起其余列表
  - 点击当前已展开列表时允许其收起
- 删除按钮只出现在 `must_pool / stock_pools / stock_pre_pools`，不出现在 `持仓股`
- 删除前弹确认框；删除动作与点击选中分离，避免误切换主图标的

### 2. `stock_pre_pools` 语义

- `category` 缺省或为空时，后端不再过滤分类，直接按 `datetime desc` 返回全量结果。
- `KlineSlim` 不额外提供分类切换。

### 3. 热门原因读模型

- 新增集合：`freshquant_gantt.stock_hot_reason_daily`
- 每条记录表示“一只股票在某个交易日、某个 provider、某个板块下的一条热门事件”。
- 字段：
  - `trade_date`
  - `provider`
  - `code6`
  - `name`
  - `plate_key`
  - `plate_name`
  - `plate_reason`
  - `stock_reason`
  - `time`
  - `reason_ref`
  - `updated_at`

### 4. 数据构建

- 从 `gantt_stock_daily` 读取当日热门标的事件。
- 用 `(provider, trade_date, plate_key)` 关联 `plate_reason_daily`。
- 生成 `stock_hot_reason_daily` 当日记录。
- 索引重点服务两类查询：
  - 按 `(provider, trade_date, plate_key, code6)` upsert
  - 按 `code6` 倒序读取历史

### 5. 后端接口

- 新增 `GET /api/gantt/stocks/reasons`
- 默认 `provider=all`
- 返回 `data.items`
- 每项字段：
  - `date`
  - `time`
  - `provider`
  - `plate_name`
  - `plate_reason`
  - `stock_reason`
- 排序：`date desc -> time desc`

### 6. 前端 hover

- hover 某个标的时，懒加载 `getGanttStockReasons({ code6 })`
- 前端按 `code6` 本地缓存，避免重复请求
- 弹层三种状态：
  - 加载中
  - 暂无热门记录
  - 加载失败

### 7. 列表删除与刷新策略

- 不新增后端接口，直接复用现有删除接口：
  - `deleteFromStockMustPoolsByCode`
  - `deleteFromStockPoolsByCode`
  - `deleteFromStockPrePoolsByCode`
- 删除后刷新策略保持最小一致性：
  - 删除 `must_pool`：只刷新 `must_pool`
  - 删除 `stock_pools`：刷新 `stock_pools`，同时刷新 `must_pool`
  - 删除 `stock_pre_pools`：只刷新 `stock_pre_pools`
- 如果删除的是当前主图标的，不强制跳转其它标的，只从列表中消失。

### 8. Dagster

- 在 [`job_gantt_postclose`](/D:/fqpack/freshquant-2026.2.23/morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py) 中新增 `op_build_stock_hot_reason_daily`
- 顺序放在：
  - `op_build_gantt_daily` 之后
  - `op_build_shouban30_daily` 之前

## 落地文件范围

- 后端读模型：
  - [`freshquant/data/gantt_readmodel.py`](/D:/fqpack/freshquant-2026.2.23/freshquant/data/gantt_readmodel.py)
- 后端路由：
  - [`freshquant/rear/gantt/routes.py`](/D:/fqpack/freshquant-2026.2.23/freshquant/rear/gantt/routes.py)
- 股票池服务：
  - [`freshquant/stock_service.py`](/D:/fqpack/freshquant-2026.2.23/freshquant/stock_service.py)
- Dagster：
  - [`morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`](/D:/fqpack/freshquant-2026.2.23/morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py)
  - [`morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py`](/D:/fqpack/freshquant-2026.2.23/morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py)
- 前端 API 与页面：
  - [`morningglory/fqwebui/src/api/ganttApi.js`](/D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/api/ganttApi.js)
  - [`morningglory/fqwebui/src/api/stockApi.js`](/D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/api/stockApi.js)
  - [`morningglory/fqwebui/src/views/KlineSlim.vue`](/D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/KlineSlim.vue)
  - [`morningglory/fqwebui/src/views/js/kline-slim.js`](/D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/js/kline-slim.js)

## 验收标准

- 左侧 4 组列表按固定顺序展示。
- 默认仅展开 `持仓股`，且任一时刻最多只有 1 个列表展开。
- 左侧列表项统一展示 `标的名称 + 代码`。
- `must_pool / stock_pools / stock_pre_pools` 支持单条删除。
- `stock_pre_pools` 在不传分类时显示全量合并结果。
- 点击列表项后主图区切换标的。
- 悬浮时显示从近到远的历史热门记录。
- Dagster 盘后任务能写出 `stock_hot_reason_daily`。

## 风险

- 如果 `gantt_stock_daily` 某些记录没有可 join 的板块理由，读模型构建需要明确 fail-fast 还是跳过策略。
- 当前 `KlineSlim` 已与旧页面分叉，恢复侧栏时必须避免夹带旧 grid/workbench 逻辑。
- 盘后任务增加一步后会增长执行耗时，需要通过只处理单日数据来控制成本。
