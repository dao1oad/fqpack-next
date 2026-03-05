# ETF 前复权(qfq)数据同步与查询设计

**目标**：让 `get_data_v2()` 在 **股票**与 **ETF** 标的上都能“默认前复权(qfq)读取 K 线”，且与股票现有逻辑保持一致（无新增开关）。

## 1. 现状（代码与数据）

- Dagster：
  - `stock_data_schedule` 下游包含 `stock_xdxr`（`QA_SU_save_stock_xdxr("tdx")`），会同步 `stock_xdxr` 并生成 `stock_adj`。
  - `etf_data_schedule` 仅同步 `etf_list → etf_day/etf_min`，**未同步 ETF 的除权(xdxr)/复权因子(adj)**。
- 存储：
  - ETF 日线/分钟线通过 QUANTAXIS 保存到 `quantaxis.index_day / quantaxis.index_min`（ETF 被当作“指数”数据保存）。
- 查询链路：
  - 股票：`freshquant/data/stock.py` 中 `QA_fetch_stock_*_adv(...).to_qfq()` → 依赖 `stock_adj`，因此股票默认 qfq 成立。
  - ETF：`freshquant/quote/etf.py` 使用 `QA_fetch_index_*_adv(...).data`（Index DataStruct 无 `.to_qfq()`），因此 ETF 默认仍是 bfq。

## 2. 关键结论（数据源与可行性）

- Docker Linux 容器内无法直接使用宿主机 Windows 的 `xtquant/xtdata` 二进制（`.pyd`），因此不依赖 xtdata。
- TDX/pytdx 能返回 ETF 的除权信息（`get_xdxr_info`），并可验证：
  - `512000` 在 `2025-08-04` 有 `category=11`（扩缩股）且 `suogu=2.0`，用于拆分复权。
  - `510050` 等 ETF 存在 `category=1`（现金分红）事件，字段语义可复用股票公式。

## 3. 设计决策（与股票一致）

### 3.1 新增集合

在 `MongoDB: quantaxis` 库新增：

- `etf_xdxr`：ETF 除权/拆分事件明细（可审计、可重算）。
  - 关键字段：`code(6位)`, `date(YYYY-MM-DD)`, `category`, `fenhong`, `peigu`, `peigujia`, `songzhuangu`, `suogu`, ...
  - 索引：唯一 `('code','date')`
- `etf_adj`：ETF 前复权因子（qfq），用于查询时乘到 OHLC。
  - 关键字段：`code(6位)`, `date(YYYY-MM-DD)`, `adj(float)`
  - 索引：唯一 `('code','date')`

> 约定：`code` 始终存 6 位数字（如 `512000`），与 `index_day/index_min` 以及 `stock_adj` 的 join 方式一致。

### 3.2 复权因子计算口径

对每个 ETF code：

1) 从 `index_day` 获取 bfq 日线序列（按 `date` 升序）。
2) 基于事件计算 `preclose`：
   - `category=1`（除权除息）：复用股票口径
     `preclose = (prev_close*10 - fenhong + peigu*peigujia) / (10 + peigu + songzhuangu)`
   - `category=11`（扩缩股）：拆分/合并
     `preclose = preclose / suogu`（`suogu!=0` 时生效）
3) 生成 qfq 因子（与股票一致、锚定最新交易日）：
   `adj = (preclose.shift(-1) / close).fillna(1)[::-1].cumprod()`

### 3.3 Dagster 同步（历史补全 + 每日增量）

新增资产依赖链：

`etf_list` → `etf_day` → `etf_xdxr` → `etf_adj`

- 历史补全：首次物化 `etf_data_job` 时，补全 `index_day/index_min` 历史后，生成 `etf_xdxr/etf_adj` 全量数据。
- 每日更新：16:00 后触发（已有 `etf_data_schedule`），执行增量写入日线/分钟线，并对 `etf_xdxr/etf_adj` 做“全量覆盖式重算”（确保 qfq 锚定最新日，保持绝对正确）。

### 3.4 ETF K 线查询默认 qfq（无开关）

修改 `freshquant/quote/etf.py`：

- `queryEtfCandleSticksDay/Min` 返回前，按 `date` join `etf_adj`，并对 `open/high/low/close` 乘 `adj`。
- 若 `etf_adj` 缺失：回退 bfq 返回，并 `warning` 日志（避免接口报错）。

## 4. 验证点（手工 + 自动化）

- 数据正确性（重点）：`512000` 的 `2025-08-04` 拆分点，qfq 后应基本连续（不出现 2 倍跳变）。
- 行为一致性：`get_data_v2('sh600000','1d')` 与 `get_data_v2('sh512000','1d')` 均返回 qfq K 线。
- 自动化测试：对“adj 计算 + OHLC 应用”做纯 pandas 单测（避免 CI 依赖 TDX 网络）。
