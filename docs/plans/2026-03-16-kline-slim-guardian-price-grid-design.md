# KlineSlim Guardian 价格层级与止盈网格设计

## 背景

`/kline-slim` 当前已经具备：

- 单标的多周期 K 线主图
- 缠论结构叠加
- 左侧标的列表
- 图例、viewport、十字星等图表交互

但页面还缺少“与当前标的交易配置直接相关”的价格真值展示与维护入口。用户希望在 `KlineSlim.vue` 页面直接完成：

- Guardian 倍量价格层级设置
- 止盈价格设置
- 在图表上直接展示这些价格横线
- 横线之间形成明显的价格网格视觉

并要求颜色规则固定：

- Guardian 倍量价格层级成功高到低：蓝、红、绿
- 止盈价格从低到高：蓝、红、绿

## 目标

- 在 `/kline-slim` 直接查看和编辑当前标的的 Guardian 三层价格与止盈三层价格。
- 图表主区直接展示 6 条价格横线，并带轻量网格化视觉提示。
- 不新增新的配置真值来源，继续复用现有后端接口和 Mongo 集合。
- 保持 `KlineSlim` 当前的 scene 重建、viewport、自定义十字星机制不被破坏。

## 非目标

- 本期不做“拖拽横线直接保存”。
- 本期不改 Guardian / TPSL 后端真值结构。
- 本期不把 buy lot 止损并入 `KlineSlim` 图表层。
- 本期不新增批量编辑或多标的联动保存。
- 本期不处理 Guardian 空层级清空语义，只沿用当前“固定三层价格”的前端约束。

## 当前真值边界

### 1. Guardian 价格层级

现有真值：

- 读聚合详情：`GET /api/subject-management/<symbol>`
- 写配置：`POST /api/subject-management/<symbol>/guardian-buy-grid`

后端聚合详情已经返回：

- `guardian_buy_grid_config`
- `guardian_buy_grid_state`

当前配置字段：

- `enabled`
- `buy_1`
- `buy_2`
- `buy_3`

运行态字段：

- `buy_active`
- `last_hit_level`
- `last_hit_price`
- `last_hit_signal_time`
- `last_reset_reason`

说明：

- `buy_1 / buy_2 / buy_3` 已经是标的级 Guardian 真值，不应在 KlineSlim 另建一份状态。
- 当前后端 `upsert_config()` 对空值不支持“真正删除”，因此前端按固定三层、必填价格处理更稳。

### 2. 止盈价格层级

现有真值：

- 读聚合详情：`GET /api/subject-management/<symbol>`
- 写 profile：`POST /api/tpsl/takeprofit/<symbol>`

当前字段：

- `level`
- `price`
- `manual_enabled`

运行态：

- `armed_levels`

说明：

- `KlineSlim` 不需要自己维护 takeprofit profile。
- 当前 TPSL 保存接口要求 tiers 非空且每层 `price` 能转成正数，不能直接提交空价格。

## 方案对比

### 方案 A：复用 SubjectManagement 聚合详情，在 KlineSlim 内增加价格层级面板

做法：

- `KlineSlim` route symbol 变化时，额外请求 `/api/subject-management/<symbol>`
- 直接复用现有保存接口：
  - Guardian：`/api/subject-management/<symbol>/guardian-buy-grid`
  - Takeprofit：`/api/tpsl/takeprofit/<symbol>`
- 图表 scene 增加价格引导线数据，renderer 渲染横线与价格带

优点：

- 真值单一
- 改动集中在前端
- 不需要新增后端接口
- 与现有 `SubjectManagement` 页面语义完全一致

缺点：

- 需要把 `SubjectManagement` 的部分 view-model / 校验逻辑抽出来复用

结论：

- 推荐

### 方案 B：KlineSlim 自己分别拉取 Guardian 和 TPSL 接口并拼装数据

优点：

- 读链路表面上更直接

缺点：

- 要重复写归一逻辑
- 容易和 `SubjectManagement` 页面产生字段漂移
- 错误处理和保存后刷新逻辑会重复

结论：

- 不推荐

### 方案 C：新增专用 `kline-price-guides` 聚合接口

优点：

- 如果以后要做图上拖拽保存，接口形态会更自然

缺点：

- 当前是重复建设
- 增加后端维护面
- 对本期需求收益不大

结论：

- 当前不推荐，除非确认下一步马上做拖拽编辑

## 推荐设计

### 1. 数据源

`KlineSlim` 继续以 K 线数据为主数据源，另增加一个“标的价格引导详情”副数据源：

- `subjectDetail`

来源：

- `GET /api/subject-management/<symbol>`

在前端把这份详情归一为：

- `guardianDraft`
- `guardianState`
- `takeprofitDrafts`
- `takeprofitState`
- `priceGuides`

其中 `priceGuides` 是给图表层的只读派生数据，不单独保存。

### 2. 前端结构

`KlineSlim.vue` 新增一个轻量右侧面板，不替换现有左侧 sidebar。

推荐布局：

- 顶部 toolbar 增加：
  - `价格层级` 按钮
  - 当前标的价格配置摘要 chip
- 右侧主图区上方或右侧抽屉增加 `价格层级面板`

面板分两段：

1. `Guardian 倍量价格`
   - `enabled`
   - `buy_1`
   - `buy_2`
   - `buy_3`
   - `buy_active` 只读状态

2. `止盈价格`
   - `L1`
   - `L2`
   - `L3`
   - `manual_enabled`
   - `armed_levels` 只读状态

交互原则：

- Guardian 与止盈分开保存
- 保存成功后只刷新当前 symbol 的 detail 与图表
- 不刷新左侧 sidebar 数据

### 3. 图表展示设计

不使用 `markLine`，而是继续沿用当前 scene -> renderer -> series 的架构。

#### 3.1 价格横线

为每条价格生成一条 `line series`，数据只需要两个点：

- `[scene.mainWindow.startTs, price]`
- `[scene.mainWindow.endTs, price]`

渲染规则：

- Guardian 三条线：
  - `G-B1` 蓝色实线
  - `G-B2` 红色实线
  - `G-B3` 绿色实线
- 止盈三条线：
  - `TP-L1` 蓝色虚线
  - `TP-L2` 红色虚线
  - `TP-L3` 绿色虚线

说明：

- 两组都用蓝红绿是用户明确要求
- 为避免混淆，必须同时靠“前缀标签 + 实/虚线”区分

#### 3.2 网格效果

仅靠 6 条横线不够像网格，推荐补两类淡色价格带：

- Guardian price band：
  - `buy_1 <-> buy_2`
  - `buy_2 <-> buy_3`
- Takeprofit price band：
  - `L1 <-> L2`
  - `L2 <-> L3`

价格带使用 `custom series` 渲染横向矩形，透明度很低。

视觉目标：

- 给用户明显的价格区间层次感
- 不盖住 K 线主体

#### 3.3 标签

每条线右侧显示短标签：

- `G-B1 10.20`
- `G-B2 9.90`
- `G-B3 9.50`
- `TP-L1 10.80`
- `TP-L2 11.20`
- `TP-L3 11.80`

标签和现有十字星价格标签不能冲突，建议作为 `graphic` 或独立 label line series 实现，但应由 renderer 统一生成。

### 4. Scene / Renderer / Controller 改动

#### 4.1 Scene

`buildKlineSlimChartScene()` 增加可选输入：

- `priceGuides`

scene 内新增：

- `priceGuideLines`
- `priceGuideBands`

#### 4.2 Renderer

在 `buildSceneRenderSeries()` 中：

- 先画 legend placeholder
- 再画 K 线
- 再画价格 band
- 再画价格 line
- 最后画缠论结构线和结构框

原因：

- price band 要在 K 线上方但很淡
- price line 需要清楚可见
- 缠论主结构仍要保持可读性

#### 4.3 Controller / Y 轴

`collectVisibleValues()` 必须把价格线值和价格带边界值纳入计算。

否则问题会是：

- 当某个 Guardian 或止盈价明显高于/低于当前 visible K 线范围时
- Y 轴自动缩放会把它裁掉

所以 viewport 的 `yRange` 必须同时覆盖：

- 主 K 线 high/low
- 多周期结构 line points
- 结构框 top/bottom
- price guide line prices
- price band top/bottom

### 5. 数据归一与复用

不建议直接在 `KlineSlim` 中复制 `SubjectManagement` 的归一逻辑。

推荐做法：

- 把当前 `subjectManagement.mjs` 中与页面无关的纯函数抽到共享模块

建议抽出的函数：

- `normalizeGuardianConfig`
- `buildTakeprofitDrafts`
- `buildDetailViewModel` 的价格相关子集

建议新增模块：

- `morningglory/fqwebui/src/views/js/subject-price-guides.mjs`

这样：

- `SubjectManagement`
- `KlineSlim`

都可以复用同一份标的级价格真值归一逻辑。

### 6. 校验规则

#### Guardian

- `buy_1 / buy_2 / buy_3` 必须都是正数
- 价格顺序必须满足：
  - `buy_1 > buy_2 > buy_3`

#### Takeprofit

- `L1 / L2 / L3` 必须都是正数
- 价格顺序必须满足：
  - `L1 < L2 < L3`

#### 保存阻断

任一规则不满足时：

- 不发请求
- 在面板内给出明确提示

### 7. 刷新与缓存策略

Kline 数据刷新和价格详情刷新应解耦：

- 切换 symbol：
  - 刷 K 线
  - 刷 Chanlun 叠加
  - 刷 subjectDetail
- 切换 period：
  - 不重新拉 subjectDetail
- 保存 Guardian / Takeprofit：
  - 重新拉 subjectDetail
  - 调 `scheduleRender()`

为保证图表一定重绘，`renderVersion` 应加入：

- `priceGuideVersion`

可以是：

- `JSON.stringify(priceGuides)`

或更轻量的 hash 字符串。

## 风险点

### 1. Guardian 空值语义不稳定

当前后端对空值更接近“转成默认值/保留旧值”，不是真正删除。

策略：

- 本期固定三层必填
- 不在 KlineSlim 放“删除层级”能力

### 2. TPSL 空价格会直接保存失败

当前 `save_takeprofit_profile` 要求 tiers 非空且价格可转成浮点。

策略：

- 前端保存前先做完整校验
- 沿用 `SubjectManagement` 当前的阻断提示语义

### 3. 图表信息过密

价格线、band、缠论结构、十字星叠加后，主图可能变脏。

策略：

- band 透明度严格控制
- Guardian 用实线，止盈用虚线
- 提供总开关：
  - `显示价格网格`

如果第一版仍显拥挤，可再拆分：

- `显示 Guardian`
- `显示止盈`

### 4. 标签与十字星冲突

右侧价格标签可能与十字星价格标签重叠。

策略：

- 价格线标签用更靠内的偏移
- 十字星标签继续贴右边界

## 测试策略

### 前端纯逻辑测试

- `priceGuides` 构建函数
- Guardian / Takeprofit 顺序校验
- 保存前 payload 生成
- `renderVersion` 包含 price guides 后的重绘触发

### 图表渲染测试

- scene 包含 6 条价格线时，renderer 生成对应 series
- controller 的 `collectVisibleValues()` 含 price guide 后，`yRange` 覆盖这些价格

### 页面交互验证

- 切换 symbol 后面板同步更新
- 保存 Guardian 后图表横线立即变化
- 保存 Takeprofit 后图表横线立即变化
- period 切换不丢失价格线
- history / realtime 模式下价格线都稳定显示

## 部署影响

如果按推荐方案实施，代码改动仅在：

- `morningglory/fqwebui/**`

部署动作：

- 重建并重部署 Web UI

如果后续追加“Guardian 空层级清空语义”修复，则会额外影响：

- `freshquant/rear/**`
- `freshquant/strategy/**`

本设计当前不包含该后端变更。
