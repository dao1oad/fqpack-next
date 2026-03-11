# RFC 0031: Gantt Shouban30 筛选结果落库与股票池/blk 同步

- **状态**：Implementing
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-11
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

当前目标仓库的 `/gantt/shouban30` 已经完成首期页面、盘后缠论快照和额外筛选按钮，但仍然只有“读快照”的能力：

- 页面可以筛选、查看板块与标的
- 页面不能把当前筛选结果写回项目股票池
- 页面不能同步旧分支同用途的 `30RYZT.blk`
- 页面也没有“预选池 -> 自选股 -> must_pool”这一条人工整理链路

旧分支 `D:\fqpack\freshquant` 已有一套更完整的操作面：

- `/api/gantt/shouban30/chanlun/filter` 可以得到人工筛选结果
- 结果可以进入旧分支的“预选池 / 自选股”
- 同时会覆盖写 `30RYZT.blk`
- 页面上还能继续把自选股推入 `must_pool`

但旧分支的数据模型与目标仓并不一致。旧分支主要使用：

- `DBpipeline.sanshi_zhangting_pro`
- `DBpipeline.sanshi_zhangting_watchlist`
- `30RYZT.blk`

而当前目标仓的正式池子语义已经收敛为：

- `stock_pre_pools`
- `stock_pools`
- `must_pool`

因此，本 RFC 要解决的不是“把旧页原样搬过来”，而是把旧页的人工作业流程映射到当前仓正式数据模型中，并在共享集合前提下明确覆盖边界。

## 2. 目标（Goals）

- 在 `/gantt/shouban30` 现有“条件筛选”按钮组后新增 `筛选` 按钮，把当前可见筛选结果保存到当前仓的 `stock_pre_pools`。
- 在板块列表每一行新增 `保存到 pre_pools` 按钮，只把当前板块对应的可见标的覆盖写入预选池。
- 同步覆盖写旧分支同用途的 `30RYZT.blk`，并保持 blk 顺序与页面当前保存顺序一致。
- 在页面新增 `pre_pool` 与 `stockpools` 工作标签页。
- `pre_pool` 标签页支持：
  - 展示本票管理范围内的预选池记录
  - 每行 `加入 stockpools`
  - 每行 `删除`
- `stockpools` 标签页支持：
  - 展示本票管理范围内的自选股记录
  - 每行 `加入 must_pools`
  - 每行 `删除`
- 保持当前 `/gantt/shouban30` 的读模型、盘后快照和额外筛选逻辑不变，不恢复旧分支的导出/SSE/重算运行面。

## 3. 非目标（Non-Goals）

- 不恢复旧分支 `sanshi_zhangting_pro / sanshi_zhangting_watchlist` 两张独立集合。
- 不把 `/gantt/shouban30` 改回盘中实时计算页面。
- 不在本票里做全站股票池管理页重构。
- 不引入新的生产部署、数据库批量迁移或高风险交易动作。
- 不新增 must_pool 配置弹窗；本票沿用旧页默认参数直写 must_pool。
- 不让 `30RYZT.blk` 镜像整个 `stock_pre_pools` 或整个 `stock_pools`。

## 4. 范围（Scope）

**In Scope**

- `/gantt/shouban30` 页面新增“保存当前筛选结果”“按板块保存到 pre_pools”“pre_pool / stockpools 标签页”。
- 后端新增 `shouban30` 专用的池子编排服务与 HTTP 写接口。
- `stock_pre_pools` / `stock_pools` 新增一组仅由 `shouban30` 页面管理的专用分类。
- `30RYZT.blk` 的覆盖写、删除后重同步与顺序保持。
- `stockpools -> must_pool` 的无弹窗默认参数写入。

**Out of Scope**

- 非 `shouban30` 页面复用这套专用分类工作区。
- `must_pool` 全量展示页。
- `stock_pre_pools` / `stock_pools` 既有通用接口的统一重写。
- 旧分支“两台同步”“cluster must pool”“独立 watchlist 集合”的迁回。

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- `freshquant/shouban30_pool_service.py`
  - 负责页面专用工作区语义
  - 负责“覆盖保存当前筛选结果/单板块结果”
  - 负责 `30RYZT.blk` 覆盖写与重同步
  - 负责 `pre_pool -> stock_pools -> must_pool` 的链式操作
- `freshquant/rear/gantt/routes.py`
  - 对外暴露 `shouban30` 专用写接口和标签页读接口
- `morningglory/fqwebui/src/api/ganttShouban30.js`
  - 增加页面专用接口封装
- `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`
  - 负责按钮、标签页、列表和状态切换

**不负责（Must Not）**

- 不直接改写其他来源写入的 `stock_pre_pools` 记录
- 不直接改写其他来源写入的 `stock_pools` 记录
- 不让 `30RYZT.blk` 承担“全站股票池镜像”职责
- 不替代现有 `/api/get_stock_pre_pools_list`、`/api/get_stock_pools_list` 的通用管理入口

**依赖（Depends On）**

- RFC 0017：`/gantt/shouban30` 首期页面
- RFC 0023：`shouban30` 盘后缠论快照
- RFC 0027：页面额外筛选按钮
- 当前仓 `stock_pre_pools / stock_pools / must_pool` 的正式语义
- `TDX_HOME` 指向的通达信目录

**禁止依赖（Must Not Depend On）**

- 旧分支 `DBpipeline.sanshi_zhangting_pro`
- 旧分支 `DBpipeline.sanshi_zhangting_watchlist`
- 页面前端自己拼接 blk 文件
- 生产环境或真实交易操作的自动执行

## 6. 对外接口（Public API）

### 6.1 新增页面专用写接口

#### `POST /api/gantt/shouban30/pre-pool/replace`

用途：

- 覆盖保存“当前筛选结果”或“当前板块结果”到 `stock_pre_pools` 的 `shouban30` 专用分类
- 同步覆盖写 `30RYZT.blk`

请求体建议字段：

- `items[]`
  - `code6`
  - `name`
  - `plate_key`
  - `plate_name`
  - `provider`
  - `hit_count_window`
  - `latest_trade_date`
- `replace_scope`
  - `current_filter`
  - `single_plate`
- `stock_window_days`
- `as_of_date`
- `selected_extra_filters[]`
- `plate_key`（当 `single_plate` 时必填）

返回：

- `saved_count`
- `deleted_count`
- `category`
- `blk_sync`
  - `success`
  - `file_path`
  - `count`

错误语义：

- `400`：请求体为空、`items` 非 list、存在非法 `code6`
- `500`：Mongo 或 blk 写入失败

#### `GET /api/gantt/shouban30/pre-pool`

用途：

- 只返回 `shouban30` 页面工作区管理范围内的预选池记录

返回：

- `items[]`
- `meta.category`
- `meta.blk_filename`

#### `POST /api/gantt/shouban30/pre-pool/add-to-stock-pools`

用途：

- 把一条 `pre_pool` 工作区记录加入 `stock_pools` 工作区分类

请求体：

- `code6`

返回：

- `created | updated | already_exists`

#### `POST /api/gantt/shouban30/pre-pool/delete`

用途：

- 删除一条 `pre_pool` 工作区记录
- 删除后按剩余工作区顺序重写 `30RYZT.blk`

请求体：

- `code6`

#### `GET /api/gantt/shouban30/stock-pool`

用途：

- 只返回 `shouban30` 页面工作区管理范围内的自选股记录

#### `POST /api/gantt/shouban30/stock-pool/add-to-must-pool`

用途：

- 把一条工作区 `stock_pool` 记录推入 `must_pool`

默认参数沿用旧页语义：

- `stop_loss_price = 0.1`
- `initial_lot_amount = 50000`
- `lot_amount = 50000`
- `forever = true`
- `category = "三十涨停Pro"`

#### `POST /api/gantt/shouban30/stock-pool/delete`

用途：

- 删除一条工作区 `stock_pool` 记录

### 6.2 页面读接口保持不变

- `GET /api/gantt/shouban30/plates`
- `GET /api/gantt/shouban30/stocks`

当前页面仍然先读盘后快照，再基于前端已显示结果做“保存到工作区”的动作。

## 7. 数据与配置（Data / Config）

### 7.1 工作区分类（推荐假设，待 Human Review 确认）

由于 `stock_pre_pools` 与 `stock_pools` 在当前仓是共享集合，本 RFC 采用“专用分类隔离”作为默认方案：

- `stock_pre_pools.category = "三十涨停Pro预选"`
- `stock_pools.category = "三十涨停Pro自选"`
- `must_pool.category = "三十涨停Pro"`

说明：

- `pre-pool/stock-pool` 标签页只展示这两个专用分类
- 这避免 `/gantt/shouban30` 覆盖掉其他策略来源的池子记录
- 若 Human Review 明确要求“接管整张集合”，需单独修订本 RFC

### 7.2 `stock_pre_pools.extra`

为保持页面顺序与 blk 顺序一致，`pre_pool` 工作区记录新增这些字段：

- `extra.shouban30_order`
- `extra.shouban30_provider`
- `extra.shouban30_plate_key`
- `extra.shouban30_plate_name`
- `extra.shouban30_replace_scope`
- `extra.shouban30_stock_window_days`
- `extra.shouban30_as_of_date`
- `extra.shouban30_selected_filters`

### 7.3 `stock_pools.extra`

工作区自选股新增：

- `extra.shouban30_source = "pre_pool"`
- `extra.shouban30_from_category = "三十涨停Pro预选"`
- `extra.shouban30_provider`
- `extra.shouban30_plate_key`

### 7.4 blk 文件

- 文件名：`30RYZT.blk`
- 路径：`%TDX_HOME%/T0002/blocknew/30RYZT.blk`
- 文件内容只镜像 `stock_pre_pools.category = "三十涨停Pro预选"` 的当前工作区顺序

### 7.5 配置

- 必须依赖 `TDX_HOME`
- 不新增新的用户级配置开关
- `TDX_HOME` 缺失时，接口返回 500，并明确提示未配置通达信目录

## 8. 破坏性变更（Breaking Changes）

- `/gantt/shouban30` 页面会新增“写池子/写 blk”行为，不再是纯只读页面。
- 新增 `shouban30` 页面专用工作区分类：
  - `三十涨停Pro预选`
  - `三十涨停Pro自选`
- `30RYZT.blk` 将由当前仓正式接管，并只镜像 `三十涨停Pro预选`。

**影响面**

- 依赖旧“只读页面”假设的使用者
- 当前手工维护 `30RYZT.blk` 的操作习惯
- 直接查看 `stock_pre_pools / stock_pools` 的调用方，会看到新增分类

**迁移步骤**

1. 部署包含 RFC 0031 的前后端代码
2. 确保运行环境存在 `TDX_HOME`
3. 进入 `/gantt/shouban30`，使用 `筛选` 或 `保存到 pre_pools`
4. 从页面 `pre_pool` / `stockpools` 标签页继续完成人工整理

**回滚方案**

1. 回退 `shouban30` 页面和后端写接口改动
2. 删除 `三十涨停Pro预选` / `三十涨停Pro自选` 分类记录（仅当确认不再需要）
3. 恢复人工维护 `30RYZT.blk`

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- `D:\fqpack\freshquant\freshquant\rear\gantt\shouban30_routes.py`
  - 旧 `/chanlun/filter`、`/chanlun/pool/*`、`/chanlun/watchlist/*`
  - 映射为当前仓 `/api/gantt/shouban30/*` 下的页面专用工作区接口

- `D:\fqpack\freshquant\freshquant\data\gantt_shouban30_service.py`
  - 旧 `sanshi_zhangting_pro / sanshi_zhangting_watchlist / blk` 编排
  - 映射为当前仓 `stock_pre_pools / stock_pools / must_pool / 30RYZT.blk`

- `D:\fqpack\freshquant\morningglory\fqwebui\src\views\GanttShouban30.vue`
  - 旧页面上的 “加入预选池 / 加入 must / 删除 / 同步 blk”
  - 映射为 `GanttShouban30Phase1.vue` 的工作区按钮与标签页

## 10. 测试与验收（Acceptance Criteria）

- [x] 点击 `筛选` 时，当前可见标的会覆盖保存到 `stock_pre_pools` 的 `三十涨停Pro预选` 分类
- [x] 点击板块行 `保存到 pre_pools` 时，只覆盖当前板块的可见标的
- [x] 每次覆盖保存后，`30RYZT.blk` 会按页面保存顺序重写
- [x] `pre_pool` 标签页只展示 `三十涨停Pro预选`，并支持 `加入 stockpools` / `删除`
- [x] `stockpools` 标签页只展示 `三十涨停Pro自选`，并支持 `加入 must_pools` / `删除`
- [x] `加入 must_pools` 沿用旧页默认参数，无需新增弹窗
- [x] `TDX_HOME` 缺失时，blk 写接口会返回明确错误，而不是静默成功
- [x] `pytest`、前端 node tests 与 `npm build` 通过

## 11. 风险与回滚（Risks / Rollback）

- 风险：用户真实期望是“覆盖整张 `stock_pre_pools`”，而不是专用分类。
  - 缓解：本 RFC 明确把这条写成 Human Review 待确认边界；默认采用最保守方案。

- 风险：`30RYZT.blk` 顺序与页面顺序漂移。
  - 缓解：在 `stock_pre_pools.extra` 固化 `shouban30_order`，接口与 blk 同时基于该顺序。

- 风险：`must_pool` 直写默认参数与用户期望不一致。
  - 缓解：沿用旧页默认值，并在 Human Review comment 里单独列为确认项。

- 回滚：撤回页面工作区按钮、后端写接口和新增分类记录；blk 回到人工维护。

## 12. 里程碑与拆分（Milestones）

- M1：RFC 0031 评审通过
- M2：后端工作区服务与 blk 写入落地
- M3：前端页面按钮、标签页和行级动作落地
- M4：TDD 回归、迁移记录和 Human Review 收口
