# 破坏性变更清单（Breaking Changes）

> 任何破坏性变更落地时必须追加记录，并引用对应 RFC。

## 记录模板

- **日期**：YYYY-MM-DD
- **RFC**：NNNN-<topic>
- **变更**：做了什么不兼容的变化
- **影响面**：哪些模块/脚本/用户会受影响
- **迁移步骤**：如何升级（包含命令/配置修改）
- **回滚方案**：如何撤回

## 变更记录

- **日期**：2026-03-05
- **RFC**：0002-etf-qfq-adj-sync
- **变更**：ETF K 线查询默认从 `bfq` 切换为 `qfq`（通过新增 `quantaxis.etf_xdxr/etf_adj` 并在查询侧应用复权因子）。
- **影响面**：依赖 `freshquant/quote/etf.py:queryEtfCandleSticks*` 或 `freshquant/chanlun_service.py:get_data_v2()` 的策略/回测/可视化结果可能变化。
- **迁移步骤**：如需 `bfq`，请直接读取底层原始集合 `quantaxis.index_day/index_min`（或回滚本变更）。
- **回滚方案**：移除 ETF 查询侧对 `etf_adj` 的应用逻辑，并停用/移除 `etf_xdxr/etf_adj` 同步资产。
