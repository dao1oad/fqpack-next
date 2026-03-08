# RFC 0021: XTData 默认模式改为 guardian_1m

- **状态**：Done
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-08
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

当前 `freshquant.market_data.xtdata.market_producer` 与 `strategy_consumer` 在 `monitor.xtdata.mode` 缺省时，会回落到 `clx_15_30`。

这在并行 Docker + 宿主机 XTData 的当前运行形态下有明显问题：

- `clx_15_30` 只消费 `stock_pools`
- 但宿主机运行面更常见、也更容易持续存在的是 `xt_positions`
- 当 `stock_pools` 为空、`xt_positions` 非空时，Producer/Consumer 会在“进程看起来正常运行”的情况下没有任何预热对象，也不会向 Redis 写入 `CACHE:KLINE:*`

本仓库当前环境已验证出这一问题：`monitor.xtdata.mode` 未设置，`stock_pools=0`、`xt_positions>0`，导致 `prewarm codes=0`。

## 2. 目标（Goals）

- 当 `monitor.xtdata.mode` 未设置、为空或非法时，统一默认执行 `guardian_1m`
- 显式设置为 `guardian_1m` 或 `clx_15_30` 时，保持原有语义
- 统一收口 XTData mode 默认解析逻辑，避免多处硬编码漂移
- 更新初始化默认值与治理文档

## 3. 非目标（Non-Goals）

- 不修改 `guardian_1m` 与 `clx_15_30` 各自的监控池口径
- 不自动把数据库里已有的 `clx_15_30` 配置改写成 `guardian_1m`
- 不在本 RFC 中处理 `stock_pools / must_pool` 的生成策略
- 不调整 Redis/Mongo 连接方式

## 4. 范围（Scope）

**In Scope**

- `market_producer.py` 的 XTData mode 缺省语义
- `strategy_consumer.py` 的 XTData mode 缺省语义
- 与 Guardian 事件模式相关的 mode 读取一致性
- `preset/params.py` 初始化时对 `value.xtdata.mode` 的默认值
- 回归测试、迁移记录、破坏性变更记录

**Out of Scope**

- 新增第三种 XTData mode
- 更改 `load_monitor_codes()` 的池选择逻辑
- 自动重建 `stock_pools`

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- 统一封装 XTData mode 的标准化与默认值逻辑
- 让 Producer / Consumer / Guardian / 初始化脚本共用同一默认语义

**不负责（Must Not）**

- 不对显式配置值做重写
- 不引入新的运行服务或存储

**依赖（Depends On）**

- RFC 0003：XTData Producer/Consumer + fullcalc
- RFC 0010：宿主机 XT/XTData 运行时对齐 Docker Mongo

**禁止依赖（Must Not Depend On）**

- 不依赖前端页面状态
- 不依赖 `stock_pools` 以外的新临时集合

## 6. 对外接口（Public API）

本 RFC 不新增 HTTP/CLI 接口，只修改配置缺省语义：

- 配置键：`monitor.xtdata.mode`
- 合法值：`guardian_1m`、`clx_15_30`
- 新缺省语义：
  - 缺省 / 空字符串 / 非法值 -> `guardian_1m`
  - 显式 `guardian_1m` -> `guardian_1m`
  - 显式 `clx_15_30` -> `clx_15_30`

## 7. 数据与配置（Data / Config）

- 不新增集合或 schema
- `freshquant.params(code="monitor").value.xtdata.mode` 若缺失，运行时按 `guardian_1m` 解释
- 初始化脚本今后写入的默认值改为 `guardian_1m`

## 8. 破坏性变更（Breaking Changes）

这是一个**行为语义变更**：

- 影响面：所有未显式设置 `monitor.xtdata.mode` 的宿主机 Producer/Consumer/Guardian 运行面
- 新行为：默认从 `clx_15_30` 切换为 `guardian_1m`
- 迁移步骤：
  1. 若希望保持旧行为，显式设置 `monitor.xtdata.mode=clx_15_30`
  2. 重启宿主机 `xtdata producer / consumer`
- 回滚：
  - 回退本 RFC 涉及的默认值与 helper 收口改动

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- 旧分支宿主机运行习惯更偏向“持仓即监控”，映射到目标仓的 `guardian_1m`
- 目标仓中的 `market_producer.py` / `strategy_consumer.py` 缺省行为从“池驱动”改为“持仓优先”

## 10. 测试与验收（Acceptance Criteria）

- [x] 缺省 `monitor.xtdata.mode` 时，标准化结果为 `guardian_1m`
- [x] 显式 `clx_15_30` 时，标准化结果仍为 `clx_15_30`
- [x] `preset/params.py` 在 mode 缺失时写入 `guardian_1m`
- [x] Producer / Consumer 运行时代码不再硬编码 `clx_15_30` 作为缺省值

## 11. 风险与回滚（Risks / Rollback）

- 风险：未配置 mode 的老环境会切到 `guardian_1m`，监控池范围变化
- 缓解：保留显式 `clx_15_30` 兼容路径，并在 breaking changes 中明确迁移步骤
- 回滚：恢复旧默认值为 `clx_15_30`

## 12. 里程碑与拆分（Milestones）

- M1：RFC 审批通过
- M2：统一 helper + 回归测试落地
- M3：运行文档与迁移记录同步完成
