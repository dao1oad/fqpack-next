# KlineSlim 默认持仓标的设计

**日期**：2026-03-07

## 背景

当前从 [MyHeader.vue](/D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/MyHeader.vue) 点击 `KlineSlim` 按钮时，只会跳转到 `/kline-slim`。而 [KlineSlim.vue](/D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/KlineSlim.vue) 与 [kline-slim.js](/D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/js/kline-slim.js) 当前要求 query 中必须显式提供 `symbol`，否则页面只显示“请输入或通过 query 传入 `symbol`”的空态提示。

用户要求：

- 所有直接访问 `/kline-slim` 且未带 `symbol` 的情况，都自动取“当前持仓列表的第一个标的”作为默认标的。
- 导航栏按钮文案从 `KlineSlim` 改为 `行情图表`。

## 目标

- 让 `/kline-slim` 成为可直接访问的页面入口，而不是必须依赖外部 query 参数。
- 缺少 `symbol` 时，优先复用现有持仓列表接口解析默认标的。
- 保持已有 `symbol`、`period`、`endDate` 查询参数语义不变。

## 非目标

- 不新增后端接口。
- 不修改 `/api/stock_data` 的查询契约。
- 不自动触发 broker 或后端去同步持仓。
- 不改变“第一个持仓”的排序规则，直接使用 `/api/get_stock_position_list` 当前返回顺序。
- 不实现“最近查看标的”“收藏优先”“用户自定义默认标的”等扩展规则。

## 现状结论

- 前端现有可复用接口是 `GET /api/get_stock_position_list`，对应实现位于 [routes.py](/D:/fqpack/freshquant-2026.2.23/freshquant/rear/stock/routes.py)。
- 该接口最终读取 [holding.py](/D:/fqpack/freshquant-2026.2.23/freshquant/data/astock/holding.py) 中的 `get_stock_positions()`。
- 2026-03-07 当前运行环境下，`http://127.0.0.1:15000/api/get_stock_position_list` 返回空列表；`xt_positions` 与 `xt_positions:last_sync` 在当前新仓库并行部署实例中也未读到有效同步结果。因此本次前端能力落地后，若持仓仍为空，页面会继续停留在空态，这是数据现状，不是前端错误。

## 方案比较

### 方案 A：在 KlineSlim 页面自身解析默认标的（推荐）

- 当路由中已有 `symbol` 时，沿用现有逻辑加载主图与叠加图。
- 当路由中缺少 `symbol` 时，页面先请求 `/api/get_stock_position_list`，取第一个持仓的 `symbol`，再执行 `router.replace('/kline-slim?symbol=<first>&period=5m')`。
- 若持仓为空或接口失败，则不跳转，维持空态。

优点：

- 覆盖所有进入方式：导航点击、手工输入 URL、浏览器刷新、外部书签。
- 逻辑集中在页面内部，不把导航语义塞进 Header 或数据接口。

缺点：

- 首次访问无 `symbol` 的页面时，会多一次轻量持仓请求。

### 方案 B：只在导航栏点击时补 `symbol`

优点：

- 改动最小。

缺点：

- 不能覆盖用户直接访问 `/kline-slim` 的场景，不满足需求。

### 方案 C：后端为 `/api/stock_data` 隐式补默认标的

优点：

- 前端实现最少。

缺点：

- 破坏数据接口的显式语义，调试与排障成本更高。
- 把页面导航逻辑混进后端数据接口，边界不清晰。

## 设计

### 1. 入口行为

- [MyHeader.vue](/D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/MyHeader.vue) 仅修改按钮文案为 `行情图表`。
- Header 仍然直接跳转 `/kline-slim`，不在 Header 中提前查持仓或拼 query。
- [kline-slim.js](/D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/js/kline-slim.js) 在路由变化时增加“默认标的解析”分支：
  - `route.query.symbol` 非空：按现有逻辑继续执行。
  - `route.query.symbol` 为空：请求 `/api/get_stock_position_list`，尝试取首个持仓并替换路由。

### 2. 页面状态

- 页面新增一个轻量“默认标的解析中”的状态，仅在“无 `symbol` 且正在请求持仓列表”时出现。
- 解析中不显示当前空态文案，避免刚进入页面就看到误导性提示。
- 解析完成后分三种结果：
  - 解析成功：替换路由，进入现有图表加载流程。
  - 持仓为空：显示原空态提示。
  - 请求失败：显示空态，并保留一条轻量错误状态，且不影响用户手工输入 `symbol`。

### 3. 竞态控制

- 自动解析默认标的的请求必须服从当前页面已有的路由版本控制。
- 如果请求尚未返回，但用户已经手工输入了 `symbol` 或跳转到带 `symbol` 的新路由，旧请求结果必须丢弃，不能覆盖当前已选标的。
- 继续复用当前组件的 `routeToken` 风格控制，避免引入额外复杂状态机。

### 4. 失败与回退

- 若 `/api/get_stock_position_list` 返回空数组，不做重试死循环，直接停留空态。
- 若接口报错，不做自动降级到任意硬编码标的，避免隐式行为。
- 页面始终保留手工输入 `symbol` 的能力，用户可自行恢复。

## 落地文件范围

- 修改 [MyHeader.vue](/D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/MyHeader.vue)
  - 按钮文案从 `KlineSlim` 改为 `行情图表`
- 修改 [kline-slim.js](/D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/js/kline-slim.js)
  - 增加默认持仓标的解析逻辑
  - 增加解析中状态与竞态保护
- 修改 [KlineSlim.vue](/D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/KlineSlim.vue)
  - 增加“解析中”空态展示

## 验收标准

- 访问 `/kline-slim?symbol=sh510050` 时，行为与当前一致。
- 访问 `/kline-slim` 且持仓列表非空时，页面自动跳到 `/kline-slim?symbol=<first>&period=5m`。
- 访问 `/kline-slim` 且持仓列表为空时，页面保留空态提示，不报错、不死循环。
- 从导航栏点击进入、浏览器刷新、手工地址栏访问三种方式，行为一致。
- 导航栏按钮文案显示为 `行情图表`。

## 风险

- 当前运行环境里，持仓列表接口返回空数组，因此功能落地后短期内仍可能无法自动打开任何标的。
- 若后续需要保证一定能默认进入具体标的，需要单独修复 broker 到 `xt_positions` 的同步链路，不属于本次前端改动范围。
