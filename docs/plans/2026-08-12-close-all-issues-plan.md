# 关闭全部 Issue 的总体方案（2026-08-12）

> 目标：4 个 open issue（#578/#587/#588/#589）全部关闭，走完
> merge + ci + docs sync + deploy + health check + cleanup，三机守恒探针全绿，无遗留 open issue。
> 关键决策：#578 默认指数按用户决策采用 **t³（3.0）**（Devin 曾建议默认 t²，用户否决，PR/文档中显式记录）。

## 现状基线

- 已关闭：#571、#586（附完成评论）。
- Open：#578（代码，Devin 验收不通过、3 项必改）、#589（代码，方案已 Devin 评审）、
  #588（数据调查）、#587（数据操作）。
- 最新 main：`2c6c744e`（含 PR1-PR7）；#578 分支 `codex/issue-578-formalize` 已就绪。

## 逐项方案

### #578 guardian 做T买入指数可配置（默认 t³）——接近完成

现状：`codex/issue-578-formalize`（基于 2c6c744e）cherry-pick 完成；85 pytest + 13 webui 绿；
pre-commit 绿；Devin 验收：实现质量合格，**3 项必须修复**：

1. PR 正文显式记录 t³ 默认的运营影响（未配置部署 t<1 时 B=R×t³ < R×t²，买入金额变小）与
   部署矩阵（strategy 改动需重部署后端 + fqwebui）；
2. `freshquant/strategy/guardian_buy_grid.py:495` 注释 `B = R × t²` → `t^n`；
3. `morningglory/fqwebui/public/trading-guide/index.html:549` 与 `web/trading-guide/index.html:549`
   `B = R × t²` → `t^n`（public 为源、web 为发布产物，需同步）。

步骤：修 3 项 → 重跑测试/pre-commit → Devin 复审通过 → push + PR → CI → merge →
deploy（API/Guardian 相关 + fqwebui）→ 验收（设置页可见 buy_amount_exponent、decision context
含 exponent=3）→ **关闭 #578**。

### #589 must_pool 同步待买空分组阻断 + allow_empty（方案C）——待实现

Devin 已评审方案，**必须按以下修正实现**：

1. **关键遗漏**：`sync_must_pool_from_tdx_self_select` 的空 `target_code_set` 守卫会跳过删除
   （`if target_code_set else []`），`allow_empty` 将静默变 no-op——需放开
   `if target_code_set or allow_empty` 并补用例；
2. 定义 `TdxEmptyGroupError(RuntimeError)`，路由 `except TdxEmptyGroupError` 返回
   400 + `{"code":"empty_group"}`（其余异常保持 500）；文件缺失/GBK 失败无论 allow_empty 均阻断；
3. 前端两入口（StockMustPools.vue / kline-slim.js）catch 需从 `err.response.data.code`
   读取 `empty_group`（成功路径才是 `result.code`）；
4. 边界用例：分组非空但代码全无效时**不清空**；
5. docs：interfaces.md 补 allow_empty 契约；kline-webui.md 顺带修正旧接口路径。

步骤：实现（后端 service/routes + 前端两入口 + 测试 + docs）→ 本地测试 → Devin 验收 →
PR → CI → merge → deploy（api + webui）→ 验收 → **关闭 #589**。

### #588 101 归属一致性告警（600104 t entry）——待调查

步骤：查 101 `xt_trades`/`xt_orders` 2026-08-11 14:45:05 600104 成交记录及其与 116
14:45:05 7,400 股成交的关系 → 结论（确为 101 账户 broker-only 买入 → entry/member 改 base；
镜像/残留 → 清理该 entry）→ 定向修复（dry-run → execute + 审计）→ 探针
`ledger_intent_alignment` 归零 → **关闭 #588**。

### #587 100/101 账本存量漂移（002262 无 entry）——待批准执行

步骤：`rebuild_order_ledger_v2.py --mode flatten-cost-price`（100/101 各一次）：
dry-run 先行 → `--backup-db` 备份 → execute → 守恒复验 → 探针 `ledger_vs_positions` 归零 →
**关闭 #587**。

门禁：破坏性操作，执行前需用户批准；备份库保留一个对账周期。

## 顺序与依赖

- 两条并行轨道：代码类（#578 → #589）与数据类（#588 → #587），互不依赖；
- 优先级：#587/#588（生产账本正确性，直接影响容量计算与守恒告警）> #589（当天操作阻塞）>
  #578（默认值变更，需显式记录）；
- 合并顺序：#578 与 #589 文件不重叠（strategy/settings vs stock_service/routes/webui pools），
  可独立合并、独立回滚。

## 收口验收（全部完成后）

1. `gh issue list --state open` == 0；
2. 三机 `/api/ops/ledger-invariants`：116 ok=true；100/101 处置后 violation_count=0；
3. docs/current 与代码事实一致（t³ 默认、allow_empty 契约、无 t² 残留）；
4. 无遗留本地 feature 分支/临时文件；本方案文档保留于 docs/plans/。

## 关键决策记录

- #578 默认指数 = **3.0（t³）**：用户明确决策；运营影响（t<1 时买入金额变小）已要求在
  PR 正文与 docs/current 显式记录。
