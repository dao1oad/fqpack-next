# Shouban30 Extra Filter Snapshot Repair Design

## 背景

`/gantt/shouban30` 页面已经接入三类额外筛选：

- `融资标的`
- `均线附近`
- `优质标的`

页面前端只消费 `/api/gantt/shouban30/stocks` 返回的快照字段，再在本地做交集过滤。

当前并行环境中，`freshquant_gantt.shouban30_stocks` 的最新快照仍然缺少：

- `is_credit_subject`
- `credit_subject_snapshot_ready`
- `near_long_term_ma_passed`
- `is_quality_subject`
- `quality_subject_snapshot_ready`

因此三个按钮一旦开启，前端会把所有行都过滤掉。

## 现状结论

问题不是前端按钮逻辑，而是后端快照和重建判定：

1. `shouban30_stocks` 还是 RFC 0027 之前的旧 schema。
2. Dagster 只用 `shouban30_plates` 的 `stock_window_days + chanlun_filter_version` 判断“最新快照是否已完成”，没有检查 `shouban30_stocks` 是否已经带上 0027 的额外筛选字段。
3. `quality_stock_universe.load_quality_stock_lookup()` 对真实 PyMongo `Collection` 使用了布尔判断，实际会抛 `NotImplementedError`，会阻断按新代码重建 `quality` 快照字段。

## 目标

- 让 Dagster 能识别“只有缠论字段、没有额外筛选字段”的旧 `shouban30` 快照，并触发最新交易日重建。
- 修复 `quality_stock_universe` 在真实 PyMongo 环境下的读取 bug。
- 保持 `/api/gantt/shouban30/plates|stocks` 路由和页面交互不变。
- 用自动化测试覆盖这次退化路径，避免后续再次出现“页面代码已上线，但最新快照未重建”的问题。

## 非目标

- 不修改前端筛选交互。
- 不为 `quality` 空基础表引入兜底命中逻辑。
- 不调整“均线附近”的业务口径。
- 不新增公开 API。

## 方案对比

### 方案 A：仅修前端，字段缺失时视为“未启用筛选”

优点：

- 改动小。

缺点：

- 只是掩盖旧快照问题。
- 后端真实数据模型继续失真。
- 页面和 RFC 0027 的盘后快照语义不一致。

不采用。

### 方案 B：引入显式 `snapshot_schema_version`

优点：

- 长期最清晰。
- 后续 schema 升级更容易判定。

缺点：

- 会扩展 `plates/stocks` schema。
- 需要额外迁移和测试改动。
- 对当前问题属于过度设计。

这次不采用。

### 方案 C：最小修复现有 schema 判定

做法：

- 继续沿用现有 `chanlun_filter_version`。
- 在 Dagster 的 legacy 判定里补充检查最新 `shouban30_stocks` 是否存在 RFC 0027 关键字段。
- 修复 `quality_stock_universe` 的 PyMongo 兼容性问题。

优点：

- 直接修复当前线上问题。
- 不改变接口契约。
- 改动面最小，便于快速验证。

缺点：

- 仍然基于“字段存在性”做旧快照判定，不如显式 schema version 干净。

本次采用方案 C。

## 设计

### 1. Legacy 快照判定扩展

修改 `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`：

- 保留当前对 `shouban30_plates` 的检查。
- 增加对 `shouban30_stocks` 的检查：
  - 若最新交易日没有任一 `stocks` 文档，视为 legacy。
  - 若存在缺失 RFC 0027 关键字段的文档，视为 legacy。

关键字段采用最小集合：

- `is_credit_subject`
- `credit_subject_snapshot_ready`
- `near_long_term_ma_passed`
- `is_quality_subject`
- `quality_subject_snapshot_ready`

这些字段即便值为 `false` 或 `null` 也算合法，只要求字段存在。

### 2. 质量名单读取修复

修改 `freshquant/data/quality_stock_universe.py`：

- 把 `target_collection = target_collection or ...` 改成显式 `is None` 判断。

这样 `load_quality_stock_lookup(target_collection=DBfreshquant[...])` 在真实 PyMongo 下不会触发 `Collection.__bool__` 异常。

### 3. 验证口径

修复后预期分三层验证：

1. 单元测试证明：
   - 旧 `stocks` schema 会被识别成 legacy。
   - 带新字段的 `stocks` schema 不会被误判。
   - `load_quality_stock_lookup()` 可读取真实 collection-like 对象。
2. 重建最新交易日 `2026-03-09` 的四档窗口后：
   - `credit` 相关字段应出现，且应有非零命中。
   - `quality` 相关字段应出现，但若 `quantaxis.stock_block` 仍为空，则应表现为 `quality_subject_snapshot_ready=false`。
   - `near_long_term_ma_*` 字段应出现，是否命中由日线数据链路决定。
3. API `/api/gantt/shouban30/stocks` 返回字段存在，页面按钮不再因“字段缺失”而全空。

## 测试策略

后端新增和修改的测试聚焦三类：

- `freshquant/tests/test_quality_stock_universe.py`
  - 覆盖显式传入 collection 时不再触发布尔判断异常。
- `freshquant/tests/test_gantt_dagster_ops.py`
  - 覆盖 `_has_legacy_shouban30_snapshot()` 对旧 `stocks` schema 的判定。
- `freshquant/tests/test_gantt_readmodel.py` 或相邻测试
  - 如需要，补一条真实字段存在性的保护测试。

验证命令：

- `py -3.12 -m pytest freshquant/tests/test_quality_stock_universe.py freshquant/tests/test_gantt_dagster_ops.py freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py -q`
- `node --test morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs morningglory/fqwebui/src/views/shouban30StockFilters.test.mjs`

## 风险

- `quality` 结果可能仍为空。
  - 这是当前 `quantaxis.stock_block` 空表导致的数据现状，不是这次修复的逻辑回归。
- `near_long_term_ma` 可能重建后仍然全为 `false`。
  - 若发生，说明 1d 取数链路还存在独立问题，需要单独排查。

## 落地顺序

1. 先写失败测试。
2. 再最小修复 `quality_stock_universe` 和 Dagster legacy 判定。
3. 跑后端测试。
4. 在并行 Mongo 上重建 `2026-03-09` 的 `shouban30` 四档快照。
5. 查库和调 API 验证字段分布。
