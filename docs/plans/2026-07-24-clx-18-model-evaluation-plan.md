# CLX 18 模型（S0000～S0017）回测结果评价方案

日期：2026-07-24。执行者：Devin（用户委托）。

## 目标

基于已完成并已揭示 HOLDOUT 的 CLX 回测 run `01KBYC7REC0V3RY99634853AAB`（semantic-recovery child run，`.codex/memory/clx-preholdout-handoff.md`），对 `S0000`～`S0017` 共 18 个模型给出可复核的评价结论，并落盘最终报告。

## 数据来源与访问边界

- 唯一数据源：VM `fqcompare@192.168.77.10` 上的派生库 `freshquant_clx_backtest`，经临时只读网关（host `127.0.0.1:18098`）的 `/api/clx-backtest` 只读端点读取。
- 只使用 `GET` 端点（rankings / model-heatmap / combos/&lt;id&gt; / metrics / quality / manifest）；不调用 `start` / `freeze` / `reveal`，不触发第二次 HOLDOUT 揭示（该 run 已 `REVEALED, reveal_count=1`，查询属于合法揭示后读取）。
- 不改写任何 artifact、Mongo 文档或 ledger。

## 评价框架

1. 分层：事件研究层（信号预测力）与组合撮合层（真实撮合盈亏）分开评价，互不替代。
2. 门槛先行：TRAIN 段样本量 / 密度 / 年度覆盖 / BH-FDR 已由平台在候选生成时执行；本评价不重做筛选，只解读冻结结果。
3. 选优真值：VALIDATION 冻结排行（27 个冻结组合）是唯一合法排序依据；HOLDOUT 只用于评估样本外一致性与衰减，禁止用 HOLDOUT 反向重筛。
4. 维度下钻：模型 × 方向 × 主触发 ×发生次数；用 `model_heatmap`（24 个 model×trigger 单元）观察模型内部触发差异。
5. 独立根去重：`S0008/S0013/S0014` 记一个独立根，`S0016/S0017` 记一个独立根；评价结论按独立根汇总，避免派生模型互相"佐证"。

## 指标口径（默认 horizon=5 交易日，另查 1/3/10/20 稳健性）

- 事件研究：样本数、可执行数、均值/中位收益、胜率、95% 置信区间、方向归一化 MFE/MAE、信号密度、年度正收益比例、最差年度、FDR q 值。
- 组合撮合：总收益/年化、Sharpe、最大回撤、成交数、费用、受阻原因（`portfolio_summaries`，27×TRAIN/VALIDATION + HOLDOUT）。

## 判定标准

- 有效：VALIDATION 显著（CI 不含 0、q 值达标）且 HOLDOUT 方向一致、衰减可接受、年度稳定。
- 过拟合嫌疑：VALIDATION 靠前但 HOLDOUT 均值归零/反向。
- 不可评（UNRATED）：样本不足或未进入冻结组合的模型维度，只描述事实不下结论。

## 实施步骤

1. 拉取 run manifest、quality、freeze 状态，确认身份（manifest SHA：event `89676bcc…`、ranking `40554a30…`）。
2. 拉取 VALIDATION 与 HOLDOUT rankings（frozen 顺序）、TRAIN/VALIDATION/HOLDOUT combo_metrics（81 条）、model_heatmap、combo 定义与 portfolio_summaries（24 条）。
3. 按模型聚合：单模型组合直接归属；多模型组合按成员模型分别登记（标注非独占）。
4. 计算 VALIDATION→HOLDOUT 衰减（均值收益、胜率、组合年化、Sharpe）并按独立根汇总。
5. 落盘最终报告：`docs/plans/2026-07-24-clx-18-model-evaluation-report.md`，含每模型结论表、下钻发现、披露与限制。

## 披露与限制

- RAW 撮合口径不含分红送转现金流；`CORPORATE_ACTION_NOT_FULLY_LEDGERED` 区间为研究近似。
- HOLDOUT 区间 2024-01-02～2026-07-21，仅一段样本外；结论不构成实盘保证。
- 本评价为只读研究分析，不属于 formal deploy，也不改变 run 的冻结/揭示状态。
