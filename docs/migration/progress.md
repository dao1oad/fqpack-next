# 迁移进度（progress）

> 记录粒度：以 RFC 为单位。每个 RFC 通过评审后才能进入编码状态。

## 更新规则（强制）

- RFC 状态任意变更时（Draft/Review/Approved/Implementing/Done/Blocked），必须在**同一提交**更新本表。
- 任何涉及迁移/重构/删改功能的合并到 `main`，必须在**同一提交**更新本表。
- 处于 Implementing 状态的 RFC，按 Asia/Shanghai 自然日 **每天至少更新一次**（可只写“无进展 + 原因”）。

## 状态说明

- Draft：起草中
- Review：评审中
- Approved：已通过，可开始编码
- Implementing：编码中（必须已 Approved）
- Done：完成并合并
- Blocked：阻塞（写清原因）

## 进度总表

| RFC | 主题 | 状态 | 负责人 | 更新时间 | 旧分支来源（路径/能力） | 备注 |
|---:|------|------|--------|----------|--------------------------|------|
| 0001 | Docker 并行部署（端口隔离） | Done | TBD | 2026-03-06 | N/A（部署形态） | `docker/compose.parallel.yaml` + 部署文档；覆盖 Web UI/API/TDXHQ/Dagster UI+daemon/Redis/Mongo/QAWebServer；修复 tdxhq `len(int)` 导致的 500；Web UI Nginx 增加 Docker DNS 动态解析避免 502；stock_data_job 排除 cjsd_data + 关闭 cjsd_data eager auto-materialize（避免数据同步触发 CJSD） |
| 0002 | ETF 前复权(qfq)因子同步（TDX xdxr → etf_adj）与查询默认 qfq | Done | TBD | 2026-03-05 | 现状缺口补齐（ETF 无 xdxr/adj） | 新增 `etf_xdxr/etf_adj`，Dagster 补历史+每日更新；ETF 查询链路默认应用 qfq，与股票一致（无开关）；容器内已验证 `512000` 拆分与 `510050` 分红连续性，`get_data_v2()` 股票/ETF 日线&分钟均可 qfq 读取 |
| 0003 | XTData Producer/Consumer + fullcalc（替代轮询） | Implementing | TBD | 2026-03-06 | `D:\fqpack\freshquant\freshquant\market_data\xtdata\market_producer.py` / `strategy_consumer.py` / `morningglory\fqcopilot\fullcalc\*` | Producer/Consumer/fullcalc/Guardian(event) 已落地骨架与关键语义（prewarm/backfill/qfq/积压只算最新）；待补充端到端运行验收与部署说明 |
| 0004 | Windows PowerShell UTF-8 中文显示（cat/type 不乱码） | Done | TBD | 2026-03-05 | N/A（开发体验） | 新增 `script/pwsh_utf8.ps1`；`docs/agent` 与 `README.md` 增加提示；dot-source 后 `cat/type` 默认按 UTF-8 读取 |
