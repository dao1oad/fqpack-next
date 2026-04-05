# 对账中心

## 职责

`/reconciliation` 是当前统一排障入口，负责把 symbol 级一致性审计、相关订单、Entry / Slice 与 gap / resolution / rejection 收口到同一页。

当前页面职责固定为：

- 上半屏：`symbol` 对账主表，用于发现异常
- 下半屏：排障工作区，用于解释异常
- `相关订单` tab：吸收原 `/order-management` 的正式查单与详情能力

`/reconciliation` 只读，不负责 repair、rebuild、reconcile 或任何写操作。

## 路由

- Web UI
  - `/reconciliation`

支持当前 URL contract：

- `/reconciliation?symbol=600000`
- `/reconciliation?symbol=600000&tab=orders`
- `/reconciliation?symbol=600000&tab=orders&order=<id>`
- `/reconciliation?symbol=600000&tab=ledger&entry=<id>`

## 读接口

- `GET /api/position-management/reconciliation`
  - 返回 symbol 对账总览
- `GET /api/position-management/reconciliation/<symbol>`
  - 返回 symbol 级规则与 evidence detail
- `GET /api/position-management/reconciliation-workspace/<symbol>`
  - 返回 `detail / gaps / resolutions / rejections`
  - 若当前运行中的后端尚未部署该接口，前端会回退到 `GET /api/tpsl/management/<symbol>` 的基础 detail，并在 `Resolution` tab 明确提示“workspace 接口未部署”；此时 `gap / resolution / rejection` 为空
- `GET /api/order-management/orders`
  - `相关订单` tab 的主列表
- `GET /api/order-management/orders/<internal_order_id>`
  - 订单详情
- `GET /api/order-management/stats`
  - 订单摘要
- `GET /api/tpsl/management/<symbol>`
  - Entry / Slice / TPSL 历史基础 detail

## 页面结构

当前页面固定 4 个 tab：

- `概览`
- `相关订单`
- `持仓账本`
- `Resolution`

其中：

- `概览` 展示 `R1 ~ R4` 与 surface 对照
- `相关订单` 展示 request / order / event / trade 主线
- `持仓账本` 左侧展示 open `om_position_entries`，右侧上下联动展示当前 entry 的 open `om_entry_slices` 与 Entry detail
- `Resolution` 展示 `om_reconciliation_gaps / om_reconciliation_resolutions / om_ingest_rejections`

## 页面语义

- 选择 `symbol` 后，工作区默认保留当前 tab
- 通过 lookup 可直接按 `symbol / internal_order_id / request_id / broker_order_id` 定位
- 从 `/position-management` 进入时，当前选中 symbol 会通过 `?symbol=` 透传
- 旧 `/order-management` 正式入口已删除；订单排障必须从本页进入
- `Resolution` tab 需要 `reconciliation-workspace` 接口；若接口 `404`，页面仍可打开，但只显示 TPSL 历史，不显示 `gap / resolution / rejection` 明细
