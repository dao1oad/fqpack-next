# 零股成交回报入账修复方案（2026-08-18）

> 状态：方案待评审（Devin 对齐后实施）。
> 关联事故：116 今天 10:01 002123（梦网科技）T 买入 2000 股成交 1640+100+260 三笔，
> 其中 1640/260 为非整手成交，被 ingest 按 `non_board_lot_quantity` 拒绝入账，
> 内部账本只记 1740 股 → 对账 gap（buy 260, REJECTED, board_lot_rejected）
> → 持仓管理检查显示「异常」。100 无买入是该信号被 `signal_structure_check`
> 正常拦截，不属于本方案范围。

## 1. 事实与现行口径

* 116 `om_position_entries`：002123 t entry（buy_cluster）= 1740 股 @8.18；
  券商 `xt_positions` = 19300（昨日 17300 + 今日 2000，on_road_volume=2000）；
  gap `quantity_delta=260`，state=REJECTED，resolution_type=board_lot_rejected。
* 现行设计（docs/current/modules/order-management.md「Board Lot 规则」）：
  「odd-lot 不会生成 position_entry/entry_slice/exit_allocation；写入
  om_ingest_rejections；若差额不是 100 整数倍，保留 REJECTED gap，不要手工伪造 entry」。
* 该口径的问题：内部账本长期比真实持仓少 260 股（002123），而买卖量、止盈
  数量、T 切片全部以内部账本为真值 → 后续卖出会少卖 260 股；且检查页持续
  告警「异常」。
* 影响面（实测）：116 有 2 条 zero-lot 拒绝（均为 002123）；100 0 条；
  101 待部署后扫描确认（预计 0~少量）。

## 2. 方案选项

* **A（展示层最小修复）**：board_lot_rejected 的 REJECTED gap 在持仓管理检查
  中显示为「已知差异（零股）」而非异常。不改账本。缺点：账实不符持续存在，
  卖出少 260 股。
* **B（治本：成交事实全量入账）**：成交回报（fills）不再做整手校验，全量
  进入 V2 账本（委托下单仍必须整手）；配套「剩余持仓 < 一手允许零股清仓卖出」；
  数据修复补记存量被拒零股。改动面：ingest + rebuild + 卖出约束 + 文档 + 修复脚本。
* **C（折中：对账收敛零股）**：保持 ingest 拒绝，但 reconcile 对零股差额
  auto_open 零股 entry 并关闭 gap。本质仍是零股入账，但经由对账间接完成，
  复杂度更高且时序不确定。

**推荐 B**：账本必须反映真实持仓；委托整手与成交零股是两个正交规则。

## 3. 方案 B 实施范围

1. `freshquant/order_management/ingest/xt_reports.py`：
   * buy 分支：删除 `_is_board_lot_quantity` 拒绝，成交事实全量走
     `_upsert_broker_position_entry`（cluster 聚合）；
   * sell 分支：删除 `_is_board_lot_quantity` 拒绝，全量走 guardian sell
     分配（`allocate_sell_to_entry_slices_with_budget` 对零股无假设，已验证）。
2. `freshquant/order_management/rebuild/service.py::_rebuild_position_entries`：
   同样允许零股 fills 进入 buy cluster / sell 重放（运行态与重建一致）。
3. 卖出清仓零股支持：
   * `freshquant/order_management/sell_constraints.py::resolve_sell_submission_quantity`：
     当该标的 `can_use_volume` < 一手（100）且 > 0 时，允许全额清仓卖出
     （A 股规则允许剩余不足一手一次性卖出），不再 floor 到 0 阻断；
   * `freshquant/tpsl/takeprofit_quantity.py` 的卖出数量解析与
     `freshquant/tpsl/service.py` 卖单提交路径同步核对该语义。
4. 数据修复脚本 `script/repair_odd_lot_fill_ledger.py`（三阶段 preview/apply/verify，幂等）：
   * 扫描 `om_ingest_rejections.reason_code=non_board_lot_quantity`；
   * 对每笔被拒 fill：按 broker_order_key 找到所属 buy cluster entry，把被拒
     数量并入 entry/slices（或按重建规则重放该 broker order 的全部 fills）；
   * 关闭对应 REJECTED gap（写 `om_reconciliation_resolutions`，resolution_type=
     `odd_lot_fill_repair`）；
   * verify：内部 entry 总量 == broker `xt_positions` 口径（或 gap 消失）。
5. 文档同步（同一 PR）：
   * `docs/current/modules/order-management.md`：Board Lot 规则改为
     「委托下单整手硬约束；成交回报零股全量入账；卖出清仓允许零股」；
   * `docs/current/troubleshooting.md`：odd-lot 拒绝条目改为「存量数据用
     repair 脚本补记」。
6. 测试：
   * ingest 零股 buy/sell 成交入账单测（fake + 真实 Mongo）；
   * rebuild 重放零股 fill 单测；
   * `resolve_sell_submission_quantity` 清仓零股分支单测（含 0 股、不足一手、整手回归）；
   * 修复脚本 preview/apply/verify 测试；
   * 回归：guardian signal_structure_check 行为不变（100 场景）。
7. 部署面（三机）：
   * `fq_apiserver` 镜像重建 + compose up（order_management 代码在内）；
   * `fqnext_xtquant_broker` 重启（XT 成交回报 ingest 进程）；
   * `fqnext_tpsl_worker` 重启（卖出数量解析）；
   * 数据修复执行顺序：先部署新代码 → 116 修复 002123（260 股）→ 三机
     `repair_odd_lot_fill_ledger.py preview/apply/verify` 扫描收敛 → 健康检查。

## 4. 验收标准

1. 116 002123 t entry = 2000 股（1740+260），gap 关闭（resolution 写入），
   持仓管理检查不再异常；
2. 三机 `om_ingest_rejections` 无存量 `non_board_lot_quantity`（或全部已修复）；
3. 委托下单整手校验行为不变（手工/策略下单回归测试）；
4. 卖出清仓零股：模拟「持仓 60 股」可全额卖出，模拟「0 股/100 股以上」行为不变；
5. CI 全绿（governance/pre-commit/pytest）；Devin 合并前验收通过；
6. 部署后 1 个交易日无新增零股拒绝与 REJECTED gap。

## 5. 风险与回滚

* 清仓零股卖出必须与券商侧规则一致（实测 XT 允许剩余不足一手清仓）；
* rebuild 与运行态共用同一「零股入账」helper，避免两套口径；
* 回滚：本 PR 可整体 revert；数据修复脚本幂等，修复后的 entry 与旧代码
  兼容（旧代码读 V2 不受影响，仅不再拒绝新零股）；
* 修复脚本 apply 前必须 preview 人工确认差异报告。

## 6. 非目标

* 100 的 `signal_structure_check` 拦截行为（设计内，不改）；
* 两机信号评估时序对齐（另议）；
* 手工导入/reset 的整手校验（维持拒绝零股）。
