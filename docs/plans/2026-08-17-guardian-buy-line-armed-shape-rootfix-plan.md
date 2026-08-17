# 买入线武装状态形状缺陷根治方案（2026-08-17）

> 状态：**已落盘，未实施**。已与 Devin 两轮评审对齐；第二轮门禁终审裁定 **go（有条件）**，P0 修正已并入本文。
> 关联事故：512000（券商ETF）2026-08-17「止盈止损执行.trigger_eval」93 条 `below_min_buy_amount` 噪音。
> 代码基线：本地/100/116 均为 `c0f46099`（dao1oad/fqpack-next main）。

## 0. 事故事实（生产实证，2026-08-17 09:30–09:58，192.168.1.100）

1. 09:30:54.805：512000 买入线 BUY-1（价 0.517）触发，`triggered=true`，quantity=75600；
2. 09:30:54.870：真实提交买单（`submit_intent`，`ladder_triggered=true`，order `ord_91cd7d…`），09:30:56.435 成交（trade_callback 1 条），09:31:05 完成 reconcile；
3. 触发即关写入后，Mongo `freshquant.guardian_buy_grid_states` 中 512000 的 `buy_line_armed` 变为**对象** `{"0": false}`，而非数组 `[false, true, true]`；
4. 09:30:57.750 出现第二笔 `triggered=true`（同数量 75600）——被 15 分钟冷却 `base_buy:512000` 拦下，未重复下单；
5. 09:31:00.858–09:35:48.794：价格仍 ≤ BUY-1，买入后剩余额度 < `min_buy_amount`(10000)，每个 tick（≈3s）落一条 `below_min_buy_amount`（`trigger_consumed=false`），共 **93 条**，全部在 UI 可见（`no_armed_buy_line` 已被 #549 过滤，`below_min_buy_amount` 未过滤）；
6. 09:35:51 后转 `no_armed_buy_line`：不是线被关，而是价格涨回 0.517 上方（命中条件含 `price ≤ BUY-1`）。

## 1. 根因（代码定位）

### 1.1 直接根因：点路径写入数组字段 + 读取端宽松兜底

写侧 `freshquant/strategy/guardian_ladder.py`：

- `_close_buy_lines`（~L325）：`$set: {f"buy_line_armed.{i}": False ...}` 点路径写入；当文档**存在但缺 `buy_line_armed` 字段**时（匹配 `$or` 的 `{"$exists": false}` 分支），Mongo 点路径创建的是**嵌套对象** `{"0": false}`，不是数组；
- `on_buy_zero_fill_terminal`（~L279）：`$set: {f"buy_line_armed.{index}": True}` 同模式；
- `submit_base_buy_batch` 提交失败补偿（`freshquant/tpsl/service.py` L626-630）复用 `on_buy_zero_fill_terminal`，同一风险。

读侧 `guardian_ladder.py::_coerce_buy_line_armed`（L44）：只接受「长度 3 的 list」，**对象/缺失一律回退缺省 `[True, True, True]`（全武装）** → 关闭失效、逐 tick 持续评估。

### 1.2 字段缺失成为常态：`upsert_state` 的半成品创建

`freshquant/strategy/guardian_buy_grid.py::upsert_state`（~L380）用 `update_one({...}, {"$set": fields}, upsert=True)` 创建状态文档，**只写显式传入字段**，从不写 `buy_line_armed`；`upsert_config` 的价格变更重置路径（`last_reset_reason="config_updated"`）即经此创建文档。阶梯状态机（#549/#614）假定该字段存在。

### 1.3 影响面（实测）

| 机器 | 状态文档总数 | 对象形状 | 缺字段 | 正常数组 |
| --- | --- | --- | --- | --- |
| 100 | 19 | 1（512000） | 17 | 1 |
| 116 | 19 | 0 | 19 | 0 |

安全面（已验证）：`buy_active` 全部数组形状且整数组写入；`om_takeprofit_states.armed_levels`（DB `freshquant_order_management`）17/17 字典形状（设计如此，点路径写安全）；全库点路径 `$set` 盘点仅 qfq `slots.*`、clx `publication.*`、ladder `armed_levels.*`/`buy_line_armed.*`——前两者为字典设计，安全。

### 1.4 隐蔽影响（Devin 补充并核实）

对象形状下 `_close_buy_lines` 两个 `$or` 分支（`$exists:false` / `buy_line_armed.0:true`）**均不匹配** → `matched_count=0` → 返回 `ladder_conflict` → 后续真实触发被静默阻断。即：形状损坏后**关闭链与触发链同时失效**（今天靠冷却 + 额度双兜底未重复下单，属偶然安全）。

## 2. 全量审查结论（同类根因清单）

### P0（已实盘缺陷）

1. `guardian_ladder.py` `_close_buy_lines` 点路径写数组（1.1）。
2. `guardian_ladder.py` `on_buy_zero_fill_terminal` 点路径写数组（含提交失败补偿路径）。
3. `upsert_state` `upsert=True` 创建缺字段文档（1.2）。
4. `_coerce_buy_line_armed` 对对象/缺失回退全武装（1.1 读侧）。

### P1（同族结构风险，本次不修、登记）

5. `_is_grid_enabled`（`guardian_buy_grid.py` ~L108）：配置缺失视为启用（文档化旧路径兼容）——**Devin 裁定不随本次收紧**，单独登记。
6. `_coerce_bool` 对字符串 `"false"` 返回 True（当前写入方均为 Python bool，未触发）——登记。
7. 测试 fixture 只覆盖理想数组形状，缺「缺失字段/对象形状」用例。
8. 无状态集合形状健康检查；无 CI 静态防护（点路径写数组）。

## 3. 方案裁定（与 Devin 单轮评审对齐后的最终决策）

### R1 写侧：保留字段级原子写 + 形状守卫 + CAS 归一（Devin 部分反对原「整数组 read→write」后采纳）

**不做**整数组 read→write：会重新引入 tpsl tick worker 与 XT ingest 双进程 lost update，违反 #614/A5「字段级原子 $set」约定。

**做**：

1. `_close_buy_lines`：
   - 查询条件改为 `{"code": code, "buy_line_armed": {"$type": "array"}, f"buy_line_armed.{index}": True}`；
   - **删除** `{"buy_line_armed": {"$exists": false}}` 放行分支（对象形状制造者）；
   - 未匹配且文档存在 → 按形状走「一次性 CAS 归一」：
     - 缺字段：`$set: {buy_line_armed: [True, True, True]}`，条件 `{"buy_line_armed": {"$exists": false}}`（CAS，仅一人成功）；
     - 对象形状：读取现值 → 归一为数组（保留下标现值，缺省 True）→ `$set` 整数组，条件 `{"buy_line_armed": {"$type": "object"}}`；
     - 归一成功后**重试原关闭**（此时字段为数组，点路径原子写生效）。
2. `on_buy_zero_fill_terminal` 与提交失败补偿路径：同样加 `$type:"array"` 守卫 + CAS 归一；**归一 CAS 失败后必须重读状态、以 `$type:"array"` 守卫继续点路径 `$set index=True`（天然幂等），不得「视为已由他方处理」直接返回**——重开的终态必须 armed=True，否则偶发形状竞态会导致买入线静默永闭（终审 P0-①）。
3. `_ensure_buy_grid_state_document`：`$setOnInsert` 补齐完整默认字段（`buy_line_armed: [True,True,True]`、`buy_active: [False,False,False]`），供新建文档路径使用。
4. `upsert_state`：创建路径改为「`$setOnInsert` 完整默认字段 + `$set` 显式字段」一条原子 update（upsert=True），杜绝半成品文档。**实现约束（终审 P0-②）：同一条 update 内 `$set` 与 `$setOnInsert` 不得含同名字段（Mongo 直接报 ConflictingUpdateOperators）——`updated_at`/`updated_by` 必冲突、`disable_grid` 路径的 `buy_active` 也冲突，实现时从 `$setOnInsert` 剔除所有 `$set` 已含的键**。
5. 保持整数组写路径（`rearm_all_buy_lines`/`set_buy_line_armed`/`disable_grid`）不变。

### R2 读侧：fail-accurate 归一（Devin 裁定）

- `_coerce_buy_line_armed`：
  - 数组（长度 3）→ 原样；
  - 对象形状 → 按现值归一（`{"0": false}` → `[False, True, True]`），**不再回退全武装**（现行行为才是危险点）；
  - 文档缺失/字段缺失 → 保持 `[True, True, True]`（默认武装是产品语义）+ **限频告警**，不允许静默。告警实现约定（终审 P1-⑤）：进程内内存节流（按 code×形状类别每 5–10 分钟最多一条 `logger.warning`），tick 热路径零额外 IO；持久化形状异常事件由 R4 的 ops-snapshot 检查承担，不在 `_coerce_buy_line_armed` 内写 runtime 事件/Mongo。

### R3 数据修复（先部署、后修数据；Devin 裁定无「误开」风险）

- 幂等脚本（只读预览 → 人工确认 → 写入），对 100/116 的 `freshquant.guardian_buy_grid_states`：
  - 对象形状 → 按现值归一为数组；
  - 缺失字段 → 补 `[True, True, True]`（与读侧现语义等价，无误开）；
  - 输出每文档 before/after 差异报告；
- 同时校验 `buy_active` 数组形状、`freshquant_order_management.om_takeprofit_states.armed_levels` 字典形状；
- 顺序硬约束：**先部署新代码**（代码自带 CAS 归一兜底），**再跑数据修复脚本**（确定性全量修复 + 校验）。

### R4 防护

- `script/fqnext_ops_host_snapshot.py`（每 5 分钟）增加状态集合形状健康检查：`guardian_buy_grid_states.buy_line_armed`/`buy_active` 非数组、`armed_levels` 非字典 → 输出异常事件（runtime observability）。
- CI/pre-commit 静态扫描：正则匹配已知数组字段名集合（`buy_line_armed`/`buy_active`/`buy_enabled`/`max_position_amounts`）的 `f"字段.{...}"` 与 `"字段.<数字>"` 点路径 `$set` 模式（字段名高度特异，AST 属过度工程）；白名单：`armed_levels`、`slots`、`publication` 等字典字段。扫描器纳入 `script/` 并挂 pre-commit。
- 代码审查规则：数组字段整写、字典字段点写并显式标注。
- ops-snapshot 形状检查的 Mongo 查询失败必须**降级跳过**，不得阻断原有 5 分钟快照主链（终审 P2-⑧）。

### R5 测试

- 单测：`buy_line_armed` 三形态（缺失/对象/数组）× 四操作（close/reopen/rearm/set）+ `_coerce_buy_line_armed` 归一 + 限频告警；
- 集成：真实 Mongo（docker）验证「缺失字段触发 → CAS 归一 → 关闭 → 读侧 no_armed」全链路；验证 CAS 并发安全（两进程同时归一仅一人成功）；
- 回归：512000 场景（触发→关闭→读侧 `no_armed_buy_line`，不再产生 `below_min_buy_amount` 噪音）；
- 数据修复脚本：预览/写入/校验三阶段测试。

### R6 实施与部署

流程：GitHub Issue（高影响、破坏性变更，写明影响面/验收/部署影响）→ feature branch → PR（CI 全绿：governance / pre-commit / pytest）→ 合并 main → 部署 → 数据修复 → 健康检查 → cleanup。

部署面（两台机 100/116）：

| 组件 | 进程/容器 | 原因 |
| --- | --- | --- |
| API 读侧 + 路由 | `fq_apiserver`（docker） | `_coerce_buy_line_armed`、`set_buy_line_armed` 路由 |
| TPSL worker | `fqnext_tpsl_worker`（supervisor） | `evaluate_base_buyline`/`submit_base_buy_batch`/补偿路径 |
| XT ingest（broker） | `fqnext_xtquant_broker`（supervisor） | `xt_reports.py` 调 `on_buy_zero_fill_terminal`/`on_takeprofit_fill`（Devin 补充，已核实） |
| 账户同步 | `fqnext_xt_account_sync_worker`（supervisor） | `position_cleanup.converge_position_configs` → `disable_grid` → `upsert_state`：不重部署则旧 upsert 路径继续创建缺字段文档，防线不闭合（终审 P1-③） |
| ops-snapshot | `fqnext_ops_host_snapshot` | 形状健康检查（R4） |

`fqdagster` 经全仓 grep 不导入 guardian 模块，无需部署。

镜像/代码同步：100 正常走 git + docker build/pull；116 出站受限，用 git bundle + `docker save`/`docker load`（见 `docs/current/machines.md` §5.3）。

## 4. 里程碑切分（合并单元 = 可独立部署 + 可独立回滚）

| 里程碑 | 内容 | 依赖 |
| --- | --- | --- |
| M1 | 代码修复：guardian_ladder / guardian_buy_grid / service.py 补偿路径 + 单测 | 无 |
| M2 | 防护：ops-snapshot 形状检查 + CI 静态扫描 + pre-commit | 无（可与 M1 同 PR 或独立 PR） |
| M3 | 数据修复脚本（只读预览 + 写入 + 校验） | M1 已合并 |
| M4 | 部署 + 数据修复执行 + 健康检查（100/116） | M1–M3 |

建议 M1、M2 独立 PR（文件不重叠，可并行），M3 在 M1 合并后开 PR；M4 为运维执行，不走 PR。

## 5. 验收标准

1. 512000 下次触发后：Mongo `buy_line_armed` 为数组 `[false, true, true]`（或按实际关闭档位），读侧 `no_armed_buy_line`，不再产生 `below_min_buy_amount` 噪音；
   **等价替代口径（不依赖市场触发，三件齐备即可关闭验收 1，终审 G9）**：(a) 数据修复后 100/116 全量 19/19 形状校验通过；(b) 集成回归重放 512000 场景（缺字段/对象 → 触发 → 数组关闭 → 读侧 no_armed、无 below_min 噪音）；(c) 观察期 ≥1 交易日 ops-snapshot 无形状异常事件。
2. 100/116 状态文档全量形状校验通过（19/19 数组，0 对象、0 缺失）；
3. 触发→关闭→重开→补偿四条写路径均有形状守卫测试；
4. CI 静态扫描对「数组字段点路径写」生效；
5. ops-snapshot 形状检查在异常时产生事件；
6. 观察期（部署后 ≥1 个交易日）无新形状异常事件。

## 6. 风险与回滚

- CAS 归一并发：条件更新保证单写者，失败重试幂等；
- 部署顺序错误（先修数据后部署）：新代码读到修复后数组，行为正确，仅失去 CAS 兜底演示——顺序约束已写入 R3；
- 回滚：M1/M2 为独立 PR，可分别 revert；数据修复脚本幂等可重跑，归一方向可逆（对象 → 数组后，旧代码 `_coerce_buy_line_armed` 对数组可正常识别，**旧代码与新数据兼容**）；
- 实施期间禁止直改生产 Mongo；脚本写入前必须出差异报告并人工确认。

## 7. 遗留登记（本次不实施）

- `below_min_buy_amount`（及同类非终态 skip）纳入 UI 可见性过滤（#549 过滤条件扩展）——另立小 PR；
- `_is_grid_enabled` 配置缺失视为启用的兼容语义是否收紧——产品决策，登记；
- `_coerce_bool` 字符串形状防御——低风险，随相关模块改动时处理。

## 附：Devin 单轮评审结论（2026-08-17，只读）

- R1：部分反对原「整数组 read→write」方案，采纳「保留点路径 + `$type:"array"` 守卫 + 异常形状一次性 CAS 归一 + 删除 `$exists:false` 分支」，守卫覆盖 close/reopen/提交失败补偿三入口；
- D1：缺失=默认武装+限频告警保留；对象形状必须按现值归一（fail-accurate）；
- D3：缺失补 `[True,True,True]` 无误开风险（读侧现语义等价）；硬条件 = 先部署后修数据；
- D4：不随本次收紧；D5：止盈侧 dict 设计无同类隐患；
- 补充事实：对象形状下 `_close_buy_lines` 两分支均不匹配 → `ladder_conflict` 意外阻断重复下单，但触发/重开链修复前静默失效；
- R6：部署面补 XT ingest worker（`fqnext_xtquant_broker`，`xt_reports.py` 调 `on_buy_zero_fill_terminal`/`on_takeprofit_fill`）。

全部裁定已并入上文 R1–R6 / D1–D5 决策。

## 附：Devin 第二轮门禁终审结论（2026-08-17，只读，基于 c0f46099 远程仓库实读）

**最终裁定：go（有条件）**——方案与代码事实吻合、并发与部署顺序论证成立，仅 P0 两项为方案文本级修正（不改架构方向），并入 M1 设计后即可开工。

终审修正与条件（已全部并入上文）：

- **P0-①**（G10）：`on_buy_zero_fill_terminal`/补偿路径的 CAS 失败语义修正——归一失败后必须重读并以数组守卫重试置 True（幂等），不得视为已处理，防止买入线静默永闭；
- **P0-②**（G3）：`upsert_state` 单条 update 内 `$set`/`$setOnInsert` 同键冲突剔除规则（`updated_at`/`updated_by` 必冲突、`disable_grid` 的 `buy_active` 冲突）；
- **P1-③**（G8）：部署面补 `fqnext_xt_account_sync_worker`（`disable_grid`→`upsert_state` 路径）；
- **P1-④**（G1/G2）：实现约定——归一+重试在 `_close_buy_lines` 内同一调用完成、各最多 1 次、未匹配返回 False（=ladder_conflict 语义不变），禁止循环；
- **P1-⑤**（G4）：告警节流约定——进程内内存节流、热路径零 IO、持久事件由 ops-snapshot 承担；
- **P2-⑥**：混版本部署窗口竞态按既有部署流程「先停写入面再切换」消除，无需代码处理；**P2-⑦**：聚合管道合并归一+关闭为单条原子 update（可选优化）；**P2-⑧**：ops-snapshot Mongo 查询失败降级。

终审确认项：G5 部署窗口「先部署后修数据」无矛盾（`{"0":false}`→`[False,True,True]` 是迟到的正确关闭，重开仅止盈成交/零成交终态两条路径，无误伤）；G7 CI 已有 `mongo:8.2.2` service + Redis（`.github/workflows/ci.yml`），R5 集成测试可直接落地。

开工顺序建议（终审）：1 个高影响 Issue（含 P0 修正后口径）→ PR#1=M1（guardian_ladder/guardian_buy_grid/service 补偿 + 单测/集成，含 P0-①②、P1-④⑤）、PR#2=M2（防护，文件不重叠可并行）→ PR#3=M3（修复脚本，M1 合并后）→ M4 运维执行（部署面 = fq_apiserver / fqnext_tpsl_worker / fqnext_xtquant_broker / fqnext_xt_account_sync_worker / fqnext_ops_host_snapshot → 数据修复 → 健康检查 → 观察期）。
