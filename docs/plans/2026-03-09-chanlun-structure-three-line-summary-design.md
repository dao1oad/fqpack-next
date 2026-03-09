# KlineSlim 缠论结构三行摘要设计

## 背景

当前 `KlineSlim` 的缠论结构面板会分别展示 `高级段 / 段 / 笔` 三个区块，每个区块使用多格摘要网格展示基础字段；其中 `高级段` 与 `段` 下方还会继续渲染中枢表格。这种展示信息完整，但在日常盯盘时占用空间较大，阅读路径也偏重。

本次目标是将该面板压缩为只保留三条摘要行，保留少量标签样式，但移除网格和中枢表格，使其更接近“快速扫读”的信息条。

## 目标

- 将缠论结构面板收敛为 `高级段 / 段 / 笔` 三条摘要。
- 保留少量标签样式，避免退化为纯文本大串。
- 不修改后端接口与 fullcalc 结构提取逻辑。
- `笔` 的统计指标改为展示“当前这一笔包含几根 K 线”。

## 非目标

- 不新增或修改 `/api/stock_data_chanlun_structure` 返回字段。
- 不保留任何中枢表格。
- 不调整 KlineSlim 图表、侧栏、轮询、按钮行为。
- 不触碰 `freshquant/` 后端实现。

## 当前事实

- 结构面板由 `morningglory/fqwebui/src/views/KlineSlim.vue` 渲染。
- 交互与格式化函数位于 `morningglory/fqwebui/src/views/js/kline-slim.js`。
- 后端已提供 `higher_segment / segment / bi` 的基础字段，包括 `direction`、`price_change_pct`、`start_idx`、`end_idx`、`start_time/start_price`、`end_time/end_price`，并为 `高级段/段` 提供现成计数字段。

## 方案选择

### 方案 A：仅在模板里内联拼接

- 直接在 `KlineSlim.vue` 中把网格替换为三行摘要。
- `笔` 的 K 线数在模板表达式中计算。

优点：
- 改动最小。

缺点：
- 模板会承载较多拼接和条件逻辑，可读性差。

### 方案 B：前端先整理摘要 view-model，再由模板渲染

- 在 `kline-slim.js` 中统一生成三个摘要对象。
- 模板只负责输出标题和标签行。
- `笔` 的 K 线数在前端脚本中统一计算。

优点：
- 模板干净，展示逻辑集中。
- 更容易通过文件级前端测试锁定。

缺点：
- 比纯模板替换多一层前端整理逻辑。

### 方案 C：后端返回展示文案

- 接口直接返回三条展示文本。

优点：
- 前端最薄。

缺点：
- 将 UI 文案耦合进 API，超出本次需求。

**结论：采用方案 B。**

## 最终设计

### 1. 展示结构

缠论结构面板仅保留三个 section：

- `高级段`
- `段`
- `笔`

每个 section 内只渲染一条摘要行，不再渲染现有 `chanlun-summary-grid` 与中枢表格。

### 2. 行内字段顺序

- `高级段`：方向，价格比例，包含段数，中枢数，起始时间(起始价格)，终点时间(终点价格)
- `段`：方向，价格比例，包含笔数，中枢数，起始时间(起始价格)，终点时间(终点价格)
- `笔`：方向，价格比例，K线数，起始时间(起始价格)，终点时间(终点价格)

### 3. 视觉语义

- 保留当前半透明面板与 section 标题。
- 摘要内容改为单行 `inline tag` 风格。
- 每个字段采用“标签名 + 值”的轻量形式，例如：
  - `方向 上`
  - `价格比例 12.34%`
  - `包含段数 3`
  - `起始 2026-03-07 10:30 (12.45)`

### 4. K线数规则

`笔` 的 K 线数在前端计算：

- 当 `start_idx` 和 `end_idx` 都为合法数字时，显示 `end_idx - start_idx + 1`
- 任一索引缺失或非法时，显示 `--`

### 5. 空态规则

某一级结构缺失时，不显示空标签行，直接显示原有空态：

- `暂无已完成高级段`
- `暂无已完成段`
- `暂无已完成笔`

## 改动边界

只修改前端展示层：

- `morningglory/fqwebui/src/views/KlineSlim.vue`
- `morningglory/fqwebui/src/views/js/kline-slim.js`
- `morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs`

明确不动：

- `/api/stock_data_chanlun_structure`
- `freshquant/chanlun_structure_service.py`
- 任何迁移台账与 breaking-changes 文档

## 验收标准

- 打开 `/kline-slim` 的缠论结构面板，只看到 `高级段 / 段 / 笔` 三条摘要。
- 不再看到任何中枢表格。
- `高级段 / 段 / 笔` 的空态仍正常显示。
- `笔` 能展示按索引计算出的 `K线数`。
- 前端文件级测试能锁定新展示关键字，并确认旧表格表头已移除。
