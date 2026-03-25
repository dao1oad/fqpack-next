# Runtime Observability Dense Ledger Follow-up Design

## 目标

把 [`morningglory/fqwebui/src/views/RuntimeObservability.vue`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/RuntimeObservability.vue) 的 runtime-observability 页面继续向高密度工作台推进，解决三个明确问题：

- 全局 Trace 主表里，`节点路径` 需要拿到最大的横向展示空间。
- 右侧当前选中节点详情仍然带有卡片式头块和分段样式，不够紧凑。
- 打开 `异常节点` 模式后，在中间 Trace 列表切换不同链路，右侧详情看起来没有变化。

页面必须满足：

- 全局 Trace 主表继续以 dense ledger 为主，不退回 feed card。
- 浏览器 `1920x1080 / 100%` 下，不依赖浏览器主滚动条浏览右侧详情。
- `异常节点` 模式下切换 Trace，右侧步骤与节点详情必须立即切换到新链路。

## 当前实现事实

- 全局 Trace 主表当前使用 [`RuntimeObservability.vue`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/RuntimeObservability.vue) 中的 `runtime-trace-ledger__grid`，列顺序是：
  - `最近时间`
  - `标的`
  - `链路类型`
  - `链路状态`
  - `信号备注`
  - `节点路径`
  - `节点数`
  - `总耗时`
  - `断裂原因`
- 当前 `标的` 列宽约为 `minmax(220px, 1.1fr)`，`信号备注` 约为 `minmax(180px, 0.95fr)`，`节点路径` 是 `minmax(480px, 3.1fr)`，但后三列仍然和它并列抢宽。
- 右侧 `步骤` tab 当前由上方 `trace-step-ledger` 和下方 `step-inspector` 组成。`step-inspector` 内部仍保留：
  - 状态头块
  - tag/chip
  - 多段分区
  这些元素会增加垂直占用。
- `selectedTraceDetail` 当前由：
  - `selectedTrace`
  - `selectedTracePayload`
  - `traceSteps`
  合成。
- 切换 Trace 时，`handleTraceClick()` 只更新 `selectedTrace`，但只有在“同一 trace 且无 payload”时才主动 `loadTraceDetail()`；切到新 trace 时不会先清理旧 `selectedTracePayload/traceSteps`，因此右侧详情会被旧链路数据短暂甚至持续覆盖。
- `异常节点` 模式只过滤 `filteredSteps = filterTraceSteps(selectedTraceDetail.steps, { onlyIssues })`。一旦 `selectedTraceDetail` 被旧 payload 覆盖，看上去就像“切换链路没有变化”。

## 设计原则

### 1. 节点路径优先于辅助统计列

全局 Trace 主表的主要任务是展示链路过程，而不是统计摘要。`节点数 / 总耗时 / 断裂原因` 仍然保留，但它们不应抢占 `节点路径` 的主可视空间。

### 2. 页面级不滚动，面板级滚动

延续 runtime-observability 当前布局约束：

- 页面壳不承担主滚动。
- 中间 ledger 需要横向查看时，只在中间 panel 内出现横向滚动。
- 右侧详情过长时，只在右侧 detail panel 内出现纵向滚动。

### 3. 选中节点详情彻底表格化

右侧 `步骤` tab 的“当前选中节点详情”改成以 key-value ledger 为主的高密度表格展示：

- 不再用状态卡片头强化视觉层级。
- 不再用独立 chip 块承载主要信息。
- 信息分组仍保留，但统一用紧凑表头 + 表格体表达。

### 4. 选择态必须和链路切换强一致

只要用户在中间 Trace 主表切到新链路，右侧详情必须立即进入“新链路”上下文：

- 旧步骤缓存不能继续渲染。
- 慢请求不能把后点开的链路覆盖回旧链路。
- `异常节点`、`首个异常`、`上下异常` 导航都必须以当前链路为准。

## 信息架构调整

## 中间全局 Trace

主表仍然保留 9 列，但分成两段语义：

- 固定高频列：
  - `最近时间`
  - `标的`
  - `链路类型`
  - `链路状态`
  - `信号备注`
- 主展示列 + 次要统计列：
  - `节点路径`
  - `节点数`
  - `总耗时`
  - `断裂原因`

具体布局：

- `标的` 列宽缩到当前约 60%。
- `信号备注` 列宽缩到当前约 60%。
- `节点路径` 扩为唯一主弹性列。
- `节点数 / 总耗时 / 断裂原因` 继续保留在最右侧，但通过中间 panel 的横向滚动查看。

结果是：

- 默认可见区域优先给 `节点路径`。
- 链路很长时用户滚动中间 panel 横向滚动条，而不是压缩所有列。

## 右侧步骤详情

`步骤` tab 改成双层 dense ledger：

- 上半部分：步骤列表 `trace-step-ledger`
- 下半部分：当前选中节点详情 `trace-step-detail-ledger`

下半部分按以下分区渲染，但统一采用表格式：

- `基础字段`
  - 组件
  - 运行节点
  - 时间
  - 状态
  - 耗时
  - 标的
- `判断字段`
  - `decision_branch`
  - `decision_expr`
  - `reason_code`
  - `decision_outcome`
- `Guardian 上下文`
  - `signal_summary`
  - `decision_context`
  - 终结结论
- `异常信息`
  - `error_type`
  - `error_message`
- `原始 JSON`
  - `payload`
  - `metrics`

如果某一分区没有有效字段，则整块不渲染。

## 状态与请求流修复

切换 Trace 的正式流程改为：

1. 识别是否切到了新的 `trace_key`
2. 若是新 Trace：
   - 先 `resetSelectedTraceDetailState()`
   - 再更新 `selectedTrace`
   - 再异步拉取新 detail
3. `loadTraceDetail()` 使用请求 token / 目标 trace key 防止响应乱序覆盖
4. `selectedStep` 在新链路步骤到达前保持为空；步骤到达后重新从当前链路的可见步骤中选默认节点

这样在 `异常节点` 模式下：

- 中间列表切换 Trace 后，右侧会先清空旧节点详情。
- 新链路步骤一到位，右侧立即进入新链路的首个异常节点。

## 数据整形方案

继续复用 [`morningglory/fqwebui/src/views/runtimeObservability.mjs`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/runtimeObservability.mjs) 作为 view-model 层：

- 扩展 `buildTraceLedgerRows()` 输出更适合滚动主列的字段。
- 新增或扩展“当前选中节点详情行” helper，把 step 数据转成多个 dense table rows。
- 保留 `buildTraceStepLedgerRows()` 作为上半部分步骤列表 schema。

[`RuntimeObservability.vue`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/RuntimeObservability.vue) 负责：

- 调整 Trace 主表 grid
- 增加中间 panel 横向滚动容器
- 把 `step-inspector` 改成紧凑表格布局
- 修正 Trace 切换时的状态 reset 和异步覆盖

后端接口不变；这次问题完全是前端布局和状态流问题，不需要扩 API。

## 测试与验收

### 自动化测试

需要更新 [`morningglory/fqwebui/src/views/runtime-observability.test.mjs`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/runtime-observability.test.mjs)：

- 断言 Trace 主表 grid 改为“压缩标的 / 备注 + 扩大节点路径 + 横向滚动容器”
- 断言右侧 `步骤` 详情不再依赖旧 `step-inspector-head` 卡片样式
- 断言切换 Trace 时会先 reset detail state，再加载新链路 detail
- 断言 `异常节点` 模式下切换 Trace，右侧步骤列表和默认选中节点会切到新链路

### 人工验收

在浏览器 `1920x1080 / 100%` 下：

- 中间主表能明显看到 `节点路径` 比当前更长
- `标的` 与 `信号备注` 视宽缩小
- 过长链路可通过中间 panel 横向滚动查看 `节点数 / 总耗时 / 断裂原因`
- 右侧 `步骤` 页没有卡片式详情头块，只保留高密度表格
- 右侧 detail panel 自己滚动，不出现页面主滚动条
- 开启 `异常节点` 后，在中间主表切换不同 Trace，右侧步骤和节点详情都跟着变

## 非目标

- 不改 `/api/runtime/*` 协议
- 不改 Guardian 节点 hover 的上下文字段
- 不重做 `摘要 / 原始数据` tab 的信息架构
- 不改组件 Event 主表结构
