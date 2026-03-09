# KlineSlim Legend 与中枢残影修复设计

## 背景

当前目标仓 `KlineSlim` 已迁回四周期缠论图层，但图表仍有两个明显缺陷：

1. 周期 legend 开关没有按旧仓语义正常显示和工作。
2. 中枢 `markArea` 在切换主周期/标的时出现残影，旧矩形会持续留在画布上。

截图 `docs/temp/中枢显示异常.png` 显示的问题与当前实现一致：右侧存在大量未被清除的黄色中枢框。

## 根因

### 1. legend 开关缺失

当前 `morningglory/fqwebui/src/views/js/draw-slim.js` 只声明了：

- `legend.data = ['1m', '5m', '15m', '30m', '中枢', '段中枢']`

但没有像旧仓那样：

- 为周期组注册占位 series
- 为周期组与中枢组建立 group member 联动
- 用 legend handler 将组开关映射到成员线条/中枢

这导致当前 legend 只有文本声明，没有旧仓的“周期组”实体语义。

### 2. 中枢残影

当前 `drawSlim()` 接收了 `keepState`，但最终 `chart.setOption()` 仍固定使用：

- `notMerge: false`

这与 `kline-slim.js` 中“切换主周期/标的时将 `keepState` 设为 false”的意图不一致。  
结果是主周期切换时，ECharts 仍按 merge 模式处理 `markArea`，旧中枢图形没有被完整替换。

此外，当前跨周期中枢 remap 逻辑也比旧仓更弱：

- 只输出 `coord`
- 没有旧仓的 `xAxis / yAxis` 点位形式
- 没有旧仓对边界与零宽中枢的完整过滤

这会放大 merge 残影问题。

## 目标

- 恢复旧仓的周期 legend 分组显示与联动。
- 修复切换主周期/标的时的中枢残影。
- 保留当前仓已实现的四周期范围、懒加载与实时刷新策略。

## 非目标

- 不扩展到 `3m / 60m / 120m / 1d`。
- 不迁移 MACD、均线、信号标记等旧仓附加图层。
- 不改后端接口或 Redis 推送语义。

## 方案比较

### 方案 A：最小补丁

- 只在当前 renderer 里补几项 legend 配置
- 将 `notMerge` 改为 `!keepState`

优点：

- 改动最小

缺点：

- legend 仍缺少旧仓“周期组占位 series + 组联动”语义
- 中枢 remap 逻辑仍偏弱，容易留下边界问题

### 方案 B：恢复旧仓关键语义，裁剪为当前四周期版本

- 恢复周期组占位 series
- 恢复 legend 组联动
- 恢复旧仓中枢 remap 的 `xAxis / yAxis` 与边界过滤
- 在 `keepState=false` 时做结构性重绘

优点：

- 同时修 legend 和残影根因
- 与旧仓显示语义一致

缺点：

- 改动比最小补丁大，但仍局限在 renderer 和控制层

### 方案 C：整段替换为旧仓 `draw-slim.js`

优点：

- 对齐旧仓最快

缺点：

- 会重新带回当前明确不需要的能力，维护成本高

**结论：采用方案 B。**

## 最终设计

### 1. legend 分组

在 `draw-slim.js` 中为每个周期组创建占位 series：

- `1m`
- `5m`
- `15m`
- `30m`

同时保留全局组：

- `中枢`
- `段中枢`

每个周期组的成员包括：

- `笔`
- `段`
- `高级别段`
- `中枢`
- `段中枢`
- `高级段中枢`

点击周期组时，联动控制整组成员显隐。

### 2. 中枢 remap

将当前 `remapZhongshu()` 改成旧仓稳定语义：

- 输出 `xAxis / yAxis` 点位
- 终点落在主图最左边界之前的中枢直接过滤
- 起止映射到同一根 K 线的中枢直接过滤
- 保留最近点映射与边界 clamp

### 3. 结构性重绘

当 `keepState=false` 时：

- 先 `chart.clear()`
- 再 `setOption(..., { notMerge: true })`

当 `keepState=true` 时：

- 继续保留当前 legend/dataZoom 状态
- 但 `replaceMerge` 扩展为旧仓使用的结构性集合，避免旧图层残留

### 4. 测试策略

新增/扩展前端文件级与函数级测试，至少覆盖：

- 周期组 placeholder series 存在
- `drawSlim()` 的 legend 配置与组成员存在
- `keepState=false` 时 `setOption` 使用 full replace
- 中枢 remap 过滤左边界外/零宽中枢

## 验收标准

- 图表右上角能看到 `1m / 5m / 15m / 30m / 中枢 / 段中枢` legend 开关。
- 点击周期 legend 时，对应周期全部缠论层同时显隐。
- 切换主周期或标的后，不再出现旧中枢残影。
- `docs/temp/中枢显示异常.png` 中类似的右侧堆积框不再持续残留。
- 现有四周期懒加载与实时刷新语义保持不变。
