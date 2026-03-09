# RFC 0025: 运行观测与日志可视化

- **状态**：Approved
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-09
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

旧分支 `D:\fqpack\freshquant` 已经存在“结构化 JSONL 落盘 + 本机 HTTP 读取 + Web UI 可视化”的日志链路，但目标仓 `D:\fqpack\freshquant-2026.2.23` 目前没有对应的统一模块、后端接口和页面入口。

与此同时，目标仓的实盘运行链路已经重构为：

- `XTData Producer/Consumer`
- `Guardian` 策略
- `TPSL`
- `Position Management`
- `Order Management`
- `Broker/Puppet` 执行网关

旧仓中 `Guardian` 一体化策略日志语义已经无法准确映射当前目标仓架构，直接照搬会把订单域、仓位域和执行域重新混回策略层。

此外，本项目是实盘系统，日志系统必须满足最高优先级约束：**绝不阻塞主进程，尤其绝不阻塞下单链路**。

## 2. 目标（Goals）

- 为 FreshQuant 实盘核心链路提供统一结构化事件模型。
- 优先支持链路追踪（trace），可定位一笔策略/订单卡在哪个节点。
- 同步提供健康看板，观察 Producer/Consumer、仓位管理、订单桥接、下单网关的运行状态。
- 保留 raw JSONL tail 作为底层排障入口。
- 首期支持本机单节点，并兼容 Docker/宿主机混合运行。
- 所有观测能力必须旁路、异步、可丢弃，不影响交易执行。

## 3. 非目标（Non-Goals）

- 多机器 cluster 聚合
- TradingAgents-CN、Dagster、Huey 的全量接入
- Mongo 事件库存储
- 复杂拓扑动画或历史报表
- 让日志系统参与业务控制流或业务决策

## 4. 范围（Scope）

**In Scope**
- 新增 `freshquant/runtime_observability/` 模块
- 新增 `/api/runtime/*` 只读接口
- 新增 Web UI 运行观测页面
- 接入核心链路：
  - `XTData Producer/Consumer`
  - `Guardian`
  - `TPSL`
  - `Position Management`
  - `Order Management`
  - `Broker/Puppet`
- 统一 `trace_id / intent_id / request_id / internal_order_id` 关联语义

**Out of Scope**
- 多机节点代理
- 非核心链路的广覆盖埋点
- 日志事件持久化到 Mongo
- 与 TradingAgents-CN 的统一观测平台整合

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**
- 统一事件 schema
- 非阻塞异步 JSONL 落盘
- 后端 trace 聚合与健康摘要
- 前端 trace/health/raw records 展示
- 宿主机与 Docker 混合运行下的 `runtime_node` 标识

**不负责（Must Not）**
- 业务控制
- 实盘下单重试/补偿
- 消息总线抽象替换
- 实时告警平台集成

**依赖（Depends On）**
- 现有 Flask `api_server`
- 现有 Vue `fqwebui`
- 现有订单域、仓位域、TPSL、XTData、Broker/Puppet
- 文件系统 JSONL 落盘能力

**禁止依赖（Must Not Depend On）**
- 交易关键路径上的同步 Mongo 写入
- 交易关键路径上的同步 HTTP 调用
- 任何会反压业务线程的观测外部服务

## 6. 对外接口（Public API）

新增后端只读接口：

- `GET /api/runtime/components`
- `GET /api/runtime/health/summary`
- `GET /api/runtime/traces`
- `GET /api/runtime/traces/<trace_id>`
- `GET /api/runtime/events`
- `GET /api/runtime/raw-files/*`

新增前端页面：

- 运行观测页（健康看板 + trace 列表 + trace 详情 + raw records）

错误语义：

- 所有接口为只读接口
- 参数非法返回 `400`
- 文件不存在返回 `404`
- 聚合异常返回 `500`
- 不因单条日志解析失败导致整个接口失败，错误应在结果中局部暴露

兼容性策略：

- 首期保留 raw JSONL tail 访问能力
- 不复用旧仓 `SystemLogs.vue` 的聚合逻辑作为主实现

## 7. 数据与配置（Data / Config）

配置来源：

- Dynaconf / 环境变量
- 首期允许新增运行观测相关环境变量，例如：
  - 日志根目录
  - `runtime_node`
  - 队列大小
  - 是否启用

数据存储：

- JSONL 文件

建议目录布局：

- `<root>/<runtime_node>/<component>/<YYYY-MM-DD>/<component>_<YYYY-MM-DD>_<pid>.jsonl`

核心字段：

- `ts`
- `runtime_node`
- `component`
- `node`
- `event_type`
- `status`
- `message`
- `reason_code`
- `trace_id`
- `intent_id`
- `request_id`
- `internal_order_id`
- `symbol`
- `action`
- `strategy_name`
- `source`
- `decision_branch`
- `decision_expr`
- `payload`
- `metrics`

## 8. 破坏性变更（Breaking Changes）

首期预期无强制破坏性 API 替换，但存在以下重要语义调整：

- 新系统不再把 `Guardian` 当作完整交易链容器
- trace 聚合从前端迁移到后端
- 运行观测主入口从旧的“按组件 tail”思路转为“按 trace + 健康摘要”

影响面：

- 后续若有依赖旧仓 `SystemLogs` 聚合逻辑的迁移脚本，需要按新 `/api/runtime/*` 调整

迁移步骤：

1. 部署运行观测模块
2. 打开新页面与接口
3. 保留 raw tail 作为兼容排障入口

回滚方案：

- 下线新 `/api/runtime/*` 蓝图与新页面
- 保留业务运行逻辑不变

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- `freshquant/logging/structured_logger.py` → `freshquant/runtime_observability/logger.py`
- `freshquant/logging/guardian_signal_logger.py` → `guardian_strategy` 节点化事件模型
- `freshquant/logging/bar_monitor_structlog.py` → `heartbeat/metric_snapshot` 模型
- `freshquant/rear/system_logs/routes.py` → `freshquant/rear/runtime/routes.py` 的 raw records 子能力
- `morningglory/fqwebui/src/views/SystemLogs.vue` → 新运行观测页面（仅保留 raw tail 思路，不复用其前端聚合核心）

## 10. 测试与验收（Acceptance Criteria）

- [ ] 单元测试覆盖 schema、IDs、runtime logger、assembler、health 聚合
- [ ] 后端接口测试覆盖 `/api/runtime/*`
- [ ] 至少一条 Guardian 买单 trace 能跨组件展示：
  - `guardian -> position_gate -> order_submit -> broker -> puppet`
- [ ] 至少一条 Guardian 卖单 trace 能展示盈利切片/减仓分支
- [ ] 至少一条 TPSL trace 能并入同一执行链
- [ ] 健康看板能显示 Producer/Consumer 关键指标
- [ ] 单机环境能区分 `host:*` 与 `docker:*`
- [ ] 日志系统在队列满、写文件失败时不会阻塞业务线程

## 11. 风险与回滚（Risks / Rollback）

- 风险点：当前链路缺少统一 ID 传播
- 缓解：从 `trace_id -> intent_id -> request_id -> internal_order_id` 分层补齐

- 风险点：业务代码分散，接入点多
- 缓解：统一通过 `runtime_observability` 公共包接入

- 风险点：日志写入影响实盘线程
- 缓解：强制使用有界队列、后台线程、可丢弃策略、吞异常策略

- 回滚：关闭新接口与页面，移除业务埋点，业务链路本身不依赖运行观测模块

## 12. 里程碑与拆分（Milestones）

- M1：RFC 通过
- M2：公共 logger + schema + 后端聚合接口
- M3：接入 Guardian / Producer / Consumer / OrderSubmit / Broker
- M4：接入 TPSL / Position / Puppet / XT 回报 / 对账
- M5：Web UI 完成与治理文档更新
