# Quality Stock 21-Board Fallback Design

## 背景

`/gantt/shouban30` 的 `优质标的` 依赖 `freshquant.quality_stock_universe`，而它当前从 `quantaxis.stock_block` 提取 `QUALITY_STOCK_BLOCK_NAMES` 对应板块。

现状问题已经明确：

- 运行中的 Dagster 仍在用 QUANTAXIS 的 `QA_SU_save_stock_block("tdx")`，失败时会先清空 `stock_block`
- 远端 `QA_fetch_get_stock_block('tdx'/'tushare')` 当前不稳定，导致 `stock_block` 可以长期为 `0`
- 我们临时用宿主机 `D:\new_tdx` 恢复过 `quality_stock_universe`，但只通过旧读取口径命中了 `18/21`

进一步排查后发现：

- `D:\new_tdx\T0002\hq_cache\infoharbor_block.dat` 已经包含完整 `21` 个优质板块
- 缺失的 `上证50 / 沪深300 / 中证央企` 就在该文件里
- 当前 `QUALITY_STOCK_BLOCK_NAMES` 中写的是 `“中证央企”`，而本地 TDX 实际板块名是 `中证央企`

因此，本轮修复不需要引入新的外部数据源，核心是把本机 TDX 的 `infoharbor_block.dat` 正式接入 `stock_block` 日更，并处理少量板块名别名。

## 目标

- 将本机 TDX `infoharbor_block.dat` 接入 `stock_block` 的正式 fallback
- 让 `quality_stock_universe` 在远端 block 源失效时，仍能稳定恢复到完整 `21/21` 板块
- 保持 `quality_stock_universe -> shouban30` 现有日更链路不变
- 让 Dagster 每日盘后可稳定刷新 `优质标的`，不再依赖手工导库

## 非目标

- 不重构 Dagster 资产图
- 不改 `shouban30` 前端筛选逻辑
- 不扩展 `QUALITY_STOCK_BLOCK_NAMES` 的业务范围
- 不解决 Docker 宿主机 `27027` 端口代理异常
- 不把远端 `QA_fetch_get_stock_block` 的问题作为本轮前置条件

## 方案对比

### 方案 A：继续依赖远端 `QA_fetch_get_stock_block`

优点：

- 代码最少

缺点：

- 当前环境已证实远端源不可靠
- 无法保证每日 `quality_stock_universe` 非空

不采用。

### 方案 B：仅在 `quality_stock_universe` 里直接读本机 TDX

优点：

- 可以快速恢复 `优质标的`

缺点：

- `stock_block` 与 `quality_stock_universe` 会长期双轨
- 其他依赖 `stock_block` 的链路仍然没有稳定上游

不采用。

### 方案 C：在 `stock_block` 安全刷新中正式加入 `infoharbor_block.dat` fallback

做法：

- 在 `market_data.py` 中新增本机 TDX `infoharbor_block.dat` 解析 helper
- 将其作为 `stock_block` 的一个稳定来源写入 `quantaxis.stock_block`
- `refresh_quality_stock_universe()` 保持从 `stock_block` 读取
- 为 `中证央企 -> “中证央企”` 增加规范化映射

优点：

- 与现有数据流一致
- 能把临时修复提升为正式日更能力
- 不需要新外部依赖

缺点：

- 需要补一层本地文件解析与板块名标准化

本次采用方案 C。

## 设计

### 1. `stock_block` 新增本机 TDX `infoharbor_block` 来源

在 [`morningglory/fqdagster/src/fqdagster/defs/assets/market_data.py`](../../morningglory/fqdagster/src/fqdagster/defs/assets/market_data.py) 中增加内部 helper：

- `_parse_tdx_infoharbor_block_text(text: str) -> list[dict]`
- `_load_local_tdx_infoharbor_docs(log) -> list[dict]`

解析规则：

- 读取 `D:\new_tdx\T0002\hq_cache\infoharbor_block.dat`
- 按 `gbk` 解码
- 识别形如 `#FG_活跃ETF,...`、`#ZS_沪深300,...` 的块头
- 后续 `0#000001,1#600000,...` 形式的 code 行归入当前板块
- 生成 `{code, blockname, source}` 文档

本地来源标记为：

- `source = "tdx_infoharbor"`

写入策略沿用安全刷新语义：

- 先收集来源文档
- 成功来源按 `source` 定向替换
- 全部来源失败时保持旧集合不动

### 2. `quality_stock_universe` 增加板块名标准化

在 [`freshquant/data/quality_stock_universe.py`](../../freshquant/data/quality_stock_universe.py) 中增加轻量标准化：

- `中证央企` 统一映射为 `“中证央企”`

这样不需要修改 RFC 0027 中既有的 `QUALITY_STOCK_BLOCK_NAMES` 常量，也不需要强行改写远端或本地原始 block 文档。

### 3. 日更链路保持不变

保持当前链路：

- `stock_data_job` 刷新 `stock_block`
- `job_gantt_postclose` 执行 `refresh_quality_stock_universe()`
- 随后构建 `shouban30`

修复后的关键差异是：

- 即使远端 block 源继续失败，本机 TDX `infoharbor_block.dat` 仍可为 `quality_stock_universe` 提供完整 `21/21` 板块候选

## 测试策略

### 1. `stock_block` fallback 解析测试

在 `freshquant/tests/test_market_data_assets.py` 新增：

- `test_parse_tdx_infoharbor_block_text_parses_quality_blocks`
- `test_refresh_stock_block_prefers_local_infoharbor_when_remote_sources_fail`

覆盖：

- `#FG_ / #ZS_` 头与多行 code 列表解析
- `tdx_infoharbor` 在远端源失败时仍能写入 `stock_block`

### 2. `quality_stock_universe` 标准化测试

在 `freshquant/tests/test_quality_stock_universe.py` 新增：

- `test_refresh_quality_stock_universe_normalizes_infoharbor_aliases`

覆盖：

- `blockname = "中证央企"` 时，产出 `block_names = ["“中证央企”"]`

### 3. 运行态验证

验证目标：

- `quantaxis.stock_block` 非空
- `freshquant.quality_stock_universe` 含完整 `21` 个目标板块
- `source_version` 回到正式版本，不再依赖手工 `18of21` 临时包
- `shouban30` 的 `is_quality_subject` 保持非零命中

## 风险

- 宿主机本地 TDX 路径可能在不同机器不同，需要保留现有路径探测或兼容多个候选路径
- `infoharbor_block.dat` 文件格式若未来变化，解析器需要容错
- 运行中的 Docker Dagster 容器当前还是旧代码，必须在部署后才会真正生效

## 落地顺序

1. 先写解析与标准化失败测试
2. 实现 `infoharbor_block.dat` 解析和 `quality` 板块名标准化
3. 跑聚焦回归
4. 在运行容器中验证 `stock_block -> quality_stock_universe -> shouban30`
