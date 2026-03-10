# Stock Block Safe Refresh Design

## 背景

`/gantt/shouban30` 的 `优质标的` 依赖 `freshquant.quality_stock_universe`，而该集合又直接从 `quantaxis.stock_block` 提取指定板块名单。

当前目标仓库的 Dagster asset [`market_data.py`](D:/fqpack/freshquant-2026.2.23/morningglory/fqdagster/src/fqdagster/defs/assets/market_data.py) 仍直接调用 `QA_SU_save_stock_block("tdx")`。这条链路有一个已知问题：

- QUANTAXIS 的 `QA_SU_save_stock_block` 在失败路径上可能先清空 `stock_block`，再吞掉异常。

当前并行环境中：

- `quantaxis.stock_block` 为 `0` 条
- `freshquant.quality_stock_universe` 为 `0` 条

因此 `优质标的` 现在必然全空。

## 现状结论

问题核心不是 `quality_stock_universe` 的筛选名单定义，而是更底层的 `stock_block` 刷新语义：

1. 旧仓库已经有 `_save_stock_block_safe()`，会先拉取各来源数据，再按来源增量替换，且在“所有来源都失败/为空”时保留旧库。
2. 目标仓库的 asset 还没有迁这段安全刷新逻辑。
3. `quality_stock_universe` 当前使用的板块种子名单与旧仓库 `complex_screening_xgt.yaml` / `complex_screening_*` 中的“获取热门板块股票”阶段一致，不是主要矛盾。

## 目标

- 把旧仓库 `stock_block` 的“全源失败不清库”语义迁到目标仓库。
- 保持目标仓库 Dagster asset 名称、依赖关系、返回值和调度入口不变。
- 为 `quality_stock_universe` 恢复稳定上游数据源。
- 用测试覆盖这次回归路径，避免以后再次出现“板块库被清空，优质标的全空”。

## 非目标

- 不重构 Dagster asset 体系。
- 不改 `quality_stock_universe` 的板块名单定义。
- 不把旧仓库的整个 `market_data.py` 大段迁入目标仓库。
- 不引入新外部依赖。
- 本轮不处理 `stock_block` 历史补数，只关注安全刷新语义。

## 方案对比

### 方案 A：继续使用 `QA_SU_save_stock_block("tdx")`

优点：

- 零代码改动。

缺点：

- 无法防止刷新失败时把 `stock_block` 清空。
- 已经被当前环境证实会导致 `quality_stock_universe` 长时间为空。

不采用。

### 方案 B：完整迁移旧仓库 `market_data.py` 的相关片段

优点：

- 与旧仓库实现最接近。

缺点：

- 会把大量与本问题无关的辅助函数一起带进来。
- 对当前目标仓库的 asset 文件来说改动面过大。

这次不采用。

### 方案 C：在目标仓库 asset 文件内最小迁移安全刷新核心语义

做法：

- 在 [`market_data.py`](D:/fqpack/freshquant-2026.2.23/morningglory/fqdagster/src/fqdagster/defs/assets/market_data.py) 内增加内部 helper：
  - 拉取 `tdx` / `tushare` 的 block 数据
  - 成功来源按 `source` 定向替换
  - 全源失败或全为空时不改现有集合
- `stock_block` asset 继续保留原函数签名和返回值，只把内部调用从 `QA_SU_save_stock_block("tdx")` 改成安全 helper。

优点：

- 改动面最小。
- 足够修复当前 `stock_block` 被清空的问题。
- 对现有 Dagster 资产图无破坏。

缺点：

- 本次先不迁本地 TDX 行业映射增强逻辑，只保留 `QA_fetch_get_stock_block` 远端来源。

本次采用方案 C。

## 设计

### 1. 安全刷新语义

新增内部刷新 helper，语义如下：

- 使用 `QA_fetch_get_stock_block("tdx")` 和 `QA_fetch_get_stock_block("tushare")` 分别取数
- 每个来源独立处理：
  - 拉取失败：记 warning，跳过该来源
  - 返回空 dataframe：记 warning，跳过该来源
  - 转 json 失败：记 warning，跳过该来源
  - 成功：为文档补 `source` 字段
- 若所有来源都失败/为空：
  - 只记 warning
  - 不执行 `delete_many`
  - 不执行 `insert_many`
  - 保留现有 `stock_block`
- 若部分来源成功：
  - 只删除这些成功来源的旧数据
  - 只写回这些成功来源的新数据
  - 未成功来源的旧数据保留

### 2. 集合约束

仍使用 `quantaxis.stock_block`，并确保：

- 维持 `code` 索引
- 新写入文档都带 `source`

这保证后续 `quality_stock_universe` 可以继续按 `blockname` 查询，不需要改它自己的读写逻辑。

### 3. 与优质标的的关系

`quality_stock_universe` 的逻辑保持不变，仍在 [quality_stock_universe.py](D:/fqpack/freshquant-2026.2.23/.worktrees/fix-shouban30-extra-filter-snapshot/freshquant/data/quality_stock_universe.py) 中：

- 从 `stock_block` 读取 `QUALITY_STOCK_BLOCK_NAMES`
- 归并到 `freshquant.quality_stock_universe`

因此本轮修复成功的标志是：

1. `stock_block` 刷新不会再把旧数据清空
2. 一旦任一来源恢复有效返回，`quality_stock_universe` 就能恢复非空
3. 重建 `shouban30` 后 `is_quality_subject` 会出现非零命中

## 测试策略

新增聚焦单元测试，不跑完整 Dagster：

- `freshquant/tests/test_market_data_assets.py`

覆盖两条关键行为：

1. 当所有来源都失败/为空时：
   - 旧 `stock_block` 文档保留
   - 不发生删除
   - 不发生插入
2. 当一个来源成功、另一个来源失败时：
   - 仅成功来源被替换
   - 失败来源旧数据保留
   - 新文档自动补 `source`

验证命令：

- `py -3.12 -m pytest freshquant/tests/test_market_data_assets.py -q`
- `py -3.12 -m pytest freshquant/tests/test_quality_stock_universe.py freshquant/tests/test_gantt_dagster_ops.py freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py -q`

## 风险

- 即使修完安全刷新，当前远端 `QA_fetch_get_stock_block` 仍可能暂时取不到数据。
  - 但这时至少不会再把旧库清空。
- `quality_stock_universe` 何时恢复非空，仍取决于至少一个来源成功返回指定板块数据。
- 本轮不迁本地 TDX 行业映射增强，若远端来源长期不稳定，后续可能还需要继续迁那部分逻辑。

## 落地顺序

1. 先写失败测试，锁住安全刷新语义。
2. 在目标仓库 asset 文件里最小实现安全 helper。
3. 跑聚焦测试和相关回归。
4. 用真实并行环境尝试刷新 `quality_stock_universe` 并核对结果。
