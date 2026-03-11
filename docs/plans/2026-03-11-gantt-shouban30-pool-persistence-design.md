# Gantt Shouban30 筛选结果落库设计

## 背景

`/gantt/shouban30` 现在已经能：

- 读取 `shouban30_plates / shouban30_stocks`
- 做额外条件筛选
- 展示板块、标的和理由详情

但它仍然是“只读快照页”。`FRE-7` 需要补的是人工整理工作区：

- 当前筛选结果保存到预选池
- 单板块保存到预选池
- 预选池加入自选股
- 自选股加入 must_pool
- 预选池同步到 `30RYZT.blk`

旧分支已经有近似能力，但旧分支用的是独立集合 `sanshi_zhangting_pro / sanshi_zhangting_watchlist`。当前仓正式数据模型已经收口到 `stock_pre_pools / stock_pools / must_pool`，不能再把旧集合原样搬回来。

## 目标

- 在不破坏现有 `shouban30` 读模型的前提下，补齐页面工作区写操作。
- 明确共享集合下的覆盖边界，避免一个页面清空其他策略来源的池子。
- 保持 blk 文件语义稳定，让 `30RYZT.blk` 始终对应这张页面的“预选池工作区”。

## 非目标

- 不恢复旧分支的导出/SSE/独立 watchlist 集合。
- 不把 `shouban30` 变成全站股票池管理页。
- 不新增 must_pool 弹窗参数编辑。

## 方案对比

### 方案 A：直接接管整张 `stock_pre_pools / stock_pools`

做法：

- `筛选` 按钮直接清空整个 `stock_pre_pools`
- `pre_pool / stockpools` 标签页展示整张集合
- `30RYZT.blk` 镜像整张 `stock_pre_pools`

优点：

- 用户表面感知最接近“当前项目预选池就是这张集合”

缺点：

- 风险过高，会删除其他策略来源写入的池子
- `30RYZT.blk` 语义从“首板工作区”变成“全站预选池镜像”，边界失控

不采用。

### 方案 B：恢复旧分支独立集合，再异步同步到正式池子

做法：

- 重新引入 `sanshi_zhangting_pro / sanshi_zhangting_watchlist`
- 页面先写独立集合
- 再同步到 `stock_pre_pools / stock_pools / blk`

优点：

- 最接近旧页语义

缺点：

- 形成双份真相源
- 当前仓已经有正式池子语义，重新引入旧集合会加重冗余

不采用。

### 方案 C：在正式池子上增加 `shouban30` 专用工作区分类

做法：

- `stock_pre_pools` 用固定分类 `三十涨停Pro预选`
- `stock_pools` 用固定分类 `三十涨停Pro自选`
- `must_pool` 仍沿用旧页默认分类 `三十涨停Pro`
- `30RYZT.blk` 只镜像 `三十涨停Pro预选`
- 页面标签页只展示这两个工作区分类

优点：

- 继续使用当前仓正式数据模型
- 不会误删其他来源的池子
- blk 语义清晰，始终只镜像页面工作区

缺点：

- “页面工作区”不再等于整张 `stock_pre_pools`
- 需要新后端编排服务来处理覆盖保存、顺序和 blk 同步

本次采用方案 C。

## 设计

### 1. 数据模型

页面不直接接管整张共享集合，而是在正式集合中开两条受控工作区分类：

- `stock_pre_pools.category = "三十涨停Pro预选"`
- `stock_pools.category = "三十涨停Pro自选"`

`must_pool` 保持当前正式集合，但 `加入 must_pool` 默认写：

- `category = "三十涨停Pro"`
- `stop_loss_price = 0.1`
- `initial_lot_amount = 50000`
- `lot_amount = 50000`
- `forever = true`

这些默认值直接复用旧页，不新增弹窗。

### 2. 预选池顺序与 blk 顺序

`30RYZT.blk` 不能只按 Mongo 默认排序，因为页面“当前筛选结果”的顺序必须保持。

因此保存到 `stock_pre_pools` 时会额外写入：

- `extra.shouban30_order`
- `extra.shouban30_provider`
- `extra.shouban30_plate_key`
- `extra.shouban30_plate_name`
- `extra.shouban30_replace_scope`
- `extra.shouban30_selected_filters`
- `extra.shouban30_as_of_date`
- `extra.shouban30_stock_window_days`

后端专用列表接口和 blk 重写都以 `extra.shouban30_order` 为准。

### 3. 后端服务边界

新增 `freshquant/shouban30_pool_service.py`，只负责页面工作区语义：

- `replace_pre_pool(items, scope, context)`
- `list_pre_pool()`
- `add_pre_pool_item_to_stock_pool(code6)`
- `delete_pre_pool_item(code6)`
- `list_stock_pool()`
- `add_stock_pool_item_to_must_pool(code6)`
- `delete_stock_pool_item(code6)`
- `sync_pre_pool_to_blk()`

这个服务内部复用已有正式能力：

- `save_a_stock_pre_pools`
- `save_a_stock_pools`
- `must_pool.import_pool`

同时补一个简易 blk writer：

- 从 `TDX_HOME/T0002/blocknew/30RYZT.blk` 写入 GBK 文本
- 上海代码写 `1{code6}`，深圳代码写 `0{code6}`

### 4. 路由设计

保持现有只读 API 不变，只新增页面专用工作区接口：

- `POST /api/gantt/shouban30/pre-pool/replace`
- `GET /api/gantt/shouban30/pre-pool`
- `POST /api/gantt/shouban30/pre-pool/add-to-stock-pools`
- `POST /api/gantt/shouban30/pre-pool/delete`
- `GET /api/gantt/shouban30/stock-pool`
- `POST /api/gantt/shouban30/stock-pool/add-to-must-pool`
- `POST /api/gantt/shouban30/stock-pool/delete`

这样可以把“页面工作区”的边界收在 `/api/gantt/shouban30/*` 下，不污染通用 stock routes。

### 5. 前端交互

在 [`morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`](../../morningglory/fqwebui/src/views/GanttShouban30Phase1.vue) 增加：

- 条件筛选按钮组后的 `筛选` 按钮
- 板块列表中的 `保存到 pre_pools` 按钮
- 页面底部或右侧新增 `pre_pool / stockpools` 标签页

交互规则：

- `筛选`：保存当前“筛选后可见”的所有标的
- `保存到 pre_pools`：保存当前板块对应的筛选后可见标的
- `pre_pool -> 加入 stockpools`：单条迁移/复制到 `三十涨停Pro自选`
- `pre_pool -> 删除`：删除后自动重写 blk
- `stockpools -> 加入 must_pools`：按默认值写入 must_pool
- `stockpools -> 删除`：只删除工作区自选，不影响 must_pool

### 6. 错误处理

- `TDX_HOME` 缺失：后端返回显式错误，前端 toast 提示，不做静默降级
- 传入非法代码：后端 400
- Mongo 写成功但 blk 失败：整体视为失败，不返回半成功
- `must_pool` 已存在：返回 `already_exists`，前端提示幂等成功

## 测试策略

### 1. 后端服务测试

新增 `freshquant/tests/test_shouban30_pool_service.py`，覆盖：

- 专用分类覆盖替换
- 删除 stale 记录
- `extra.shouban30_order`
- blk 输出顺序
- `pre_pool -> stock_pool`
- `stock_pool -> must_pool`

### 2. 路由测试

扩展 `freshquant/tests/test_gantt_routes.py`：

- `replace pre_pool` 成功/参数错误
- `pre_pool list`
- `stock_pool list`
- 删除后 blk 重同步

### 3. 前端状态测试

新增 `morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs`，覆盖：

- 当前筛选结果到请求 payload 的归一化
- 标签页列表映射
- 行级动作成功后的本地状态刷新

### 4. 构建验证

- `py -3.12 -m pytest ...`
- `node --test ...`
- `npm --prefix morningglory/fqwebui run build`

## 风险

- 用户可能真正需要“接管整张 `stock_pre_pools`”，而不是专用分类。
- `30RYZT.blk` 依赖 `TDX_HOME`，运行环境若未配置会阻塞保存动作。
- `must_pool` 默认参数虽然与旧页一致，但仍可能与当前用户预期不完全一致。

## 结论

当前仓是共享池子架构，不能把 `shouban30` 页面当成唯一写入口。最稳妥的做法是在正式集合上建立 `shouban30` 专用工作区分类，让页面完成“筛选 -> 预选 -> 自选 -> must_pool”的闭环，同时把 `30RYZT.blk` 绑定到这条工作区语义，而不是绑定到整张集合。
