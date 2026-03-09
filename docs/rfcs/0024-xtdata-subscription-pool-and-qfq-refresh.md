# RFC 0024：XTData 订阅池收敛、前复权语义统一与盘前参考数据刷新

- **状态**：Approved
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-09
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题

当前目标仓存在两组语义债务：

1. `freshquant.market_data.xtdata.market_producer` 会把 `load_monitor_codes()` 与 `active_tpsl_codes` 做并集订阅，但当前业务约束已经明确为“`monitor_codes` 覆盖 `active_tpsl_codes`”，因此 Producer 额外感知 TPSL universe 属于职责污染。
2. 股票与 ETF 的 qfq 路径不一致：
   - 股票：历史直接 `to_qfq()`，realtime/回填在写库前乘因子。
   - ETF：历史与 realtime 先按 raw 拼接，再在读路径统一应用 `etf_adj`。
   这导致 `stock_realtime` 与 `index_realtime` 的价格语义不一致，系统只能靠路径约定记忆“哪些数据已经复权”。

同时，`stock_adj/etf_adj` 当前由 TDX/pytdx 盘后链路生成，是历史 authoritative source，但它天然覆盖不到“除权日当天盘前/盘中需要以当日为锚点读取 qfq”的场景。XTData 又能在盘前提供 `front/raw` 对照，但不能直接混写进 realtime 集合，否则会形成“部分 raw、部分 qfq”的错误数据集。

此外，宿主机当前已经存在 `credit_subjects.worker` 这类盘前参考数据任务，但“盘前除权覆盖刷新”没有被纳入同一运维管理面。

## 2. 目标

- Producer 只订阅 `load_monitor_codes(...)` 的结果。
- `stock_realtime` 与 `index_realtime` 统一改为只存 `raw/bfq`。
- 股票与 ETF 的 qfq 语义统一为：
  - 历史 raw/bfq
  - realtime raw/bfq
  - merge / dedupe / sort
  - 应用 base `stock_adj / etf_adj`
  - 若存在当日 intraday override，再应用一次覆盖修正
- 保留 TDX/pytdx 盘后 `stock_adj/etf_adj` 作为历史 authoritative source。
- 新增宿主机 `adj_refresh_worker`，在盘前生成当日 `stock_adj_intraday / etf_adj_intraday`。
- 将 `credit_subjects.worker` 与 `adj_refresh_worker` 纳入同一个 supervisor `reference-data` 组管理，但保持两个独立任务。

## 3. 非目标

- 不用 XTData `front` 直接替代 `stock_adj/etf_adj` 的历史 authoritative source。
- 不把 XTData `front` K 线直接写入 `stock_realtime / index_realtime`。
- 不修改 `monitor.xtdata.max_symbols` 的现有限额语义。
- 不新增新的 HTTP API。
- 不重构 Dagster 的 `stock_xdxr / etf_xdxr / stock_adj / etf_adj` 盘后资产图。

## 4. 范围

### In Scope

- `freshquant.market_data.xtdata.market_producer`
- `freshquant.market_data.xtdata.strategy_consumer`
- `freshquant.data.stock`
- `freshquant.quote.etf`
- 新增 `freshquant.data.adj_intraday`
- 新增宿主机 `freshquant.market_data.xtdata.adj_refresh_service`
- 新增宿主机 `freshquant.market_data.xtdata.adj_refresh_worker`
- supervisor 模板、实盘运维文档、迁移记录

### Out of Scope

- 将盘后 Dagster 任务整体迁移到宿主机
- 用 XTData 重建历史 `stock_xdxr / etf_xdxr`
- 改动 Guardian/TPSL 的业务判定规则

## 5. 模块边界

### 负责

- `market_producer.py`
  - 只负责按 mode 订阅监控池
  - 不再感知 TPSL universe
- `strategy_consumer.py`
  - realtime 落库统一为 raw/bfq
  - fullcalc 输入窗口统一由“拼接后一次 qfq”生成
- `stock_adj/etf_adj`
  - 继续作为盘后历史 qfq authoritative source
- `stock_adj_intraday/etf_adj_intraday`
  - 只负责当前交易日锚点覆盖
- `adj_refresh_worker`
  - 只负责盘前生成 intraday override
- `credit_subjects.worker`
  - 继续只负责融资标的同步

### 不负责

- realtime 集合不得保存混合语义数据
- `adj_refresh_worker` 不直接写 qfq K 线
- `credit_subjects.worker` 不承载除权刷新逻辑

## 6. 依赖与集成点

- RFC 0002：ETF qfq 因子同步
- RFC 0003：XTData Producer/Consumer + fullcalc
- RFC 0020：信用账户融资标的同步 worker
- MiniQMT / XTData / XTQuant 宿主机运行环境
- TDX/pytdx 盘后 `stock_adj/etf_adj`

## 7. Public API

本 RFC 不新增 HTTP API，但新增一个宿主机 worker 入口：

```powershell
python -m freshquant.market_data.xtdata.adj_refresh_worker
python -m freshquant.market_data.xtdata.adj_refresh_worker --once
```

默认语义：

- 启动后先执行一次
- 常驻模式下默认每天 `09:20 Asia/Shanghai` 再执行一次

错误语义：

- 单票 base adj 缺失或 XTData `front/raw` 对照缺失时，跳过该票并继续处理其他标的
- 不向 realtime 集合写入混合语义数据

## 8. 数据与配置

### 8.1 存储

保留：

- `quantaxis.stock_adj`
- `quantaxis.etf_adj`
- `quantaxis.stock_xdxr`
- `quantaxis.etf_xdxr`

新增：

- `quantaxis.stock_adj_intraday`
- `quantaxis.etf_adj_intraday`

### 8.2 intraday override 最小 schema

- `code`：前缀代码，如 `sz000001`
- `trade_date`：当前交易日，`YYYY-MM-DD`
- `base_anchor_date`：本地 base adj 的锚点日期
- `anchor_scale`：将 base adj 重新映射到当前交易日锚点的缩放系数
- `source`：固定为 `xtdata_front_raw`
- `updated_at`

### 8.3 读取语义

- 当窗口不包含当前交易日时，只使用 base `stock_adj / etf_adj`
- 当窗口包含当前交易日且存在 override 时：
  - 当前交易日 bars 视为 `adj=1`
  - 更早 bars 在 base adj 基础上再乘 `anchor_scale`
- override 缺失时回退到 base adj，不写入混合语义数据

### 8.4 部署

supervisor 新增：

- `fqnext_xtdata_adj_refresh_worker`
- `group:fqnext_reference_data`

## 9. 破坏性变更

### 9.1 realtime 语义变更

- `stock_realtime` 从“股票可能已 qfq”调整为“统一 raw/bfq”
- `index_realtime` 保持 raw/bfq，但与股票链路统一到同一读取语义

迁移步骤：

1. 停止宿主机 `market_producer / strategy_consumer`
2. 部署新代码
3. 清理或重建当天 `stock_realtime / index_realtime`
4. 重启 Producer / Consumer / API

### 9.2 Producer 订阅池语义变更

- 从“`monitor_codes ∪ active_tpsl_codes`”调整为“只订阅 `monitor_codes`”

迁移步骤：

1. 部署新代码
2. 重启 `market_producer`
3. 确认 `load_monitor_codes()` 已覆盖全部业务标的

## 10. 测试与验收

- [x] Producer 单测：只使用 `load_monitor_codes()`，不再并入 TPSL 池
- [x] Consumer 单测：股票 realtime 写库回到 raw
- [x] Consumer 单测：股票 raw realtime 与历史 raw 在读路径只做一次 qfq
- [x] Helper 单测：intraday override 存在时，历史 bars 重缩放、当前交易日 bars 保持 raw
- [x] Helper 单测：override 缺失时回退到 base adj
- [x] Worker/Service 单测：按 `front/raw` 对照计算 `anchor_scale` 并写入 `stock_adj_intraday / etf_adj_intraday`
- [x] Worker/Service 单测：默认调度为 `09:20`
- [x] supervisor 模板新增 `fqnext_reference_data`

## 11. 迁移映射

- `D:\fqpack\freshquant\freshquant\market_data\xtdata\market_producer.py`
  - 旧：并入 TPSL 活跃标的
  - 新：目标仓 `market_producer.py` 收敛为 monitor-only
- `D:\fqpack\freshquant\freshquant\data\stock.py`
  - 旧：历史 qfq + realtime qfq 拼接
  - 新：raw + merge + single qfq
- `D:\fqpack\freshquant\freshquant\quote\etf.py`
  - 旧：ETF 独立 merge-first qfq
  - 新：与股票共享同一 helper
- `D:\fqpack\freshquant\freshquant\strategy\toolkit\sync_xtquant.py`
  - 旧：宿主机参考数据任务分散
  - 新：通过 `reference-data` 组统一托管 `credit_subjects.worker` 与 `adj_refresh_worker`
