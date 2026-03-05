# RFC 0002: ETF 前复权(qfq)因子同步（TDX xdxr → etf_adj）与查询默认 qfq

- **状态**：Done
- **负责人**：TBD
- **评审人**：User
- **创建日期**：2026-03-05
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

当前系统中：

- 股票链路已具备“默认前复权(qfq)”能力：Dagster 同步 `stock_xdxr` 并生成 `stock_adj`，查询侧通过 `QA_fetch_stock_*_adv(...).to_qfq()` 应用因子。
- ETF 链路缺少“除权/复权因子”同步：Dagster 仅同步 `etf_list → etf_day/etf_min`，ETF K 线查询 `freshquant/quote/etf.py` 返回的是 bfq 数据（Index DataStruct 无 `.to_qfq()`）。

因此 `get_data_v2()` 在 ETF 标的上无法提供与股票一致的前复权 K 线，尤其在 ETF 拆分/合并（TDX xdxr `category=11`）场景会出现价格跳变。

同时，Docker Linux 环境无法直接使用宿主机 Windows 的 `xtquant/xtdata` 二进制（`.pyd`），不适合作为除权数据源。TDX/pytdx 已验证可提供 ETF xdxr 字段，可用于推导前复权因子。

## 2. 目标（Goals）

- 新增 ETF 的除权事件同步与前复权因子生成：
  - 同步 `etf_xdxr`（审计/可重算）
  - 生成 `etf_adj`（qfq 因子）
- 修改 ETF K 线查询链路，使其默认返回 qfq（不新增开关），与股票保持一致：
  - `queryEtfCandleSticks*` 返回的 OHLC 为 qfq
  - `get_data_v2()` 在股票与 ETF 标的上均可正常前复权读取 K 线
- 提供“历史补全 + 每日增量更新”的 Dagster 资产链路与验证步骤。

## 3. 非目标（Non-Goals）

- 不引入 `xtdata` 作为依赖（避免 Docker/宿主机耦合）。
- 不实现后复权(hfq)。
- 不改动股票复权逻辑与既有集合（`stock_xdxr/stock_adj`）。
- 不对指数/债券等其它标的复权做扩展。

## 4. 范围（Scope）

**In Scope**

- 新增 MongoDB 集合：`quantaxis.etf_xdxr`、`quantaxis.etf_adj`
- 新增 Dagster 资产：`etf_xdxr`、`etf_adj`（并纳入 `etf_data_job` 下游依赖）
- 修改 `freshquant/quote/etf.py`：查询默认应用 `etf_adj` 前复权因子（qfq）
- 单元测试（纯 pandas）：验证“因子计算 + 应用”逻辑
- 手工验证脚本/步骤：验证 `512000` 拆分点与 `get_data_v2()` 行为

**Out of Scope**

- xtdata-proxy / 任何宿主机 Windows 二进制透传到 Docker 的方案
- ETF 之外的其它品种复权扩展

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- 以 TDX/pytdx 的 xdxr 信息为源，生成 ETF qfq 因子，写入 `etf_adj`
- 支持 xdxr 的 `category=1`（除权除息）与 `category=11`（扩缩股）两类事件
- 查询侧默认返回 qfq，并在 `etf_adj` 缺失时回退 bfq + warning 日志

**不负责（Must Not）**

- 不依赖 xtdata（不要求在 Docker 内可 import Windows `.pyd`）
- 不修改现有 ETF K 线存储结构（仍存于 `index_day/index_min`）

**依赖（Depends On）**

- MongoDB（`quantaxis` 库）
- `pytdx`（TDX xdxr 拉取）
- 现有 ETF 日线同步（`index_day`）

**禁止依赖（Must Not Depend On）**

- `xtquant/xtdata`（宿主机 Windows 二进制）

## 6. 对外接口（Public API）

本 RFC 不新增函数签名或参数，但有行为变化：

- `freshquant/quote/etf.py:queryEtfCandleSticks*`：从“默认 bfq”变为“默认 qfq”
- `freshquant/chanlun_service.py:get_data_v2()`：ETF 标的返回的 K 线为 qfq（与股票一致）

错误语义：

- 若缺少 `etf_adj` 数据：返回 bfq（`adj=1` 等价），并记录 warning（不抛异常中断）。

## 7. 数据与配置（Data / Config）

**MongoDB（quantaxis 库）**

- `etf_xdxr`
  - 索引：唯一 `('code','date')`
  - 字段：`code(str,6位)`, `date(str,YYYY-MM-DD)`, `category(int)`, `fenhong(float)`, `peigu(float)`, `peigujia(float)`, `songzhuangu(float)`, `suogu(float)`, ...
- `etf_adj`
  - 索引：唯一 `('code','date')`
  - 字段：`code(str,6位)`, `date(str,YYYY-MM-DD)`, `adj(float)`

**配置**

- 复用现有 Dynaconf（`FRESHQUANT_MONGODB__HOST/PORT` 等）；不新增配置项。

## 8. 破坏性变更（Breaking Changes）

是。ETF 的 K 线查询从 bfq 变为 qfq，可能影响依赖“原始价格”的下游逻辑。

- 影响面：任何消费 `queryEtfCandleSticks*` / `get_data_v2()` 的策略、可视化与回测结果
- 迁移步骤：若需 bfq，请直接查询底层 `index_day/index_min` 原始数据（或在本次变更回滚前保留旧行为分支）
- 回滚方案：回滚本 RFC 对 `freshquant/quote/etf.py` 的 qfq 应用逻辑，并停止 `etf_adj` 的生成/使用

## 9. 迁移映射（From `D:\\fqpack\\freshquant`）

本能力属于当前仓库对“ETF 默认前复权”缺口的补齐，与旧仓库无直接 1:1 路径迁移。参考对齐点：

- 股票侧参考：`QUANTAXIS.QASU.save_tdx.QA_SU_save_stock_xdxr` 生成 `stock_adj`

## 10. 测试与验收（Acceptance Criteria）

- [x] `quantaxis.etf_xdxr`、`quantaxis.etf_adj` 集合创建并具备唯一索引
- [x] Dagster `etf_data_job` 物化后，`etf_adj` 对 ETF 有数据（至少覆盖 `512000`）
- [x] `512000` 在 `2025-08-04` 拆分点，qfq 后 OHLC 基本连续（不出现 2x 跳变）
- [x] `get_data_v2('sh600000','1d')` 与 `get_data_v2('sh512000','1d')` 均返回可用 qfq K 线
- [x] 单测：对 “category=1 分红” 与 “category=11 拆分” 两类事件的 adj 计算与应用通过

## 11. 风险与回滚（Risks / Rollback）

- 风险：TDX 网络波动/限流导致 xdxr 拉取失败  
  - 缓解：重试、降低并发、失败回退为“仅更新已有数据”
- 风险：首次全量重算耗时较长  
  - 缓解：限制 `max_concurrent_runs=1`（已存在），必要时拆分为 backfill + daily
- 回滚：停止/移除 `etf_adj` 应用逻辑，恢复 ETF 查询返回 bfq

## 12. 里程碑与拆分（Milestones）

- M1：RFC 通过（本 RFC）
- M2：实现 `etf_xdxr/etf_adj` 资产 + ETF 查询默认 qfq + 单测
- M3：Docker/Dagster 手工验证与上线，登记 breaking changes
