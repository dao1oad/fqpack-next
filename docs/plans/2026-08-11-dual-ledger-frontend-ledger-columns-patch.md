# 双账本前端展示补丁（#549 收尾）

> 关联：GitHub Issue #549（双账本 base/t）、#548
> 状态：用户已确认三处全部补充显示；由实施会话按本规格实施，走 feature branch + PR。

## 背景

#549 已合并部署，但前端双账本展示有三处缺口，用户确认全部补齐：

1. 持仓列表表格（`StockPositionList.vue`）数据/双列已就绪，但入口未挂载；
2. 仓位管理-持仓账本 tab（聚合买入列表 + 切片明细）无 base/t 账本列；
3. 仓位管理-相关订单 tab（订单列表 + 订单详情基础信息）无 base/t 账本列。

## 1. 持仓列表表格挂载入口

- `morningglory/fqwebui/src/router/index.js`：
  - `const StockPositionList = () => import('../views/StockPositionList.vue')`
  - 新增路由 `path: '/stock-position-list'`、`name: 'stock-position-list'`、`component: StockPositionList`，用 `withRouteTitle` 包裹。
- `morningglory/fqwebui/src/router/pageMeta.mjs`：
  - `HEADER_NAV_TARGETS` 新增 `stockPositionList: { label: '持仓列表', path: '/stock-position-list', buttonType: 'default', size: 'small' }`；
  - `HEADER_NAV_GROUPS` 放入与「仓位管理/持仓复盘」同组（第二组）；
  - 路由标题映射新增 `'stock-position-list': '持仓列表'`。
- `StockPositionList.vue` 表格已含「底仓」「做T」两列（base 蓝 / t 橙），不再改动。
- 数据源 `GET /api/get_stock_position_list` 已返回 `base_quantity/base_amount/t_quantity/t_amount`。

## 2. 仓位管理-持仓账本 tab 加账本列

`morningglory/fqwebui/src/views/PositionManagement.vue`：

- 聚合买入列表（entry 表）新增列「账本」：读 `row.position_type`（`subjectManagement.mjs` 的 `buildEntryRows` 已 `...row` 透传，后端 `om_position_entries` 行已带 `position_type`）；base 显示「底仓」蓝、t 显示「做T」橙、缺失按 base。
- 切片明细表新增列「账本」：读 `row.position_type`（切片行来自 `arranger.py`，已带 `position_type`）。
- 若 `buildEntryRows` / 切片 builder 未透传 `position_type`，先在前端 builder 中显式透传（`position_type: toText(row?.position_type)`）。

## 3. 仓位管理-相关订单 tab 加账本列

### 3.1 后端订单列表补 ledger 字段

`freshquant/order_management/read_service.py` `_assemble_order_row`：

- 从 `request_row.strategy_context` 推导 `ledger`，规则（按 #549 语义）：
  - 买（side=buy）：
    - `strategy_context.buy_ledger == "base_line"` 或 `guardian_buy_grid.buy_ledger == "base_line"` → `base`（买入线底仓补仓）；
    - `guardian_buy_grid` 存在且无 base_line 标记 → `t`（Guardian 做T）；
    - 其余（手动加仓、首开等）→ `base`（手动加仓=base 决策）。
  - 卖（side=sell）：
    - `guardian_sell_sources` 存在 → `t`（Guardian TP 卖出做T仓）；
    - 全仓止损（`scope_type` 含 stoploss）→ `-`（不区分账本）；
    - 其余 → `-`。
- 返回行新增 `"ledger": <推导值>` 与 `"position_type": <推导值或 "">`；不做字段省略。
- 补充后端单测：买单 base_line → base、Guardian 做T买单 → t、TP 卖单 → t、全仓止损 → `-`。

### 3.2 前端订单列表 + 详情展示

- `morningglory/fqwebui/src/views/orderManagement.mjs` `buildOrderRows`：显式透传 `ledger: toText(row?.ledger)`（`...row` 已含则无需额外处理）。
- `PositionManagement.vue` 订单列表新增列「账本」：base「底仓」蓝 / t「做T」橙 / `-` 灰色。
- 订单详情-基础信息（el-descriptions）新增「账本」项：
  - 优先 `orderDetail.order.ledger`（若后端订单行已带）；
  - 否则前端从 `orderDetail.request.strategy_context` 按 3.1 同规则推导展示。

## 4. 验收标准

1. 顶栏出现「持仓列表」，打开 `/stock-position-list` 表格显示「底仓」「做T」两列且数值与 `/api/get_stock_position_list` 一致。
2. 仓位管理-持仓账本：入口表与切片明细每行可见「底仓/做T」标签，颜色区分，缺失按底仓。
3. 相关订单：列表与详情可见账本来源；买入线补仓显示底仓、Guardian 做T显示做T、TP 卖单显示做T、全仓止损显示 `-`。
4. 前端单测：`subjectManagementPage.test.mjs` / `position-management.test.mjs` 覆盖账本列渲染；后端 `test_order_management_read_service*` 覆盖 ledger 推导。
5. CI 全绿（docs-current-guard / pre-commit / pytest），`docs/current/**` 如有页面/接口说明变化同步更新。

## 5. 交付要求

- 走 `codex/` feature branch + PR（与 #549 主分支分离的小补丁 PR，可聚合 2-3 个文件提交）。
- 合并后重新部署 101/100/116（`morningglory/fqwebui/**` → 重建并部署 Web UI；`freshquant/order_management/**` → 重部署后端/API）。
- 部署后健康检查 + 页面人工抽查（上述验收标准 1-3）。
