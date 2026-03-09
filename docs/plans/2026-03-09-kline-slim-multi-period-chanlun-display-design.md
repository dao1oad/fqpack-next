# KlineSlim 多周期缠论显示设计

**日期**：2026-03-09

## 背景

当前目标仓的 `KlineSlim` 已具备基础的主图行情显示能力，但图表内部仍是简化版 renderer：

- 只稳定处理当前周期的 `bidata / duandata / zsdata`
- 使用固定的“主图样式 + 单叠加样式”
- 仍保留“主周期 + 固定 overlay 周期”的组织方式

这与旧仓已经成熟的多周期缠论图层体系存在明显差异。旧仓的 `KlineSlim` 支持：

- 多周期并行缠论图层
- 按周期映射的配色和线宽
- 按周期分组的 legend 联动
- 按可见性触发的懒加载与重绘

当前问题可以归结为两类：

1. 各级别中枢无法正常显示
2. 缠论结构的配色和线条粗细未对齐旧仓

用户已明确本次只迁移“旧仓完整多周期缠论图层”，但不迁移 MACD、均线及其它工作台能力；同时由于当前生产者/消费者链路只向 Redis 推送 `1m / 5m / 15m / 30m` 周期，因此前端也只支持这四个周期。

## 目标

- 在当前目标仓 `KlineSlim` 页面布局不变的前提下，恢复旧仓多周期缠论图层能力
- 前端只支持 `1m / 5m / 15m / 30m` 四个缠论周期
- 首屏默认只加载 `5m` 主 K 线和 `5m` 缠论结构
- 其余周期仅在用户通过图表 legend 打开后才懒加载
- 图表显示恢复旧仓按周期映射的配色与线宽规则
- 图表支持每周期完整绘制：
  - 笔
  - 段
  - 高级别段
  - 中枢
  - 段中枢
  - 高级段中枢
- legend 支持按周期分组联动，并保留跨周期的中枢总开关
- 实时模式下，仅刷新当前可见周期集合

## 非目标

- 不迁移旧仓 MACD 联动
- 不迁移旧仓日线均线联动
- 不迁移旧仓信号筛选、成交标记、融资融券、网格多图等工作台能力
- 不改当前 `KlineSlim` 的整体页面布局、侧栏、右侧结构面板和路由
- 不新增后端接口
- 不为缺失的 `higher_duan_zsdata` 额外补发非 cache 请求
- 不把当前 Redis 生产者/消费者周期扩展到 `1m / 5m / 15m / 30m` 之外

## 当前现状结论

### 1. 前端 renderer 现状

当前目标仓 [draw-slim.js](D:/fqpack/freshquant-2026.2.23/.worktrees/brainstorm-kline-slim-display/morningglory/fqwebui/src/views/js/draw-slim.js) 只支持：

- 当前周期 `笔`
- 当前周期 `段`
- 当前周期 `普通中枢`
- 固定 `30m` 叠加的 `笔 / 段 / 普通中枢`

未接入：

- `higherDuanData`
- `duan_zsdata`
- `higher_duan_zsdata`
- 按周期映射的样式体系
- 按周期分组的 legend 联动

因此“中枢显示异常”不是单点 bug，而是当前 renderer 本身未实现完整多级中枢图层。

### 2. 旧仓能力现状

旧仓 [draw-slim.js](D:/fqpack/freshquant/morningglory/fqwebui/src/views/js/draw-slim.js) 和 [kline-slim.js](D:/fqpack/freshquant/morningglory/fqwebui/src/views/js/kline-slim.js) 已实现：

- 四个以上周期并行缠论图层
- 每周期 `笔 / 段 / 高级别段 / 中枢 / 段中枢 / 高级段中枢`
- 周期样式映射 `PERIOD_STYLE_MAP`
- 周期线宽倍率 `PERIOD_WIDTH_FACTOR`
- 周期 legend 组联动
- 全局 `中枢` / `段中枢` legend
- 懒加载和可见性联动
- 高周期图层到当前主图时间轴的 remap 和边界过滤

### 3. 数据源现状

当前目标仓 [freshquant/rear/stock/routes.py](D:/fqpack/freshquant-2026.2.23/.worktrees/brainstorm-kline-slim-display/freshquant/rear/stock/routes.py) 已提供 `/api/stock_data`，实时模式可通过 `realtimeCache=1` 命中 Redis 中的 fullcalc payload。

当前 [chanlun_payload.py](D:/fqpack/freshquant-2026.2.23/.worktrees/brainstorm-kline-slim-display/freshquant/market_data/xtdata/chanlun_payload.py) 已写入：

- `bidata`
- `duandata`
- `higherDuanData`
- `zsdata`
- `duan_zsdata`

但 `higher_duan_zsdata` 当前明确为空数组，不作为本次补算对象。

## 方案比较

### 方案 A：在当前页面上扩展现有 renderer，恢复旧仓多周期缠论层能力（推荐）

做法：

- 保留当前 `KlineSlim.vue` 页面布局
- 扩展当前 `kline-slim.js` 的数据状态，从“主周期 + 固定 overlay”改为“四周期可见性驱动”
- 扩展当前 `draw-slim.js`，迁入旧仓的多周期图层、样式、legend、remap 逻辑
- 删除与本次无关的旧仓 MACD/均线联动部分

优点：

- 对用户可见页面变化最小
- 改动集中在前端图表内核，风险可控
- 不引入新后端接口
- 最符合“只迁移完整多周期缠论图层”的要求

缺点：

- 需要对旧仓逻辑做裁剪整合，不能直接整文件覆盖

### 方案 B：直接移植旧仓完整 draw-slim / kline-slim 图表逻辑

优点：

- 对齐旧仓最快
- 样式与交互最接近旧仓

缺点：

- 会连带引入大量本次不需要的工作台逻辑
- 维护成本高
- 与当前页面结构冲突更大

### 方案 C：新建独立多周期缠论 renderer 模块，由当前页完全委托调用

优点：

- 结构最清晰
- 后续维护边界最好

缺点：

- 设计与重组成本最高
- 对当前需求来说偏重

## 设计决策

采用方案 A：

- 保留当前 `KlineSlim` 页面和现有后端接口
- 在前端内部恢复旧仓的多周期缠论图层能力
- 周期范围收敛为 `1m / 5m / 15m / 30m`
- 默认只加载 `5m`
- 其他周期通过 legend 开关懒加载

## 架构与数据流

### 1. 页面层

[KlineSlim.vue](D:/fqpack/freshquant-2026.2.23/.worktrees/brainstorm-kline-slim-display/morningglory/fqwebui/src/views/KlineSlim.vue) 保持当前布局：

- 顶部工具栏
- 左侧股票池侧栏
- 中间主图区域
- 右侧缠论结构面板

页面层仅做轻量文案与状态接线调整，不承担多周期图层逻辑。

### 2. 状态层

[kline-slim.js](D:/fqpack/freshquant-2026.2.23/.worktrees/brainstorm-kline-slim-display/morningglory/fqwebui/src/views/js/kline-slim.js) 从当前的：

- `mainData`
- `overlayData`
- `overlayPeriod = 30m`
- `overlayTimer`

改为：

- `mainData`：当前主图周期的 K 线数据
- `chanlunMultiData[period]`：按周期缓存的缠论 payload
- `visibleChanlunPeriods`：当前 legend 可见周期集合
- `loadedChanlunPeriods`：已成功加载周期集合
- `chanlunPeriodLoading[period]`：单周期加载状态

### 3. 数据请求规则

首屏与切换标的：

- 只加载当前主图周期的数据
- 默认主图周期为 `5m`
- 仅将 `5m` 注册为默认选中 legend

用户打开其它周期 legend：

- 若该周期数据未加载，则调用 `/api/stock_data?period=<period>&realtimeCache=1`
- 请求成功后写入 `chanlunMultiData[period]`
- 触发图表增量重绘

用户关闭周期 legend：

- 仅隐藏对应周期图层
- 不清缓存
- 不继续刷新该周期

实时模式刷新：

- 主图周期继续刷新
- 其余仅刷新当前 legend 可见周期
- 不可见周期不请求

### 4. 数据字段语义

每周期图层统一从 `/api/stock_data` payload 解析：

- `bidata`
- `duandata`
- `higherDuanData`
- `zsdata`
- `zsflag`
- `duan_zsdata`
- `duan_zsflag`
- `higher_duan_zsdata`
- `higher_duan_zsflag`

边界约束：

- 若 `higher_duan_zsdata` 为空，则“高级段中枢”图层为空，不补请求
- 若某周期 payload 缺任一其它字段，则该周期对应图层按空数组处理，不报错

## 图表绘制设计

### 1. 周期范围

只支持：

- `1m`
- `5m`
- `15m`
- `30m`

不再在前端注册 `3m / 60m / 120m` 等旧仓周期。

### 2. 图层集合

每个周期图层组包含：

- 笔
- 段
- 高级别段
- 中枢
- 段中枢
- 高级段中枢

### 3. 样式映射

沿用旧仓样式规则，但只保留四个周期：

- `1m`：笔白色、段黄色、高级别段蓝色、中枢白色、段中枢黄色、高级段中枢蓝色
- `5m`：笔黄色、段蓝色、高级别段红色、中枢黄色、段中枢蓝色、高级段中枢红色
- `15m`：笔黄色、段蓝色、高级别段红色、中枢黄色、段中枢蓝色、高级段中枢红色
- `30m`：笔蓝色、段红色、高级别段绿色、中枢蓝色、段中枢红色、高级段中枢绿色

线宽倍率只保留：

- `1m = 1`
- `5m = 3`
- `15m = 4`
- `30m = 5`

### 4. legend 规则

保留三类 legend：

- 周期组：`1m / 5m / 15m / 30m`
- 全局 `中枢`
- 全局 `段中枢`

行为语义：

- 点击某周期：联动该周期下全部图层
- 点击 `中枢`：联动所有可见周期的普通中枢
- 点击 `段中枢`：联动所有可见周期的段中枢和高级段中枢
- 切换标的后重置为默认仅 `5m` 选中
- 数据刷新后保留现有 legend 选中状态

## 跨周期对齐规则

高周期图层映射到当前主图时间轴时，沿用旧仓的 remap 思路：

- 笔、段、高级别段按最近时间点对齐
- 中枢类图层转换为带 `xAxis / yAxis` 的 `markArea` 点
- 完全早于主图最左边界的中枢直接丢弃
- 起点终点映射到同一根 K 线的中枢直接丢弃
- 对越界时间点做边界 clamp，避免 markArea 丢失

## 文件落地范围

### 直接修改

- [KlineSlim.vue](D:/fqpack/freshquant-2026.2.23/.worktrees/brainstorm-kline-slim-display/morningglory/fqwebui/src/views/KlineSlim.vue)
- [kline-slim.js](D:/fqpack/freshquant-2026.2.23/.worktrees/brainstorm-kline-slim-display/morningglory/fqwebui/src/views/js/kline-slim.js)
- [draw-slim.js](D:/fqpack/freshquant-2026.2.23/.worktrees/brainstorm-kline-slim-display/morningglory/fqwebui/src/views/js/draw-slim.js)

### 可选新增

- `morningglory/fqwebui/src/views/js/kline-slim-chanlun-periods.mjs`

用途仅限：

- 周期常量
- legend 可见性工具
- 懒加载顺序与去重工具

## 错误处理

- 单周期懒加载失败时，仅该周期不显示，不影响主图和其它周期
- 某周期数据为空时，不报错，只不生成对应图层
- `higher_duan_zsdata` 为空时不补算、不补请求
- 主图周期请求失败时沿用当前页面错误提示语义
- legend 状态不因单周期失败而重置

## 性能边界

- 首屏仅请求 `5m`
- 非默认周期只在用户点开后请求
- 已加载周期重复开关不重复请求
- 仅当前可见周期参与实时刷新
- 隐藏周期不轮询、不重绘
- 重绘继续使用节流/下一帧合并，避免 legend 快速切换触发多次 `setOption`
- 不引入 MACD / 均线 / 其它旧仓附加图层，避免无关计算负担

## 验收标准

- 进入 `/kline-slim?symbol=...` 时，只请求并显示 `5m` 主 K 线与 `5m` 缠论图层
- 图表 legend 中只默认选中 `5m`
- `1m / 15m / 30m` 只有用户点开时才请求
- 已打开过的周期再次开关时优先走本地缓存，不重复请求
- 每个周期能正确显示：
  - 笔
  - 段
  - 高级别段
  - 中枢
  - 段中枢
- `higher_duan_zsdata` 为空时，高级段中枢不显示，但不报错
- 四个周期的配色和线宽符合旧仓规则
- 中枢不会错误映射为竖线或明显越界
- legend 周期组联动正常
- `中枢` / `段中枢` 全局 legend 联动正常
- 切换标的后恢复默认仅 `5m` 选中
- 当前侧栏、热门原因弹层、右侧结构面板、主周期切换和实时/历史模式行为不回归

## 风险

- 当前目标仓的 `draw-slim.js` 已经是精简版，恢复旧仓逻辑时容易引入局部重复实现，需要在实现阶段控制迁移范围
- 多周期图层恢复后，legend 与实时刷新之间的状态保持是回归高发点
- `higher_duan_zsdata` 当前没有数据，用户会看到该层始终为空，需要在实现和文案上保持一致预期

## RFC 约束

本设计仅涉及现有页面内部显示逻辑重构，不新增顶级模块、不新增后端入口、不引入外部依赖，当前判断可直接进入实施计划阶段。

若实现阶段出现以下变化，必须先补 RFC 再编码：

- 新增对外 API
- 跨多个目录的大范围重构超出当前页面与前端图表内核范围
- 引入新的外部依赖
- 产生明确破坏性行为变更
