# 仓位管理页面布局后续优化设计

## 目标

继续收口 `/position-management` 的首屏密度与右栏表格稳定性，解决以下三个确认问题：

1. “最近决策与上下文”当前默认只显示约 11 行，底部仍留有明显空白。
2. “当前命中规则”虽然已经卡片化，但仍占用一个偏大的独立区域，没有贴齐其他小指标卡的尺寸。
3. “券商仓位 / 推断仓位 / stock_fills仓位”三列位于右栏表格中段且使用弹性宽度，长来源文本会打乱整行节奏。

## 已确认事实

- [PositionManagement.vue](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/PositionManagement.vue) 当前把“最近决策与上下文”表体高度固定为 `11` 行左右：
  - `--position-decision-ledger-row-height: 40px`
  - `max-height: calc(var(--position-decision-ledger-row-height) * 11 + 2px)`
- “当前命中规则”当前仍以单独的 `position-rule-card` 占据 `position-state-grid--compact` 的第一列，网格模板是三列：
  - `minmax(256px, 0.96fr) minmax(0, 1fr) minmax(0, 1fr)`
- 右栏“单标的仓位上限覆盖”当前列顺序为：
  - `标的 / 券商仓位 / 推断仓位 / stock_fills仓位 / 系统默认值 / 单标的上限设置 / 当前来源 / 一致性 / 门禁 / 操作`
- 右栏后三列仓位当前使用两列弹性宽列，来源文本会优先吃掉中段宽度，导致主要操作列和门禁信息的节奏不稳定。

## 方案选择

### 方案 A：继续保留现有列顺序，只再放大三列仓位宽度

- 优点：改动最小。
- 缺点：根因没变，长来源文本仍在表格中段；只是把“乱”往后推，不能保证后续数据不再挤压其他列。

### 方案 B：把三列仓位挪到“操作”后面，并改成固定宽度列

- 优点：把“编辑与门禁”这一组主流程列稳定在前半段，三列高噪声信息统一放到尾部，表格节奏稳定。
- 缺点：需要同步调整表头、行模板、测试和文档。

### 方案 C：三列仓位折叠成一个复合列

- 优点：最省宽度。
- 缺点：会降低可扫描性，也偏离用户已经习惯的三列视图。

## 推荐方案

采用方案 B，并配合首屏密度调整：

1. “最近决策与上下文”保持分页 `100/页`，但把默认可视行数提升到约 `15` 行，直接吃掉当前底部空白。
2. “当前命中规则”并入与“可用保证金”相同尺寸的指标卡网格，保留三段信息：
   - 标题
   - 主值
   - 一行压缩说明
3. 右栏表格改成以下顺序：
   - `标的 / 系统默认值 / 单标的上限设置 / 当前来源 / 一致性 / 门禁 / 操作 / 券商仓位 / 推断仓位 / stock_fills仓位`
4. 三列仓位都改成固定宽度，内部统一使用两层结构：
   - 第一行：`数量 / 市值`
   - 第二行：来源文本，超长截断并保留 tooltip

## 实施影响

### 前端

- `morningglory/fqwebui/src/views/PositionManagement.vue`
- `morningglory/fqwebui/src/views/position-management.test.mjs`

### 文档

- `docs/current/modules/position-management.md`

## 验收标准

1. “最近决策与上下文”首屏默认可见行数明显增加，底部空白被收掉。
2. “当前命中规则”卡片尺寸与“可用保证金”等小卡一致，并落在指标卡网格内。
3. 右栏表格的“券商仓位 / 推断仓位 / stock_fills仓位”三列移动到“操作”列后面。
4. 三列仓位为固定宽度，来源文本不再扰乱主列排版。
5. `node --test morningglory/fqwebui/src/views/position-management.test.mjs` 通过。
6. `npm run build` 通过。
