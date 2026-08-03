# CLX 市场上下文评价 — 2026-08-03（gap-complete v2）

## 运行边界

- 正式批次：`clx-2026-08-03-production_v1-f15383ad1c6b6495`
- strict run：`2026-08-03-market-cleanroom-gap-complete-v2`
- frontend run：`2026-08-03-group-eval-f15383ad1c6b6495-complete-v2`
- as-of：`2026-08-03T15:00:00+08:00`
- Phase A：clean-room；restricted_inputs_accessed=false

## 冻结市场状态

- 全市场：Stock 5,534；ETF 1,617；成交样本 7,142
- 主状态：中小盘广泛修复
- 产业主线：电力—核电—风电及设备链
- 次线：航空航天
- 否定假设：半导体与高端电子延续
- 冻结核心：10；CLX pure-buy 命中 1；核心漏检账 9

## 正式 CLX 勾稽

- 去重证券：394（Stock 300 / ETF 94）
- pure buy：162；pure sell：228；mixed：4
- official unique signal events：769（Stock 574 / ETF 195）
- retired direction-expanded diagnostic memberships：785
- ETF/LOF exposure：94/94 mapped；79 个全批次唯一 exposure；pure-buy 13 个去重确认

## Stock buy 分组与基本面

- Stock pure-buy：143
- 业务 primary group：143/143
- remaining unmapped：0
- 分组：13
- 冻结主题映射：11
- shortlist：6
- 2026Q1 财报覆盖：143/143
- fundamental evidence gap：0
- 组内排序字段：主题暴露、基本面质量、成长、盈利、现金流/负债、估值、风险、流动性容量、独立信号家族、formal rank、symbol

## ETF 与 sell

- ETF buy diagnostics：19
- ETF eligible confirmation：13
- unknown ETF buy：0
- sell/mixed diagnostics：232

## 验证

- market-state schema：passed
- isolation audit：passed
- CLX input schema：passed
- evaluation schema：passed
- cross-artifact validation：passed
- frontend dynamic count/group/mapping/fundamental/ETF/event reconciliation：passed

## 仍保留的市场复盘边界

- 全市场分钟行情仅由涨停池时间字段局部覆盖。
- 跌停池取得总数，明细为空。
- 本次为单日横截面，生命周期保持 `not_located`。
- 这些边界仅影响日内先后和跨日生命周期，不影响本轮 143/143 业务分组、2026Q1 基本面排序、ETF exposure mapping 或 769 事件勾稽。
