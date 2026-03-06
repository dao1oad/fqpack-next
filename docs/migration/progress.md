# 迁移进度（progress）

> 记录粒度：以 RFC 为单位。每个 RFC 通过评审后才能进入编码状态。

## 更新规则（强制）

- RFC 状态任意变更时（Draft / Review / Approved / Implementing / Done / Blocked），必须在同一提交更新本表。
- 任何涉及迁移、重构、删改功能的合并到 `main`，必须在同一提交更新本表。
- 处于 Implementing 状态的 RFC，按 Asia/Shanghai 自然日每天至少更新一次。

## 状态说明

- Draft：起草中
- Review：评审中
- Approved：已通过，可开始编码
- Implementing：编码中
- Done：完成并合并
- Blocked：阻塞中

## 进度总表

| RFC | 主题 | 状态 | 负责人 | 更新时间 | 旧分支来源（路径/能力） | 备注 |
|---:|---|---|---|---|---|---|
| 0001 | Docker 并行部署（端口隔离） | Done | TBD | 2026-03-06 | N/A（部署形态） | `docker/compose.parallel.yaml` 与部署文档已落地，覆盖 Web UI / API / TDXHQ / Dagster / Redis / MongoDB。 |
| 0002 | ETF 前复权（qfq）因子同步与查询默认 qfq | Done | TBD | 2026-03-05 | 旧链路缺少 ETF `xdxr/adj` | 新增 `etf_xdxr/etf_adj`，Dagster 同步与查询侧默认应用 qfq 已完成。 |
| 0003 | XTData Producer/Consumer + fullcalc（替代轮询） | Done | TBD | 2026-03-06 | `D:\fqpack\freshquant\freshquant\market_data\xtdata\market_producer.py` / `strategy_consumer.py` / `morningglory\fqcopilot\fullcalc\*` | Producer / Consumer / fullcalc / Guardian(event) 骨架与关键语义已完成。 |
| 0004 | Windows PowerShell UTF-8 中文显示（cat/type 不乱码） | Done | TBD | 2026-03-05 | N/A（开发体验） | 新增 `script/pwsh_utf8.ps1`，补充 `docs/agent` 与 `README.md` 提示。 |
| 0005 | KlineSlim MVP（5m 主图 + 30m 缠论叠加） | Done | Codex | 2026-03-06 | `D:\fqpack\freshquant\morningglory\fqwebui\src\views\KlineSlim.vue` / `src\views\js\kline-slim.js` / `src\views\js\draw-slim.js` / `freshquant\rear\stock\routes.py` | 方案 A 已落地并完成联调：不使用 WebSocket，前端采用 HTTP 轮询并避免闪屏；后端 `/api/stock_data` 增加了 **opt-in** 的 Redis-first 实时读取（仅 `realtimeCache=1` 时启用，避免影响旧页面字段契约）；`KlineSlim` 在无 `endDate` 的实时模式下默认携带该参数，历史模式不携带。默认展示 `5m` K 线并叠加 `30m` 缠论结构。RFC、设计稿、实施计划、breaking-changes 与测试说明已同步补充该语义。 |
