# CLX 信号研究 Handoff 手册（供后续 agent 接手）

最后更新：2026-07-25。配套进展总结：`2026-07-25-clx-research-progress-summary.md`。

## 1. 环境与访问拓扑

- 项目主机（Windows，含 D:\fqpack）通过 **XN 接口**访问：`https://xn.cardguidebook.com`，HTTP 头 `X-XN-Key`（密钥由用户提供，**绝不写入任何文件/commit/日志**）。端点均 POST+JSON：`/xn/get{path}`、`/xn/put{path,content}`、`/xn/dir{path}`、`/xn/run{cmd,timeout}`。
- agent 本机 helper（如接手 agent 在同一 VM）：`C:\Users\Administrator\xn.ps1`（-Op get/put/dir/run）、`vmrun.ps1`（把命令文件送到项目主机→Linux VM 执行并解析输出）、`show.ps1`。
- 计算发生在项目主机上的 Linux VM 的 docker 容器 **`fq_clx_backtest_worker`**，Python：`/freshquant/.venv/bin/python`。流程：本地写脚本 → `/xn/put` 到 `D:\fqpack\tmp\` → 项目主机 `.codex\upload_vm.py` 上传到 VM `/home/fqcompare/` → `docker cp` 进容器 → 执行 → `docker cp` 结果回 `/home/fqcompare/` → `cat` 取回。
- 注意：XN /run 输出嵌套在 `raw["result"]["out"]`；PowerShell 不支持 heredoc（用脚本文件，勿用 `python - <<EOF`）。

## 2. 仓库与分支

- GitHub：`dao1oad/fqpack-next`；工作分支 `codex/clx-backtest-platform-465`（Draft PR #466）。
- 项目主机工作树：`D:\fqpack\worktrees\clx-backtest-platform-465`（**从这里 push**；agent 本机 clone `C:\Users\Administrator\repos\fqpack-next` push 会 403）。
- push 方法：写 bat（add 指定文件 → commit → push origin），`/xn/put` 到 `D:\fqpack\tmp\`，`/xn/run` 执行。遇 "Connection was reset" 重试即可。
- 治理规则：不 push main、不 force push、不 amend、不 `git add .`、不修改测试、feature branch → PR → CI。

## 3. 数据（全部只读，sealed）

- Run：`01KBYC7REC0V3RY99634853AAB`（COMPLETE / REVEALED / reveal_count=1，**禁止再 reveal HOLDOUT、禁止 /start /freeze、禁止改 sealed 文件**）。
- 事件明细：容器内 `/opt/clx-backtest/events/clx-preview-99634853b/event-study/code_buckets/code_bucket=*/event_outcomes/reveal_year=*/part-*.parquet`。关键列：code, model_code, direction(+1买/−1卖), reveal_date, entry_trade_date, raw_entry_open, entry_status, split_id, split_boundary_status, occurrence, primary_trigger_semantic, h{1,3,5,10,20}_direction_adjusted_return/mfe/mae/status。
- **陷阱 1**：`h*_direction_adjusted_return` 与 event_metrics 的 `mean` **已按方向调整**（正=预测正确），绝不能再乘 direction（此前已犯过一次并公开更正）。
- **陷阱 2**：raw_* 价格未复权；长持有必须用 snapshot 的 qfq 价格。
- 复权行情：容器内 `/opt/clx-backtest/snapshots/cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4/bars/code_bucket=*/code=*/part-*.parquet`，列含 raw_*, adj_factor, qfq_open/high/low/close（`qfq = raw × adj_factor`）。用 `pyarrow.dataset(..., format="parquet")`（**不要** partitioning="hive"，会与文件内列冲突）+ `filter=ds.field("trade_year")`。
- 研究口径：`split_boundary_status=ELIGIBLE & entry_status=EXECUTABLE`，TRAIN=2005-2019 / VALIDATION=2020-2023，按 (code, model, direction, reveal_date) 去重；`merge_asof` 前左右表须按时间列排序。

## 4. 分析脚本（agent 本机 C:\Users\Administrator\fq\）

| 脚本 | 用途 |
|---|---|
| `grid_scan.py` | 全模型条件网格扫描（occurrence × 触发 × 价格分层） |
| `s16_extract.py` / `s16_subset.py` | S0016 深挖 / 条件子集 |
| `pair_scan.py` | 20 日上限闭环（单模型 + 18×18） |
| `pure_signal.py` | 纯信号闭环 RAW 版 |
| `qfq_pure.py` | 纯信号闭环前复权版（最新，含 snapshot qfq join 模板） |
| `cmd*.txt` + `vmrun.ps1` | 远程执行命令模板 |
| `add_pure.py` / `add_pair.py` | 结果 JSON 注入前端 data.js |

## 5. 可视化

- 页面源：`C:\Users\Administrator\fq\clx_viz\`（index.html / data.js / echarts.min.js），部署目标：项目主机 `D:\fqpack\tmp\clx_viz\`（/xn/put 两个文件），服务 `D:\fqpack\tmp\start_viz.ps1` → http://127.0.0.1:18099/（项目主机本机）。agent 本机验证：本地 `python -m http.server 18099 --directory C:\Users\Administrator\fq\clx_viz`。
- data.js 内嵌常量：MD（事件统计）、COMBO（冻结组合）、S16/S16SUB、GRID（条件筛选）、PAIR（20日闭环）、PURE（纯信号，当前为**前复权**数据）。

## 6. 已确立的结论（勿重复推导，勿反转）

1. 卖出信号 = 反向指标（信号后平均上涨），不能当逃顶/平仓依据；"卖出反向做多"是最强规律之一。
2. 买入最强候选：S0016 > S0006 > S0008/S0009（三条独立路线收敛）。
3. 普适放大器：低价 × 第 1 次触发 × 强确认。
4. S0004/S0007/S0014/S0015 纯信号操作系统性亏损。
5. 高单笔收益 ≈ 长持有 + 2020-23 小盘 β，单位时间收益低（S0016 ≈0.06%/天）。

## 7. 研究边界（硬约束）

只读 sealed artifacts；不重跑 facts；不用 HOLDOUT 做任何筛选；所有新结果须标注"事后研究、未预注册、未扣费"；密钥/凭据不落盘不提交。

## 8. 建议的下一步（未开始）

1. 起草预注册研究合同：S0016/S0006/S0008 纯信号 + 条件版本（低价×首次×强确认），指定费用模型与新 HOLDOUT 窗口。
2. 组合层撮合验证（容量、涨跌停、10 仓约束）。
3. "卖出信号反向做多"作为独立候选纳入合同。
4. 把 fq/ 下核心脚本整理进仓库正式目录（当前仅报告入库，脚本在 agent 本机）。
