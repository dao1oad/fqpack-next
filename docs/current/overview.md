# 当前总览

## 项目定位

FreshQuant 当前阶段以“当前系统事实收敛、潜在 bug 修复、部署与排障可维护”为主。正式文档只描述当前实现，不记录迁移过程。

## 当前已落地能力

- HTTP API 已统一挂载 `stock / gantt / daily-screening / order / position-management / subject-management / tpsl / runtime / system-config`
- Guardian、订单管理、仓位管理、TPSL 已形成分层交易链
- `OrderManagement / PositionManagement / SubjectManagement / TpslManagement / KlineSlim / RuntimeObservability` 已统一为 workbench 风格页面
- 订单账本已经切到 `broker order / execution fill / position entry / reconciliation` 主语义
- PositionManagement 已改为 `券商仓位 / 账本仓位 / 对账状态`
- SubjectManagement、TPSL、KlineSlim 的“单笔止损”都已切为 entry 级语义
- `stock_fills` 旧接口仍保留，但底层优先读取 entry ledger

## 当前目录职责

- `freshquant/`
  - API、CLI、订单、仓位、TPSL、运行观测与行情处理
- `morningglory/fqwebui/`
  - Web UI
- `morningglory/fqdagster/`
  - Gantt / 筛选相关读模型作业
- `runtime/memory/`
  - memory bootstrap 与 context pack
- `third_party/tradingagents-cn/`
  - 并行子系统

## 当前真值

- 代码真值
  - 最新远程 `origin/main`
- 运行真值
  - 最新远程 `main` 的正式 deploy + health check
- 文档真值
  - `docs/current/**`
- 券商仓位真值
  - `xt_positions`
- 内部持仓解释真值
  - `om_position_entries`

## 当前维护重点

- 保持 `xt_positions`、订单账本、TPSL、前端读模型的一致性
- 保持 docs、deploy、health check、cleanup 与合并结果同步
- 继续压缩 legacy `buy_lot / stock_fills_compat` 的运行期影响面
