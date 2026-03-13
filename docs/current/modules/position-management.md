# 仓位管理

## 职责

仓位管理负责把账户资产和持仓状态转换成策略可消费的“是否允许提交”门禁结论。它不是订单提交器，也不是 broker 适配层。

## 入口

- worker
  - `python -m freshquant.position_management.worker --interval 3`
- 核心服务
  - `freshquant.position_management.snapshot_service.PositionSnapshotService`
  - `freshquant.position_management.service.PositionManagementService`
  - `freshquant.position_management.dashboard_service.PositionManagementDashboardService`
- Web UI
  - `/position-management`
- HTTP API
  - `GET /api/position-management/dashboard`
  - `GET /api/position-management/config`
  - `POST /api/position-management/config`

## 依赖

- XT 资产/持仓快照
- Mongo
- Guardian / Order Submit
- Runtime Observability

## 数据流

`XT credit detail -> snapshot_service.refresh_once -> pm_credit_asset_snapshots / pm_current_state -> evaluate_strategy_order -> allow/reject`

提交门禁发生在 Order Management 接收策略单时。卖单原则上总是允许；买单要看当前状态。

## 存储

仓位管理单独使用 `freshquant_position_management`，主要集合：

- `pm_configs`
- `pm_credit_asset_snapshots`
- `pm_current_state`
- `pm_strategy_decisions`

## 配置

关键策略状态：

- `ALLOW_OPEN`
- `HOLDING_ONLY`
- `FORCE_PROFIT_REDUCE`

当前默认规则：

- 状态超过 15 秒未刷新视为 stale
- stale 默认按 `HOLDING_ONLY` 处理
- 允许开仓的最低保证金默认约 `800000`
- 仅允许持仓内操作的最低保证金默认约 `100000`

当前页面配置边界：

- 可编辑并真实生效
  - `allow_open_min_bail`
  - `holding_only_min_bail`
- 只读展示
  - `state_stale_after_seconds`
  - `default_state`
  - `xtquant.path`
  - `xtquant.account`
  - `xtquant.account_type`

阈值写入 `pm_configs.thresholds`，后续快照刷新时直接影响 `state_from_bail()` 的状态判定。
如果阈值刚更新、`pm_current_state` 还没被下一次 snapshot 刷新重算，Dashboard 会明确标记“阈值已更新，当前状态待下一次快照刷新”；在这段窗口期内，真实门禁仍按当前 `pm_current_state` 生效。
`POST /api/position-management/config` 只接受有限数值（finite number）阈值；`nan`、`inf`、`-inf` 会直接返回 400。若历史配置中出现这类脏值，Dashboard 读取时会回退到默认阈值，避免污染门禁判断。

## 页面读模型

`/api/position-management/dashboard` 当前聚合返回：

- 配置 inventory
- 当前 `raw_state` / `effective_state` / `stale`
- 最新资产摘要
- holding scope
- 当前规则矩阵
- 最近决策摘要

其中 `effective_state`、`stale` 和规则说明均由服务端按真实 `PositionPolicy` 计算。

## holding scope 口径

页面展示的 holding scope 与门禁判断保持同一口径，不直接复用旧的股票持仓列表接口。

当前口径：

- `get_stock_positions()` 投影持仓
- `xt_positions` 外部账户持仓
- 两者 union 后得到 `get_stock_holding_codes()`

## 部署/运行

- 改动后至少重启 worker：

```powershell
python -m freshquant.position_management.worker --interval 3
```

- 涉及门禁语义时，必须同时验证 Guardian 策略单与手工/API 单。

## 排障点

### 仓位状态一直不刷新

- 检查 worker 是否在跑
- 检查 XT 资产接口是否可读
- 检查 `pm_credit_asset_snapshots` 最近更新时间

### 所有买单都被拒绝

- 检查 `pm_current_state`
- 检查是否进入 stale
- 检查保证金阈值是否触发 `HOLDING_ONLY` 或 `FORCE_PROFIT_REDUCE`

### 盈利减仓语义异常

- 检查 `FORCE_PROFIT_REDUCE` 下的 `is_profitable` 元数据
- 检查 Guardian 卖单是否携带正确上下文
