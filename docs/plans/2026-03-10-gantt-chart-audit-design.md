# 甘特图配置与颜色映射审计设计

**目标**：审计 `GanttHistory.vue` 相对 legacy `XgbHistoryGantt.vue` 的图表配置与配色差异，给出一版只覆盖图表层的对齐设计；不恢复搜索抽屉，不恢复“加入近期涨停池”，不扩展到其它页面或运行链。

## 1. 范围与假设

- In：配色、legend、tooltip、zoom/pan、hover、高亮、reset viewport、板块侧栏与图表同步。
- Out：搜索 drawer、近期涨停池 action、页面路由/父组件协议、API 扩展、其它页面。
- 假设：
  - 继续使用当前 `GanttHistory.vue` 的 props / emits / API（`getGanttPlates`、`getGanttStocks`）。
  - 板块 tooltip 保留当前 `reason_map` / `reason_text` 能力；这是当前实现新增信息，不属于回退对象。
  - 本次不引入新入口，也不改公共 API；无需新增 RFC。

## 2. 审计结论

| 维度 | 当前实现 | Legacy 参考 | 影响 |
| --- | --- | --- | --- |
| 配色语义 | plate 按 `rank/hotCount` 五色，stock 按 `streak/isLimit` 五色 | 按“第几次连板 + 当前第几天”的四组渐变色 | 颜色从“连板阶段”变成“当天指标”，语义漂移 |
| Legend | 无 | 四档 legend | 用户无法直接理解颜色含义 |
| Tooltip | 保留 `reason_text`，但无 streak 文案和位置限位 | 有 streak 文案、位置限位、热门标的截断 | 当前内容更丰富，但边缘位置与长列表体验更弱 |
| Zoom / Pan | 基础 inside + slider | wheel/move 配置更完整，且 stock 视图有标签区拖拽兜底 | 个股视图在 y 轴标签区拖拽时平移失效 |
| Hover | 仅 `mouseover/globalout` | `axisPointer` 阴影 + `updateAxisPointer` + emphasis | 行高亮和侧栏联动明显弱化 |
| 侧栏同步 | 永远显示全量板块列表 | 仅显示 y 轴当前可视窗口 | 侧栏与 viewport 脱节 |
| Reset | 逻辑接近 legacy | 同样回到最新/顶部，并带防御式处理与侧栏重算 | 竞态场景更脆弱，reset 后联动不完整 |

## 3. 方案选项

### 方案 A（推荐）：交互对齐 + 当前数据增强保留

- 恢复 legacy 的颜色语义、legend、axisPointer、zoom/pan、侧栏同步与 stock drag-pan fallback。
- 保留当前 `reason_text`、当前 props / emits、当前“仅链接”的简化侧栏。
- 覆盖本 issue 全部范围，且不会把已明确砍掉的功能带回来。

### 方案 B：最小视觉补丁

- 只补 legend、palette、tooltip 定位。
- 代码改动最小，但 zoom/pan/hover 回归仍然存在，不满足本次审计范围。

### 方案 C：完整抽离 chart config helper

- 将 palette、tooltip、viewport、hover 计算全部模块化。
- 最利于长期维护与测试，但对本次单组件对齐来说偏重，Phase 2 不建议作为主目标。

## 4. 推荐设计

### 4.1 颜色与 legend

- 恢复 legacy 的四档 `streakPalettes`，颜色语义回到“第几次连板 + 当前第几天”。
- 在 plate / stock 两种视图都显示同一套 legend：`首次连板 / 第二次连板 / 第三次连板 / 第四次连板+`。
- 不恢复 legacy 的 `ST/其他` y 轴重排；本次只对齐颜色和交互，避免额外顺序语义变更。

### 4.2 数据整形

- 在渲染前重新计算 streak metadata，至少补出 `color`、`streakOrder`、`streakDay`，替换当前 `buildPlateColor` / `buildStockColor` 的单日指标配色。
- plate 模式继续保留当前 `reason_text`，stock 模式继续保留当前标的理由。
- 当 API 缺少必要字段时，退回中性色，不引入新的报错路径。

### 4.3 Tooltip

- 保留当前 plate tooltip 的 `板块理由` 与 `热门标的` 信息。
- 补回 legacy 的 `streakText` 与 `position` 限位逻辑，避免 tooltip 覆盖 hover 区域或贴边溢出。
- 热门标的最多展示前 10 项并附总数；若当前返回的是字符串数组，则按原值展示。

### 4.4 Zoom / Pan / Hover

- `dataZoom` 对齐 legacy：inside zoom 支持 wheel + drag move，slider 补回 filler/border 配置。
- 恢复 stock 视图的 DOM 级 drag-pan fallback，仅在 grid 外侧的 y 轴标签区域启用。
- 恢复 `axisPointer` 行阴影、series emphasis 边框，以及 `updateAxisPointer + mouseover + globalout` 的 hover 同步。
- plate 侧栏继续保持“仅链接、无加入按钮”，但列表内容改为跟随 y 轴当前可视窗口，而不是永久显示全量数据。

### 4.5 Reset Viewport

- 继续沿用“回到最新/顶部”的窗口跨度保持逻辑。
- 补回 legacy 的 `getOption` / `dispatchAction` 防御式处理，并在 reset 后立即同步侧栏可视窗口。

## 5. 验收标准

- plate / stock 两种视图都显示 legend，且颜色与连板阶段一致。
- tooltip 在边缘位置不溢出，plate tooltip 同时包含 streak 信息和当前 reason 信息。
- 个股视图可在 y 轴标签区域拖拽平移；plate 侧栏会跟随 y 轴缩放窗口变化。
- hover 时行高亮、侧栏高亮和 tooltip 日期保持同步；移出图表后清理高亮。
- reset 后 x 轴回到最右侧、y 轴回到顶部可视窗口，且不因 dispose 竞态报错。

## 6. Human Review 决策点

- 是否接受“恢复 legacy 连板语义配色”，替换当前 rank / hotCount 配色。
- 是否接受“保留当前 reason tooltip 内容 + 补回 legacy 交互”，而不是完全回退 tooltip 文案。
- 是否接受“侧栏仅保留链接，但恢复 viewport 同步”，不恢复近期涨停池操作。
