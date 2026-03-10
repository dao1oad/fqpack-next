# RFC 0030: XTQuant Observe-Only Broker 模式

- **状态**：Approved
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-11
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

当前目标仓已经具备完整订单链路：

- `Guardian / API / CLI` 调用 `OrderSubmitService`
- 订单进入主账本与 Redis 队列
- `fqxtrade.xtquant.broker` 向券商执行 `buy / sell / cancel`
- XT 回报进入 `xt_report_ingest / order_reconcile`

但运行面缺少一种安全演练模式：

- 需要让完整交易链持续运行，便于在 `/runtime-observability` 观察 `Guardian -> Position -> OrderSubmit -> Broker`
- 需要确保最终不会与券商发生任何交互
- 不能通过伪造成交来污染真实持仓、真实仓位、真实 TPSL 事实

当前宿主机也尚未按完整交易链模式托管 Supervisor 进程，只有 `xtdata producer / consumer / broker / credit_subjects.worker / adj_refresh_worker` 在运行，导致即便修复了运行观测目录，也无法稳定看到完整策略链。

## 2. 目标（Goals）

- 在 `freshquant.params(code="xtquant").value` 下新增 `broker_submit_mode`
- 支持 `normal` 与 `observe_only` 两种 broker 执行模式
- 在 `observe_only` 下让 `buy / sell / cancel` 全部止步于 broker，不与券商交互
- 为被拦截的订单提供显式状态 `BROKER_BYPASSED`
- 将宿主机 Supervisor 切换到完整交易链模式

## 3. 非目标（Non-Goals）

- 不生成 synthetic 委托、synthetic 成交或 synthetic XT 回报
- 不新增模拟持仓、模拟仓位、模拟对账读模型
- 不新增独立的 `order_management.worker`
- 不改变未配置该参数时的真实提交行为
- 不在本 RFC 中重构前端页面或订单查询 API 的整体形态

## 4. 范围（Scope）

**In Scope**

- `freshquant.params(code="xtquant").value.broker_submit_mode` 配置语义
- `fqxtrade.xtquant.broker` 的 `normal / observe_only` 分支
- 订单状态机新增 `BROKER_BYPASSED`
- 运行观测中 `broker_gateway.execution_bypassed`
- 宿主机 Supervisor 完整交易链进程清单
- 相关回归测试、文档、迁移进度

**Out of Scope**

- 真实 XT 回报 ingest/reconcile 语义重写
- 模拟成交与模拟回报系统
- 新增订单对外 HTTP API
- 替换 `credit_subjects.worker`

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- 明确定义 broker 演练模式的配置位置、默认值与运行语义
- 确保 `observe_only` 下 `buy / sell / cancel` 全部不与券商交互
- 用显式状态与运行观测表达“已跑到 broker，但被拦截”
- 明确完整交易链所需的宿主机 Supervisor 进程

**不负责（Must Not）**

- 不假装订单已真实提交
- 不通过伪造回报推进真实仓位事实
- 不新增独立订单管理守护进程

**依赖（Depends On）**

- RFC 0007：股票/ETF 系统化订单管理与逐买入跟踪
- RFC 0013：融资账户仓位管理模块
- RFC 0014：股票/ETF 独立止盈止损模块
- RFC 0021：XTData 缺省模式改为 `guardian_1m`
- RFC 0026：运行观测与日志可视化

**禁止依赖（Must Not Depend On）**

- 不依赖 synthetic XT 回报
- 不依赖新增模拟库或新增消息系统
- 不依赖前端临时逻辑绕过真实状态机

## 6. 对外接口（Public API）

本 RFC 不新增新的 HTTP 路由或 CLI 命令，变更点为配置与状态语义。

配置键：

- `freshquant.params(code="xtquant").value.broker_submit_mode`

合法值：

- `normal`
- `observe_only`

兼容性策略：

- 缺失 / 空值 / 非法值：按 `normal`
- 显式 `normal`：保持当前真实提交行为
- 显式 `observe_only`：broker 不与券商交互

新增内部稳定状态语义：

- 订单状态：`BROKER_BYPASSED`
- 订单事件：`broker_submit_bypassed`
- 订单事件：`broker_cancel_bypassed`

运行观测新增节点语义：

- `broker_gateway.execution_bypassed`

## 7. 数据与配置（Data / Config）

Mongo 文档位置：

- 集合：`freshquant.params`
- 文档 `_id`：`69ab8178dc99511db870d74e`
- `code`：`xtquant`
- 新字段：`value.broker_submit_mode`

示例：

```json
{
  "_id": "69ab8178dc99511db870d74e",
  "code": "xtquant",
  "value": {
    "account": "068000076370",
    "path": "D:\\迅投极速策略交易系统交易终端 东海证券QMT实盘\\userdata_mini",
    "account_type": "CREDIT",
    "total_position": 7000000,
    "broker_submit_mode": "observe_only"
  }
}
```

运行面配置要求：

- `freshquant.params(code="monitor").value.xtdata.mode = guardian_1m`
- 宿主机 Supervisor 需新增：
  - `freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event`
  - `freshquant.position_management.worker`
  - `freshquant.tpsl.tick_listener`

为满足“observe_only 下完全不跟券商交互”，`broker_submit_mode` 以 broker 启动时解析为准；参数变更后需要重启 `fqnext_xtquant_broker`。

## 8. 破坏性变更（Breaking Changes）

这是一次可选配置驱动的行为语义变更：

- 影响面：
  - `fqxtrade.xtquant.broker`
  - 订单状态机
  - 宿主机 Supervisor 运行面
- 新行为：
  - 当 `broker_submit_mode=observe_only` 时，`buy / sell / cancel` 不再与券商交互
  - 订单状态不再推进到 `SUBMITTED`，而是进入 `BROKER_BYPASSED`
- 迁移步骤：
  1. 在 `freshquant.params(code="xtquant").value` 增加 `broker_submit_mode`
  2. 将 `freshquant.params(code="monitor").value.xtdata.mode` 设为 `guardian_1m`
  3. 在宿主机 Supervisor 增加 `guardian / position_management / tpsl` 常驻进程
  4. 重启 `fqnext_xtquant_broker`
- 回滚方案：
  - 删除 `broker_submit_mode` 或改回 `normal`
  - 重启 `fqnext_xtquant_broker`
  - 若已落地状态机扩展但需要回滚实现，可撤回 `BROKER_BYPASSED` 路径对应代码

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- `D:\fqpack\freshquant\freshquant\strategy\toolkit\order_manager.py`
  - 旧仓订单提交语义 -> 目标仓 `freshquant.order_management.submit.*`
- `D:\fqpack\freshquant\freshquant\strategy\toolkit\order_tracking_service.py`
  - 旧仓订单跟踪 -> 目标仓 `freshquant.order_management.tracking.*`
- `D:\fqpack\freshquant\freshquant\signal\astock\job\monitor_stock_zh_a_min.py`
  - 旧仓 Guardian 常驻入口 -> 目标仓宿主机 Supervisor `guardian --mode event`
- `D:\fqpack\freshquant\freshquant\strategy\toolkit\fill_stoploss_helper.py`
  - 旧仓止盈止损衔接 -> 目标仓 `freshquant.tpsl.*`
- `D:\fqpack\freshquant\morningglory\fqxtrade\fqxtrade\xtquant\broker.py`
  - 旧仓真实券商执行入口 -> 目标仓同名 broker 增加 `observe_only` 分支

## 10. 测试与验收（Acceptance Criteria）

- [ ] 缺失 `broker_submit_mode` 时，broker 仍按当前方式真实提交
- [ ] `broker_submit_mode=observe_only` 时，`buy / sell / cancel` 不调用任何券商接口
- [ ] `observe_only` 下订单状态推进到 `BROKER_BYPASSED`
- [ ] `observe_only` 下运行观测出现 `broker_gateway.execution_bypassed`
- [ ] `observe_only` 下不产生对应订单的 XT 回报 ingest/reconcile 推进
- [ ] 宿主机完整交易链模式包含 `guardian / position_management / tpsl`，且不新增独立 `order_management.worker`

## 11. 风险与回滚（Risks / Rollback）

- 风险：下游若把 `BROKER_BYPASSED` 误当成失败或已提交，查询与展示会出现错误认知
- 缓解：同步扩展状态机、测试与文档，显式区分 `BROKER_BYPASSED` 与 `SUBMITTED`
- 风险：只改 Mongo 参数但未重启 broker，会保留旧执行模式
- 缓解：在实施计划和运维文档中明确“改参后重启 broker”
- 回滚：删除参数或改回 `normal`，并重启 broker

## 12. 里程碑与拆分（Milestones）

- M1：RFC 与设计稿进入 Review，确认参数、状态与运行边界
- M2：实现配置解析、状态机扩展、broker observe_only 分支与回归测试
- M3：切换宿主机 Supervisor 到完整交易链模式，并完成联机验收
