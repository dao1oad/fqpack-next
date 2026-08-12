# 订单账本身份与聚合技术债：系统性修复方案（Codex × Devin 共识版）

> 状态：Codex 与 Devin Ultra 单轮评审后达成一致（2026-08-12）。
> 性质：实施计划文档，非 `docs/current/**` 正式事实；落地时以 GitHub Issue + PR + CI 为交付真值。
> 原则：系统性收口，杜绝单点修复；复用现有架构模式（`LedgerResolver` 管账本归属、`OrderStateService` 管订单状态），不过度设计、不引入新框架。

## 1. 背景（两次实盘事故）

### 事故 A：2026-08-04 跨标的身份错配（GitHub Issue #504）

- 账户 `068000087558` 实盘买入 `688772` 10,000 股 @14.70（XT `broker_order_id=1209008130`，2026-08-04 10:01:30 整单成交）。
- 系统把该成交错配到 `600917` 名下，两标的持仓被聚合成一个 entry：**48,700 股 @ 7.118932**，
  精确等于 `(38,700×5.16 + 10,000×14.70) / 48,700`（600917 的 38,700@5.16 + 688772 的 10,000@14.70 加权）。
- 2026-08-05 发现并修复：#504 隔离 broker identity；#509 引入 canonical identity
  （主键 `account_id + trading_day + order_sysid`，fallback `account_id + trading_day + symbol + side + broker_order_id`，
  同时满足才匹配，否则 fail-closed）；#510 提供 688772 ledger repair 工具；08-09 flatten 全账本重建。
- 教训：修复只覆盖了 matcher/归属主链，未清点全部旧写法使用点，留下读侧与写侧残留。

### 事故 B：2026-08-11 同单成员覆盖（本次 600104 做T）

- 同一账户 600104 做T加仓买入 7,400 股 @10.30，XT 拆 **16 笔成交**（部署 SHA=99cb7b787）。
- 每笔 fill `created=True` → `_upsert_broker_position_entry` 用 `internal_order_id` 当 `broker_order_key`
  调 `find_broker_order`（生产里 key 已被 order report 迁移为 canonical `account:...:day:...:sysid:...`）→ 恒查不到
  → 静默回退到单笔 fill 数量 → `build_clustered_position_entry` 同 key 幂等覆盖 → entry 最终只等于
  **最后一笔 300 股**。
- 14:45:20 reconcile 检出 gap 7,100（券商 102,100 vs 账本 94,700+300），14:45:50 auto_open_entry 自愈合并为 7,400。
- 最终数据正确（entry/slices/gap/resolution 全部一致），但**依赖对账自愈且自愈无告警**，期间约 45 秒 entry 数量错误。

## 2. 代码现状盘点（已核实，带证据）

| # | 技术债 | 位置（文件:行） | 说明 |
| --- | --- | --- | --- |
| 1 | 写侧身份误用：`find_broker_order(internal_order_id)` 恒落空 + 静默回退单笔数量 | `order_management/ingest/xt_reports.py:1217-1236` | 事故 B 直接根因；当前 main 仍存在 |
| 2 | 读侧身份误用：先按 internal 直查（恒落空）再 O(n) 全表扫描兜底 | `order_management/read_service.py:388-400` | 8-05 加固残留；`om_broker_orders` 无 `internal_order_id` 索引（仅 `broker_order_key` 唯一索引） |
| 3 | 维护脚本直写 `om_*`，绕过 repository 幂等/冲突检查与 runtime 观测 | `script/maintenance/backfill_ledger_intent.py`（6 集合）、`order_management/repair/guardian_sell_allocation.py` | 2026-08-11 18:05:44 “幽灵写入”（仅刷新 `updated_at`，无任何 runtime 事件）即此类直写 |
| 4 | 自愈无告警：auto_open_entry 静默补账 | `order_management/reconcile/service.py` `_confirm_open_gap` | 对比 `_confirm_close_gap` 已有 `status=warning reason_code=tpsl_takeprofit_return_lost` 先例 |
| 5 | 测试失真：真实 Mongo 身份用例默认 skip；单测未模拟“order report 先到→key 迁移”生产时序 | `tests/test_external_order_identity_real_mongo.py:26-28`、`tests/test_order_management_xt_ingest.py` | `FQ_FIX_504_REAL_MONGO=1` 才跑；entry 级多 fill 用例缺失 |
| 6 | 时间/展示语义混用：订单列表默认 `updated_at`（台账更新时间），与持仓页 `trade_time`（业务时间）口径不一致 | `morningglory/fqwebui/src/views/OrderManagement.vue:180-182` | 事故 B 中 18:05:44 vs 14:45:05 即此问题 |
| 7 | 时间格式不统一 | `om_orders.submitted_at` 带 `+00:00`；`om_broker_orders.submitted_at` naive | P2，随改动顺带 |
| 8 | 证据链缺口 | resolution 成员 `trade_fact_id=null`（7100 股只有 resolution 证据） | P2，审计回放依赖 gap/resolution 关联 |

## 3. 共识方案（PR 划分）

总原则：**entry 只由 broker order 聚合（canonical key + filled_quantity/avg_filled_price）驱动生成/更新；
单笔 fill 只作为证据，不决定数量；找不到聚合时 fail-closed**。写路径、身份、可观测性三件事收口。

### PR1（P0，核心修复）

- `_upsert_broker_position_entry`：broker order 查找改为 `trade_fact.broker_order_key`（canonical，已在 trade_fact 上）优先、
  `internal_order_id` 兜底（兼容 broker-only 单）；两者都查不到 → **fail-closed 进 `om_ingest_rejections`**，
  删除 `or trade_fact.get("quantity")` 静默回退。
- **成员键兼容（防双计数，Devin 识别 P0）**：`find_entry_for_broker_order` 增加 internal↔canonical 解析匹配
  （经 `om_broker_orders.internal_order_id` 反查），覆盖存量 entry（如 600104 T entry 成员键现为 `ord_35a90...`）；
  可选一次性回填脚本（默认 `--dry-run`）。
- 生产形状用例：order report 先到→key 迁移→16 笔 fill→entry=整单 7,400、成员=1；broker-only 买单路径；
  找不到 broker order 时 fail-closed。
- 验收：116 复跑 600104 场景无新 gap、无自愈；pytest 全绿。

### PR2（P0，让自愈可见）

- `_confirm_open_gap`（auto_open_entry）补 `status=warning` + `reason_code=auto_open_entry` runtime 事件
  （复用 `_confirm_close_gap` 的告警模式）。
- 验收：构造 gap→确认后 ClickHouse/ops-console 出现 warning 事件。

### PR3（P1，读侧收口）

- repository 新增 `find_broker_order_by_internal_order_id()`（补 `om_broker_orders.internal_order_id` partial 索引）。
- `read_service._find_broker_order` 改走新 API，**删除全表扫描兜底**（保留 `find_order` 最终兜底）。
- 验收：`explain` 无 COLLSCAN；`/api/order-management/orders/<internal_order_id>` 回归通过。

### PR4（P1，守恒守门）

- 新增只读不变量模块：`entry == Σ成员证据`、`Σslice == entry`、`券商持仓 == 账本持仓（无 OPEN gap）`。
- 挂载点（成本最低）：CI 单测 + 运行时 reconcile 收尾 + ops-console 探针（复用现有 `/api/ops/*`）。
- 验收：构造漂移用例红→绿；116 探针一致。

### PR5（P1，写路径审计）

- 维护脚本（backfill/repair 等）默认 `--dry-run`；写前审计（操作/集合/影响条数/前后关键字段）；
  **内容无变化的写不再刷新 `updated_at`**（消灭幽灵写入）。
- 不做“一次性脚本服务化改造”（过度设计），只约束审计与 updated_at 语义。

### PR6（P2，展示契约）

- 订单列表默认展示 `submitted_at`（业务时间），`updated_at` 降为次级列并标注“台账更新时间”。
- 统一时间存储 ISO+tz；resolution 成员证据链补全（trade_fact_id 回填）随改动顺带。

## 4. 明确不做（防过度设计）

- 不引入 event sourcing / CQRS / 新数据库 / 新消息队列。
- 不做 entry 历史版本化（现有 `trade_facts + resolutions` 证据链已够）。
- 不改单账户部署边界（docs 已声明）。
- 不重构一次性维护脚本为领域服务。
- 不改 `members_by_key` 同 key 覆盖为“证据列表合并”（Devin 已证明：成员数量=整单，
  累加会与 `filled_quantity` 双计数；覆盖是幂等整单快照的正确语义）。

## 5. 分歧点与最终立场（Codex × Devin）

1. 覆盖语义：接受 Devin，P0 只改 key + fail-closed，不改成员合并。
2. 写侧 API：接受 Devin，不用 `find_broker_order_by_broker_order_id`（`broker_order_id` 跨日复用 + 无索引），
   用 trade_fact 自带 canonical key。
3. S3 范围：接受 Devin，脚本加审计而非服务化改造。
4. HEAD/流程事实：确认本地 main 领先远程 4 个提交（HEAD=`7ead5d3b`，含“本机部署，不推送远程”合并；
   origin/main=`448fb27b`），order_management 树与 6104a20a 无差异。**流程违规，PR 系列开始前需处理**
   （合法变更走 PR 同步远程或登记豁免），避免 CI gate 基于错误基线。
5. 成员键迁移：双方一致为 P0，纳入 PR1（兼容匹配为主、回填可选）。

## 6. 落地顺序与验收口径

`PR1(P0) → PR2(P0) → PR3(P1) → PR4(P1) → PR5(P1) → PR6(P2)`；
每 PR 独立可部署、可回滚；PR 内同步更新 `docs/current/**`（架构文档补充“entry 聚合单一权威”与身份契约段落）。
高影响 P0 先建 GitHub Issue（影响面/验收/部署影响），再走 `feature branch → PR → CI → merge → 部署 → 健康检查 → cleanup`。

## 7. 数据现状与巡检

- 当前 116 生产数据无需紧急修数：600104 entry（7,400）/slices（4,800@10.30 + 2,600@10.61）/gap（AUTO_OPENED）/resolution 全部一致。
- 存量巡检脚本：扫描所有 `buy_cluster` entry 成员与对应 broker order `filled_quantity` 一致性（当前仅 600104 一单受影响，已自愈）。
