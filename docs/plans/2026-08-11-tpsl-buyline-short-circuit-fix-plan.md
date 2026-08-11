# TPSL tick worker「买入线 skipped 短路止盈/止损评估」修复方案（2026-08-11）

> 状态：Devin 评审完成（部分同意，2 个修改点已全部采纳）；方案定稿，待实施
> 关联：GitHub dao1oad/fqpack-next（轻量 bugfix，feature branch + PR，不强制先建 Issue）
> 类型：tpsl tick 消费链 bug 修复（生产实证，192.168.1.100）

## 1. 问题背景（生产实证，2026-08-11）

恩华药业 002262：

- 持仓 27000 股（`xt_positions.stock_code="002262.SZ"`；`om_position_entries` 剩余 27000 股 OPEN）；
- TP 配置就绪：`om_takeprofit_profiles` TP1=22.811（`manual_enabled=true`），
  `om_takeprofit_states.armed_levels={1:true,2:true,3:true}`（2026-08-10 人工 rearm）；
- 价格已超 TP1：`pm_symbol_position_snapshots` 市值 622080/27000 ≈ 23.04 > 22.811；
- 但 `om_exit_trigger_events` 对 002262 无任何记录（TP1 从未触发）。

tick 链路本身正常：producer 订阅 10 个持仓码（`trading=True screening=False codes=10`），
tpsl worker 当日收到 002262 的 tick 1100+ 次。

决定性证据（worker 当日运行时事件
`D:\fqpack\freshquant-2026.2.23\logs\runtime\host_tpsl\tpsl_worker\2026-08-11\tpsl_worker_2026-08-11_4148.jsonl`）：

- `base_buyline` 事件 **10688** 条；`takeprofit` 事件 **0** 条；`batch_create` **0** 条；`stoploss` **0** 条；
- 全部 10 个持仓标的都只有 `trigger_eval|skipped|no_armed_buy_line`（买入线未命中）；
- `evaluate_takeprofit` 全仓唯一生产调用点就是 `freshquant/tpsl/consumer.py`，无旁路。

## 2. 根因

`freshquant/tpsl/consumer.py` `handle_tick`（100 部署 HEAD=48690eda 实测行 86–100；
本地 main 同源，#549 双账本提交 `73d9d998` 引入）：

```python
if event.code in self.active_buy_line_codes:        # 持仓 ∩ 有 buy grid 配置
    buy_line_batch = self.service.evaluate_base_buyline(...)
    if buy_line_batch:                              # bid1>0 时必返回字典
        if buy_line_batch.get("status") != "ready": # 含 skipped
            return buy_line_batch                   # ← 短路：本 tick 终止
        return self.service.submit_base_buy_batch(...)
takeprofit_batch = self.service.evaluate_takeprofit(...)   # 永远执行不到
```

- `evaluate_base_buyline`（`freshquant/tpsl/service.py` 625 行起）只要 `bid1>0` 就**必然返回字典**：
  命中 `{"status":"ready",...}`，未命中 `{"status":"skipped","skip_reason":"no_armed_buy_line",...}`，
  仅 `bid1<=0` 返回 `None`；
- consumer 把任何非 `ready` 结果当作本 tick 终态直接 `return`，导致同一条 tick 的
  `evaluate_takeprofit` / `evaluate_stoploss` 永远不执行；
- 002262 价格 23.04 高于全部买入线（20.55/18.1/17.4），每条 tick 都是 `skipped`，
  因此 TP1 从未被评估。
- 设计意图（consumer.py 注释）是「买入线未命中继续评估 TP」；现有测试
  （`test_tpsl_consumer.py`、`test_dual_ledger_base_t.py` 双集合用例）未覆盖
  「买入线 skipped 后 TP 仍应评估」，短路从未被测出。

## 3. 设计定稿（Devin 修改点 1、2 已采纳）

单一规则：

> 买入线评估不再是「本 tick 的终态」；只有返回 `ready` 才提交买单并终止本 tick。
> 买入线 `skipped` 时：
> - 双集合标的（同时命中 TP/SL universe `active_codes`）→ **继续**评估止盈、止损；
> - buy-line-only 标的（不在 `active_codes`）→ 本 tick 终止（保持 #549 双集合隔离，
>   不给无 TP profile 的标的增加每 tick Mongo 查询与 SL 评估负载）。

推论：

- `evaluate_base_buyline` 返回契约**不变**（skipped 观测事件保留，运维可视）；
- 买入线 `ready` 但 `submit_base_buy_batch` 返回 `cooldown`/`blocked`（冷却、阶梯冲突、
  在途容量耗尽）时本 tick 终止、不评估 TP——买入线价位在 TP1 之下、区间不相交，
  同 tick 双命中不可能，可接受（PR 非目标中显式声明）；
- 不改止盈/止损评估逻辑、不改 `guardian_ladder` 状态机、不重排 TP/买入线顺序。

## 4. 改动清单

### 4.1 `freshquant/tpsl/consumer.py`（唯一生产代码改动）

`handle_tick` 买入线分支改为：

```python
if event.code in self.active_buy_line_codes:
    buy_line_batch = self.service.evaluate_base_buyline(
        symbol=symbol,
        code=event.code,
        bid1=event.bid1,
        last_price=event.last_price,
        tick_time=event.tick_time,
    )
    if buy_line_batch and buy_line_batch.get("status") == "ready":
        return self.service.submit_base_buy_batch(
            buy_line_batch,
            trace_id=None,
        )
    if event.code not in self.active_codes:
        return None
takeprofit_batch = self.service.evaluate_takeprofit(...)
```

同步更新该分支上方过时注释（原「TP 命中即 return…先评估先提交无冲突」描述的是
短路语义，与修复后行为矛盾）。

### 4.2 测试 `freshquant/tests/test_tpsl_consumer.py`（新增）

- a) 双集合标的 + 买入线 `skipped` + TP `ready` → 断言调用序：
  `evaluate_base_buyline → evaluate_takeprofit → submit_takeprofit_batch`；
- b) 双集合标的 + 买入线 `skipped` + TP `None` → 断言 `evaluate_stoploss` 仍被调用；
- c) 回归：买入线 `ready` → `submit_base_buy_batch` 被调用且不再评估 TP；
- d) buy-line-only 标的（不在 `active_codes`）+ 买入线 `skipped` → 断言 TP/SL 均不评估
  （锁定 Devin 修改点 1 语义）；
- e) 买入线 `ready` 但 `submit_base_buy_batch` 返回 `cooldown` → 断言不评估 TP
  （锁定第 3 节推论）。

现有用例预期不回归（已核对：
`test_tpsl_consumer_dual_universe_buy_line_before_takeprofit` 买入线为 ready，
断言 `"takeprofit" not in calls` 兼容；`test_tpsl_consumer_buy_line_only_symbol_still_evaluates`
只断言 `calls[0]`，d) 用例将显式锁定其新语义）。

### 4.3 docs 同步（docs-current-guard 同 PR）

- `docs/current/runtime.md`：Guardian/TPSL 交易运行规则段补一句——
  tick 处理顺序为「买入线评估（仅 ready 提交并终止本 tick）→ 止盈评估 → 止损评估；
  买入线 skipped 不阻断双集合标的的后续评估；buy-line-only 标的终止」；
- `docs/current/troubleshooting.md`：TPSL 排查段补一条症状条目
  「标的已配 TP 且价格超档位但不触发 → 检查该标的是否同时配置买入线；
  买入线 skipped 短路曾导致 TP/SL 全屏蔽（#549 引入，已修复）」；
  同时登记同类边界「evaluate_takeprofit 返回非 ready（无可用数量/blocked）时
  本 tick 同样短路 stoploss，价格区间不相交、风险低，暂不改」（Devin 补充 4）。

## 5. 明确不做（防过度设计）

- 不改 `evaluate_base_buyline` 返回契约与观测事件；
- 不改止盈/止损评估与 `guardian_ladder` 状态机；不重排评估顺序；
- 不处理 `evaluate_takeprofit` 非 ready 短路 stoploss 的同类模式（仅登记，见 4.3）；
- 不处理 100 其它既有问题（venv 损坏、`fqnext_xtdata_adj_refresh_worker` Fatal）；
- 不为历史未触发补单（修复后行为自然恢复，002262 现价仍超 TP1，部署后下一 tick 即应触发）；
- PR 非目标显式声明：买入线 ready 但提交被 cooldown/blocked 时本 tick 终止、不评估 TP。

## 6. 工作流与验证

- 工作流：`local session -> feature branch（codex/ 前缀）-> PR -> merge remote main -> deploy`；
  PR 正文写清背景/目标/范围/非目标/验收标准/部署影响。
- 单元验证：`pytest freshquant/tests/test_tpsl_consumer.py
  freshquant/tests/test_dual_ledger_base_t.py freshquant/tests/test_tpsl_runtime_observability.py`，
  再跑全量 `pytest`；本地预检 `script/fq_local_preflight.ps1 -Mode Ensure`。
- CI：`docs-current-guard` / `pre-commit` / `pytest` 三绿。

## 7. 部署与验收

- 部署面：`freshquant/tpsl/**` → 100 与 116 同步代码（git 同步）+ supervisor 重启
  `fqnext_tpsl_worker`（`script/fqnext_host_runtime_ctl.ps1`）。
- 部署窗口：非连续竞价时段或收盘后重启，次日开盘观察，避免重启瞬间丢 tick 误判。
- 双机健康检查（100 与 116 各自）：
  - worker 运行时事件出现 `kind=takeprofit` 的 `trigger_eval`（不再是 10688:0），
    且 `base_buyline` skipped 事件仍持续产生（观测契约未破坏）；
  - 002262 触发时：`om_exit_trigger_events` 出现 TP1 记录、`armed_levels[1]` 翻 false、
    卖单数量 = base slices 过滤后可卖量（不含 T 仓）、走 `submit_takeprofit_batch`；
  - 无 TP profile 的 buy-line-only 标的 tick 不产生新增 error 事件
    （ValueError 路径静默）；
  - 回归：价格跌破 BUY-1 时买入线仍正常提交。

## 8. Done 定义

`Done = PR 合并 + CI 三绿 + docs/current 同步 + 100/116 部署 + 双机健康检查 + cleanup`
（AGENTS.md 第 8 节）。
