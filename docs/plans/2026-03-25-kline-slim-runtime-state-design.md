# Kline Slim 运行态展示设计

## 背景

`kline-slim` 的 `画线编辑` 面板当前已经把价格保存和配置开关拆开，但运行态只在 Guardian 区块头部展示了最近命中信息，三层运行态没有直接暴露，用户无法快速判断哪一层已经被系统打掉。

同时，Guardian 区块中的 `命中价` 文案容易被理解成当前编辑价格，而它实际表示最近一次真实命中的运行价。

## 目标

- 在 `Guardian 倍量价格` 和 `止盈价格` 两个区块中，都显示三层只读运行态
- 保留当前价格输入与配置开关交互，不允许用户直接编辑运行态
- 把 Guardian 的 `命中价` 改为 `最近命中价`
- 当 Guardian 从未命中过时，摘要明确显示 `最近命中 未命中`

## 方案

### 推荐方案

- 区块头部继续显示配置开关汇总
- 头部摘要增加运行态汇总：
  - Guardian：`运行态 X/3`
  - 止盈：`运行态 X/3`
- Guardian 摘要：
  - `最近命中 <level>` 在有 `last_hit_level` 时显示
  - `最近命中 未命中` 在没有 `last_hit_level` 时显示
  - `最近命中价 <price>` 仅在 `last_hit_price` 非空时显示
- 每一层行内增加只读运行态标签：
  - Guardian：`运行态 激活` / `运行态 未激活`
  - 止盈：`运行态 已布防` / `运行态 未布防`

### 不采用的方案

- 只显示区块级汇总，不显示每层运行态：信息不足，仍需要用户猜哪一层被打掉
- 单独再加一个只读状态表：信息完整，但会明显拉高面板高度

## 数据语义

- Guardian 行内运行态来源于 `guardianState.buy_active`
- Guardian 最近命中来源于 `guardianState.last_hit_level` / `guardianState.last_hit_price`
- 止盈行内运行态来源于 `takeprofitState.armed_levels`
- 配置开关与运行态继续分离：
  - 配置开关：`buy_enabled` / `manual_enabled`
  - 运行态：`buy_active` / `armed_levels`

## 影响面

- 前端模板：`morningglory/fqwebui/src/views/KlineSlim.vue`
- 前端计算属性：`morningglory/fqwebui/src/views/js/kline-slim.js`
- 前端测试：`morningglory/fqwebui/src/views/klineSlim.test.mjs`
- 当前文档：`docs/current/modules/kline-webui.md`

## 测试策略

- 先补模板/脚本层失败测试，确认新文案和运行态字段未实现前会失败
- 再做最小实现，使测试转绿
- 最后跑现有相关前端测试与构建，确认无回归
