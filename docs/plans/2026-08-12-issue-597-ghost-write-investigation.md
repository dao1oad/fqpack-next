# Issue #597 调查结论：2026-08-11 18:05 幽灵写入（om_broker_orders）

> 状态：调查完成，结论与修复方案已与 Devin 评审对齐。
> 关联：#597（追踪 18:05 幽灵写入）、#588（token 回退加固）、#583（写前审计）。

## 1. 调查结论（证据链）

### 1.1 三机同一时刻 touch 同标的订单（6 秒窗口）

2026-08-11 晚，三台机器各自刷新了**一条 600104 订单**的
`om_broker_orders.updated_at`（均为 UTC ISO，=北京 18:05 前后）：

| 机器 | 账户 | 订单 | source_type | token 状态 | updated_at |
| --- | --- | --- | --- | --- | --- |
| 116 | 068000087558 | sysid:1615（7400 股/16 笔） | strategy | 完好 | 10:05:44.530126Z |
| 100 | 068000076370 | sysid:1703（6800 股/1 笔） | strategy | 完好 | 10:05:49.094808Z |
| 101 | 068000076370 | sysid:1703（6800 股/1 笔） | **broker_only** | **null**（本应如此） | 10:05:50.953571Z |

三笔写入**都只刷新了 updated_at**：

- `om_orders.updated_at` 未动（116 仍定格在 06:45:07Z）；
- `om_order_events` 无新增（16 笔成交事件全部定格在 06:45:06-07Z）；
- `om_trade_facts` / `om_execution_fills` 无新增（fill_count=16、aggregate_revision=16 未变）；
- 其他 OM 集合（stoploss/exit_allocations/takeprofit/events）18:04-18:07Z 窗口内**零活动**；
- 116 备份库 `fqom_bak_20260811_issue571_116_v2/_final`（18:05:44 之后创建）与当前 LIVE
  文档**除 updated_at 外逐字段一致**——即 18:05:44 的写入**没有留下任何业务字段变化**。

### 1.2 写入者不在代码仓库的任何写路径内

能刷新 `om_broker_orders.updated_at` 的 repository 路径仅两个：

1. `update_broker_order_fields`（调用方 `_sync_broker_order_report`，L630）：
   有守卫 `if not update_fields: return`——业务字段全等时**不会只写 updated_at**；
2. `compare_and_set_broker_order`（调用方 `_apply_fill_to_broker_order`，L679）：
   只在**新 execution_fill** 时调用，且会 `aggregate_revision+1`（当前=16 未变，排除）。

`claim_broker_order_owner` / `fence_broker_order_execution` / `move_broker_order_key`
均不刷新 updated_at。

因此 18:05:44/49/50 的写入是**绕过 repository 的直写**（`$set: {updated_at}` 类），
执行者可能是历史维护脚本或人工直连 Mongo，当时无审计、无法追溯：

- Mongo 为**单机模式**（`local` 库仅 `startup_log`，无 `oplog.rs`）；
- profiling 关闭（`was: 0`）；
- 08-11 18:05-18:50 之间无部署（116 reflog：最近 14:14、下次 20:46）；
- 101 PowerShell 历史无相关命令；Codex 会话 18:04-18:07 在跑 CLX 测试（无关）。

### 1.3 101 "token 被置 null" 是误判

101 的订单是 **broker_only**（开发机连券商账户 068000076370，XT 回报无内部归属）：

- `_build_broker_only_order` 不写 token；
- `_broker_order_owner_claim` 对 broker_only **强制 token=None**；
- 佐证：101 上 08-12 09:32 创建的 300760 broker_only 订单（sysid:230）token 同样为
  null，从未被"修复"。

**结论：101 的 om_broker_orders token 从创建起就是 null，不是 18:05:50 被抹掉的。**
而 om_orders 里的 token（FQOM8e56206a3555853e6f00）是 `_non_empty_identity_fields`
从 XT `order_remark` 提取后写入的（指向 100 上的真实订单 ord_8c3e44...）。

**用户"修复"（fix_token.py）把 token 写入 broker_only 文档，反而制造了新问题**：
当前 101 文档处于 `broker_only + token` 的非法态，`_classify_broker_order_owner`
会直接抛 `BrokerIdentityConflict("broker-only owner cannot carry request or
correlation ownership")`，后续任何 claim 都会失败。

### 1.4 已确认的真实技术债（潜在 bug）

**债 A：终态订单无幂等短路（幽灵 touch 的直接代码路径）**

`ingest_order_report_with_meta` / `ingest_trade_report_with_meta` /
`_sync_broker_order_report` 对 FILLED/CANCELED 终态订单的**重复/迟到回报没有短路**。
已用最小复现证明（`.scratch/repro_597_ghost_write.py`）：

```text
before updated_at: 2026-08-11T06:45:07.619518+00:00
after  updated_at: <now>（被刷新）
changed: True
```

任何 XT 重连重放、日终补发、对账补 ingest，都会让终态订单的
`om_broker_orders.updated_at` 被无痕刷新，甚至误写字段
（如 `submitted_at` 时区格式不同触发"同一时刻不同字符串"的伪差异）。

**债 B：broker_only 订单 token 归属语义不闭环**

- `_non_empty_identity_fields`（L789）从 XT `order_remark` 提取 token 写入
  `om_orders`（即使 broker_only 订单，token 可能指向真实订单）；
- `_broker_order_owner_claim`（L812）对 broker_only **强制 token=None** 写入
  `om_broker_orders`；
- 结果：同一订单两集合 token 永久不一致，且手动"修复"会进入非法态且不可逆
  （claim 抛异常），只能 targeted repair。

**债 C：OM 写路径无审计 + Mongo 无追溯能力**

- repository 写路径（claim/update/CAS/fence/move）无写前审计；
- Mongo 单机无 oplog、profiling 关闭；
- 任何直写（维护脚本/人工）都无法追溯执行者与命令——本次 18:05 写入即为此类。

**债 D（放大器）：时间格式混用**

- `om_broker_orders.submitted_at` = 北京无时区 `2026-08-11T14:45:05`；
- `om_orders.submitted_at` = UTC ISO `2026-08-11T06:45:05.125049+00:00`；
- 同一时刻两种字符串，`_sync_broker_order_report` 字符串比较产生伪差异 →
  放大债 A 的无意义写入。

## 2. 修复方案（系统级，非单点；已与 Devin 评审对齐）

> Devin 评审结论（2026-08-12，只读）：
> - PR-1 需修改：主修应为 submitted_at 归一化；"终态短路"是修现象的冗余，且会危及
>   迟到成交 touch（#571）。
> - PR-2 部分同意：不透传 token 给 broker_only claim（`_classify_broker_order_owner`
>   L1073 已是真值点）；核心交付为 101 数据 $unset 修复脚本 + 回归测试。
> - PR-3 同意：5 个收口方法共用 audit helper、仅真写库才审计、复用 #583 schema；
>   并**新发现漏洞**：`update_broker_order_fields` 把 caller 传入的 updated_at 当
>   普通字段参与 diff，可产生 updated_at-only 合法写（18:05:44 的代码形态）。
> - 顺序：PR-1 ∥ PR-3（文件不重叠）→ PR-2（修复脚本在审计就位后执行）。

### PR-1：submitted_at 时间格式归一（消除终态伪差异）

- `_sync_broker_order_report` 构造 updates 处 + 写入层，submitted_at 统一归一为
  UTC ISO（与 om_orders 同格式），消除"同一时刻不同字符串"的伪差异；
- 归一后，终态订单的重复回报业务字段全等 → 现有守卫 `if not update_fields:
  return` 自然拦截，不再刷新 updated_at；迟到成交（新 execution_identity）
  仍正常 touch（#571 语义保留）；
- 复现脚本转正为 pytest 用例（submitted_at 同刻不同格式不触发写入；新 fill 仍正常）。

### PR-2：101 broker_only 数据修复（恢复合法态）

- `_broker_order_owner_claim` 保持对 broker_only 强制 token=None（不透传，
  token 指向真实订单，belongs 语义不变）；
- 101 数据修复脚本（受控，沿用 #594 修复脚本同款审计）：$unset
  `om_broker_orders.broker_correlation_token`（broker_only 文档恢复合法态）；
  om_orders 的 token 保留（记录 XT remark 观察到的事实，供真实订单接管时匹配）；
- 回归测试：broker_only + token 非法态被 `_classify_broker_order_owner` 拒绝
  （补全断言）。

### PR-3：repository 写前审计 + updated_at-only 写防护

- repository 5 个收口方法（claim/update/CAS/fence/move）共用 audit helper，
  仅真写库才审计，复用 #583 PR5 的 audit_log schema；
- `update_broker_order_fields` 补强：**拒绝 updated_at-only 写入**（无业务字段时
  直接返回，不写库）——堵住 18:05:44 类"只刷新 updated_at"的合法 API 滥用面；
- 运维项（可选后续）：Mongo 单节点改 replSet 开 oplog；
- 明示残余风险：未来绕过 repository 的直写仍不可见，需配合 replSet/oplog。

## 3. #597 关闭验收

1. 终态订单重复回报不再刷新 updated_at（复现测试转正、CI 绿）；
2. 101 broker_only 订单恢复到合法状态（token 语义一致）；
3. repository 写路径有审计，直写可追溯；
4. 三机统一部署 + 健康检查全绿；
5. docs/current 同步（OM 模块写入口径、审计口径）。

## 4. 残余风险

- 08-11 18:05 的**具体执行者**（脚本/人工）因当时无审计无法 100% 追溯；
  修复后同类写入会被审计捕获（债 C 闭环），风险收敛为"历史遗留不可考"。
