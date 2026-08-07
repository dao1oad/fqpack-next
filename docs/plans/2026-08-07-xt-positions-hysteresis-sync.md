# XT 持仓快照同步滞回（Hysteresis）方案

> 状态：已通过 Devin 实施前审查（结论：需修改，主体方向正确；2 个必改项已并入本方案）
> 日期：2026-08-07
> 关联事故：2026-07-14 ~ 08-03 期间 600271/513180 等持仓标的间歇性从 `xt_positions` 消失，
> 导致 Guardian 监控范围静默收缩、实时信号漏处理数周。

## 1. 背景与根因

### 当前实现

`freshquant/xt_account_sync/persistence.py::persist_positions` 采用全量覆盖式同步：

```python
# 先 upsert 本次快照中的每个标的
collection.bulk_write(batch)
# 再删除"不在本次快照中"的标的  <-- 危险点
collection.delete_many({"account_id": ..., "stock_code": {"$nin": stock_codes}})
```

`freshquant/xt_account_sync/service.py::_detect_suspicious_position_snapshot` 用三条件
阈值拦截异常快照：

- 空快照（`symbol_count == 0`）→ `empty_snapshot_with_positive_market_value`
- 缩水 ≤50% 标的数 **且** 估值 ≤20% **且** 数量 ≤20% → `shrunk_snapshot_*`

### 根因（已核实）

1. **直接机制**：XT 返回部分持仓（连接不稳、会话过期时常见）时，
   `query_stock_positions()` 的 `retry_on_empty=False` 不重试，部分快照直接进入
   `persist_positions`；`delete_many` 把缺失标的**即时**从 `xt_positions` 删除。
2. **阈值漏洞**：实测缺 3/10 标的（`symbol_ratio=0.70`、`value_ratio=0.67`）完全不触发
   quarantine（阈值是 0.5/0.2），直接覆盖删除。部分缺失在阈值工程上**必然漏检**，
   不是调参能解决的。
3. **放大器**：100 的 venv（uv trampoline 指向已删除的解释器）损坏，worker 无法重启
   自愈；期间 `ModuleNotFoundError: dynaconf` 5,747 次、`xtquant connect failed: -1`
   4,307 次、`empty_snapshot` quarantine 11 次，持仓同步链路极不稳定。
4. **静默收缩**：Guardian scope 每 30 秒从 `xt_positions` 重建，
   `pool changed` 日志只在**数量变化**时打印；标的集合变化但数量不变时完全无日志。

## 2. 方案总览

核心思路：**把"本次快照缺失"从"即时删除"改为"延迟可逆确认"**。

用一条**滞回（hysteresis）规则**替换 `delete_many` 即时删除，同时**删除整条 quarantine
阈值链**（保留一条空快照守卫）。一条规则天然覆盖空快照、部分缺失、缩水三类问题，
且断连时 fail-safe 是结构自带的（快照不更新 → 不删除 → 保留旧持仓）。

> **Devin 审查必改项（高危，已并入 §3.4）**：
> `sync_positions_once` 中 `reconcile_account(positions=normalized_positions)` 传的是
> **本次快照**而非库内 `xt_positions`。滞回只保护文档不被删除，但 reconcile 用本次快照
> 计算 delta，缺失标的 45 秒（3 轮 `external_confirm_observations`）即触发
> `_confirm_close_gap` 自动平掉内部 entry；`_detect_sell_gap_blast` 熔断需 ≥3 个 sell 标的
> 且 sell 数量占内部总仓位 ≥50%，缺 1-2 个标的时**不触发熔断**。
> 必改：reconcile 必须使用滞回后的有效持仓视图（库内存量 + 本次快照并集），
> 空快照守卫时跳过 reconcile。

### 设计原则

- 最小改动、净删代码：不新增逐标的证据检索、不新增独立锚点、不引入 fail-closed。
- `xt_positions` 滞回后本身就是持久化锚点，Guardian 零功能改动受益。
- 宁可多监控几分钟（可能对已清仓标的多算一次卖出信号），不可漏监控。
  卖出路径本身有 `sellable_volume_check`（按 `can_use_volume` 截断）与仓位管理门禁，
  多监控风险可控（Devin 提示：卖侧最终兜底是券商拒单而非门禁，见 §3.6）。

## 3. 详细设计

### 3.1 滞回状态存储

在每个 `xt_positions` 文档上维护同步元数据字段（与持仓数据同批写入）：

```json
{
  "account_id": "...",
  "stock_code": "600271.SH",
  "...": "持仓字段...",
  "sync_missing_count": 0,
  "sync_last_seen_at": 1784597772
}
```

- `sync_missing_count`：连续缺失轮数（日志与测试用）。
- `sync_last_seen_at`：最近一次出现在快照中的 epoch（**墙钟语义，Devin 修正**）。

不在本次快照中的标的，`sync_missing_count` 累加 1、`sync_last_seen_at` 不更新；
出现在本次快照中的标的，`sync_missing_count` 清零、`sync_last_seen_at` 更新为当前时刻。

### 3.2 `persist_positions` 改造（persistence.py）

```python
MISSING_DELETE_THRESHOLD = 20          # 连续缺失轮数阈值
MISSING_DELETE_WALL_CLOCK_SECONDS = 300  # 缺失墙钟阈值（约 5 分钟）

def persist_positions(positions, *, account_id=None, collection=None,
                      invalidator=None, missing_threshold=MISSING_DELETE_THRESHOLD,
                      missing_wall_clock_seconds=MISSING_DELETE_WALL_CLOCK_SECONDS,
                      missing_count_field="sync_missing_count",
                      last_seen_field="sync_last_seen_at"):
    ...
    # 1) upsert 本次快照中的标的：sync_missing_count=0, sync_last_seen_at=now
    # 2) 对不在本次快照中的存量标的：$inc sync_missing_count 1（last_seen 不动）
    #    驱逐条件 = missing_count >= missing_threshold
    #               OR now - sync_last_seen_at >= missing_wall_clock_seconds
    # 3) 空快照守卫：本次快照为空且存量非空时，跳过 $inc 与删除（保留存量）
```

具体实现：

- 读取本次快照 `stock_codes` 与存量集合（`account_id` 下所有文档）。
- 本次快照非空时：
  - `stock_codes` 中标的 upsert，`$set` 持仓字段 + `sync_missing_count: 0` +
    `sync_last_seen_at: now`。
  - 存量中 `stock_code not in stock_codes` 的标的：
    - `update_many({account_id, stock_code}, {"$inc": {missing_count_field: 1}})`
      （不更新 `last_seen_at`）。
    - 驱逐：`delete_many({account_id, "$or": [
        {missing_count_field: {"$gte": missing_threshold}},
        {last_seen_field: {"$lte": now - missing_wall_clock_seconds}},
      ]})`——条件删除，原子无读-改-写竞争（**Devin 必改**）。
- 本次快照为空（`not stock_codes`）且存量非空 → **跳过 $inc 与删除**，
  返回 `empty_snapshot_guard=True`（**Devin 必改：空快照不递增计数**，
  否则断连恢复后首个部分快照会把断连期存量标的计数一次性推到阈值）。
- 删除前把待删标的清单（驱逐前读取候选）写入 `freshquant.audit_log`
  （`operation=xt_positions_missing_evict`，含 `stock_code / missing_count /
  last_seen_at / snapshot_codes`）。
- 返回 `{"count", "account_id", "deleted_missing": [...], "empty_snapshot_guard": bool}`。

### 3.3 删除 quarantine 阈值链（service.py）

- 删除 `_detect_suspicious_position_snapshot`、`_summarize_position_snapshot`、
  `_normalize_snapshot_symbol`、`_position_field`、`_coerce_int`、`_coerce_float`
  全部函数（约 120 行）。
- `sync_positions_once` 不再调用 `_detect_suspicious_position_snapshot`，
  不再返回 `quarantined / persist_skipped`。
- 保留：`_load_latest_credit_snapshot_for_account` 若被 reconcile 链复用则保留，
  否则一并删除（实施时按引用确认）。
- `persist_positions` 内部空快照守卫（3.2）替代原 quarantine 的空快照拦截，
  语义从"整体跳过同步"变为"保留存量、正常写订单/成交增量"。

### 3.4 有效持仓视图 + reconcile 修复（service.py）— Devin 必改（高危）

在 `persist_positions` 返回后、调用 `reconcile_account` 前，构建**有效持仓视图**：

```python
def _resolve_effective_positions(
    *,
    current_positions,    # 本次快照 normalized
    persisted_view,       # persist_positions 落库后的库内集合
):
    # 库内 sync_missing_count < K 且未超墙钟阈值的存量标的（滞回期内仍视为有效持仓）
    # ∪ 本次快照标的；合并 volume / avg_price / stock_code
```

具体规则：

- 有效持仓 = 本次快照中所有标的 + 库内 `sync_missing_count < MISSING_DELETE_THRESHOLD`
  **且** 未超墙钟阈值的存量标的（后者保留其库内 volume 与价格快照）。
- 把**有效持仓视图**传给 `reconcile_account(positions=effective_positions)`，
  **不再传原始 `normalized_positions`**。
- 空快照守卫命中（`empty_snapshot_guard=True`）时：**跳过 reconcile**
  （返回 `reconcile_skipped=True`），防止空快照触发全账户 sell gap 误平账。
- 效果：缺失标的在滞回窗口内 delta≈0 → 不产生 sell gap → 不自动平账；
  真实清仓（连续缺失 ≥K 或超墙钟且被驱逐）后才进入 reconcile 收敛。

### 3.5 worker 日志（worker.py）

`_log_positions_quarantine` 改为 `_log_positions_persistence`：

- `empty_snapshot_guard=True` →
  `logger.warning("xt_account_sync empty snapshot guarded; kept existing positions")`
- `deleted_missing` 非空 →
  `logger.info("xt_account_sync evicted missing positions: %s", ...)`

### 3.6 Guardian scope 收缩告警（monitor_stock_zh_a_min.py）

`_refresh_codes_loop` 中 `new_codes != old_codes` 时：

- 计算 `removed = old_codes - new_codes`，日志升级为：
  `[Event] pool changed: {len(old)} -> {len(new)} removed=[...]`
  （标的集合变化无论数量变化都打印，问题 4 的静默收缩可观测）。
- 其余逻辑不变（仍按新 scope 更新 filter_codes）。

Guardian 本身**零功能改动**：`xt_positions` 滞回后，真实清仓标的会延迟约 5 分钟
才从 scope 移除。

> **Devin 补充（已接受，列为可选增强，不在本 PR 强制范围）**：
> 买侧存在真实风险——`_handle_holding_buy` 无标的级持仓校验，滞回 5 分钟内价格跌破
> 加仓阈值会给已清仓标的真实下买单（现状已存在，窗口从 15s 放大到 5min）。
> 卖侧兜底其实是**券商拒单**而非门禁（`can_use_volume` 读自 xt_positions，滞回期是过期值）。
> 建议后续提交前加 `volume > 0 且 sync_missing_count == 0` 校验。

### 3.7 阈值参数

- `MISSING_DELETE_THRESHOLD = 20`（连续缺失轮数）。
- `MISSING_DELETE_WALL_CLOCK_SECONDS = 300`（缺失墙钟，约 5 分钟）。
  - **Devin 修正**：退避期"20 轮 ≠ 5 分钟"（断连/退避会拉长实际间隔），
    必须用 `sync_last_seen_at` 墙钟语义，轮数仅作日志与测试。
  - 驱逐条件为两者任一达标。
- 持续部分快照超阈值仍会删除（残余风险，需在运维文档明示）。
- 可配置项：常量即可，不需要进 system_settings（避免过度设计）。

## 4. 测试计划（TDD）

### 4.1 `freshquant/tests/test_xt_account_sync_persistence.py`（新增）

用 fake collection（dict 模拟）覆盖 `persist_positions`：

1. 正常 upsert：新标的插入、存量标的更新、`sync_missing_count` 清零、`last_seen_at` 更新。
2. 首次缺失：缺失标的 `sync_missing_count = 1`，**不删除**。
3. 连续缺失达到轮数阈值：`missing_count >= K` 时删除，`deleted_missing` 返回该标的。
4. 缺失中途出现：`missing_count` 清零，不删除。
5. 空快照守卫：本次快照为空、存量非空 → 不删除、**不递增计数**、返回
   `empty_snapshot_guard=True`。
6. 删除审计：`audit_log` 落盘 `xt_positions_missing_evict`。
7. **K-1 边界**：`missing_count = K-1` 时不删、`= K` 时删。
8. **墙钟阈值**：`last_seen_at` 超过 300s 时驱逐（即使轮数不足）。
9. **volume=0 行**：XT 返回 `volume=0` 的标的视为"有该标的但已清仓"（真实清仓场景），
   有效视图立即剔除并允许驱逐（区别于"标的缺失"）。
10. **invalidator 调用**：每次持久化后 `mark_stock_holdings_projection_updated` 被调用。

### 4.2 `freshquant/tests/test_xt_account_sync_worker.py`（修改）

- `_log_positions_persistence`：`empty_snapshot_guard` 与 `deleted_missing` 的日志分支。
- `SequencedSyncService` 相关测试适配（若引用 `quarantined` 字段则更新断言）。
- **reconcile 交互用例（Devin 必改，最重要）**：
  - 缺 1 个标的时，`reconcile_account` 收到**有效持仓视图**（含滞回期标的），
    不产生 sell gap；
  - 空快照守卫时 `reconcile_account` 不被调用（`reconcile_skipped=True`）；
  - 滞回期标的被驱逐后才收到剔除后的视图。

### 4.3 `freshquant/tests/test_guardian_monitor_event_routing.py`（修改）

- scope 收缩时日志包含 `removed=[...]` 明细（mock logger 断言）。

### 4.4 运行命令

```powershell
.venv\Scripts\python.exe -m pytest freshquant/tests/test_xt_account_sync_persistence.py -q
.venv\Scripts\python.exe -m pytest freshquant/tests/test_xt_account_sync_worker.py freshquant/tests/test_guardian_monitor_event_routing.py -q
```

## 5. 部署与回滚

### 部署矩阵（按 AGENTS.md §6）

- 改动 `freshquant/xt_account_sync/**` → 重部署后端并重启 `xt_account_sync.worker`。
- 改动 `freshquant/signal/**`（monitor 告警日志）→ 重启 Guardian monitor
  （`monitor_stock_zh_a_min --mode event`）。
- 不涉及 Docker 镜像（宿主机 Python 进程）。

### 回滚

- 代码回滚：还原 `persist_positions` 为即时 `delete_many`，恢复 quarantine 链。
- 数据回滚：`xt_positions` 若被误删，从 `position_review_evidence_archive` /
  `om_execution_history_archive` 重建（现有链路已有）。
- 滞回字段 `sync_missing_count / sync_last_seen_at` 为冗余元数据，回滚时忽略即可。
- **reconcile 修复回滚**：若新 reconcile 视图有回归，回滚到
  `positions=normalized_positions` 并恢复空快照 quarantine 拦截（还原旧语义）。

## 6. 验收标准

1. 单测通过：4.1 十条用例 + 4.2/4.3 适配。
2. 生产验证（100）：
   - 手动模拟"XT 返回缺 1 个标的"→ `xt_positions` 该标的保留且 `sync_missing_count`
     递增，5 分钟后才删除；
   - "断连"→ 快照停更、无删除；
   - Guardian 日志 scope 变化带 `removed=[...]`；
   - **缺 1 个标的时 reconcile 不产生 sell gap、不自动平账（Devin 必改验证）**。
3. 回归：真实清仓路径（有卖出成交或 `volume=0` 行）在约 5 分钟后从 scope 移除，
   不阻塞后续交易。
4. 部署后 `fqnext_host_runtime_ctl.ps1 -Mode Status` 全 Running。

## 7. 非目标

- 不实现"内部账本为真值、快照只对账"的长期架构（另行评估）。
- 不修复 100 的 venv 损坏（运维动作，非代码改动；部署前需先重建 venv）。
- 不引入逐标的证据检索 / 独立锚点 / fail-closed（Devin 审查认为过度设计，已否决）。
- 买侧 `sync_missing_count==0` 校验为可选增强（§3.6），不在本 PR 强制范围。
