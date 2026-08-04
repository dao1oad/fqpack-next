# Guardian 三档买入仓位上限前端设计——最终最小修改方案

> 状态：联合评审后的实施方案  
> 日期：2026-08-04  
> 依据：当前 `main` 代码事实、用户产品要求、Codex 产品/UI/UX/工程复核、Devin Ultra 单轮只读评审  
> 实施范围：`/kline-slim` 的“标的设置”浮层；不改变 Guardian、Position Management、止损及订单执行的后端业务语义

## 1. 目标

在 `/kline-slim` 现有“标的设置”浮层中：

1. 把 Guardian `BUY-1 / BUY-2 / BUY-3` 的价格与阶段仓位 CAP 设计成可发现、可理解、可校验的“分级补仓”配置；
2. 在同一区域编辑“单标的总仓位上限”；
3. 总仓位上限继续直接读写 Position Management 的 `pm_configs`，与“仓位管理”保持同一个数据源真值；
4. 从该浮层移除“单笔止损”可视区域，为分级补仓设计腾出空间；
5. 三档 CAP 的默认值固定为 `20 万 / 35 万 / 50 万`；
6. 保持最小代码改动，不新增配置副本、聚合存储、交易状态或后端业务规则。

## 2. 当前代码事实

### 2.1 Guardian CAP 已具备保存合同

`morningglory/fqwebui/src/views/KlineSlim.vue` 已有三行 Guardian 输入：

```text
guardianDraft.buy_1 / buy_2 / buy_3
guardianDraft.max_position_amounts[0..2]
guardianDraft.buy_enabled[0..2]
```

保存继续使用：

```text
POST /api/stock/guardian_buy_grid_config
```

后端字段继续是：

```text
max_position_amounts
```

本次不改变该字段及其“元”单位。

当新标的或历史配置没有有效的三个 CAP 值时，前端编辑草稿默认填入：

```text
CAP-1 = 200000 元
CAP-2 = 350000 元
CAP-3 = 500000 元
```

默认值只用于初始化缺失 CAP 的前端草稿，不覆盖已经存在的合法 CAP，也不在页面加载时
自动写库。Guardian 运行时对缺失 CAP 的既有 fail-closed 行为保持不变；只有用户明确
保存后，默认值才通过现有 Guardian 配置接口成为正式配置。

### 2.2 单标的总仓位上限已有唯一真值与读写链

唯一真值：

```text
pm_configs.thresholds.single_symbol_position_limit
pm_configs.symbol_position_limits.overrides
```

当前 Subject Management detail 已调用
`PositionManagementDashboardService.get_symbol_limit()`，并在
`position_limit_summary` 中返回：

```text
default_limit
effective_limit
using_override
market_value
blocked
available
```

KlineSlim 当前也已加载该 detail，并已具备：

```text
subjectPanelState.positionLimitDraft.limit
subjectPanelActions.savePositionLimit()
handleSaveSubjectConfigBundle()
```

保存最终仍调用：

```text
POST /api/position-management/symbol-limits/<symbol>
```

因此不新增总上限 GET、POST 或聚合接口，不把总上限写入
`guardian_buy_grid_configs`。

### 2.3 单笔止损与总上限共用 detail

当前“单笔止损”列表与总上限来自同一 Subject Management detail。移除止损显示后，
该 detail 仍需加载以取得总仓位上限。因此本次只删除 KlineSlim 浮层中的止损模板、
止损同步文案和直接相关的视图断言；不为减少返回字段而新增接口，也不拆除现有
Subject Panel normalizer、止损后端或其他页面的止损能力。

## 3. 最终信息架构

浮层保持“标的设置”入口，内容顺序：

```text
标的设置                              [保存价格设置] [关闭]
├─ 止盈价格
└─ Guardian 分级补仓
   ├─ 说明：价格下跌进入对应区间后，每次按基础量补仓；
   │        累计仓位不超过该级 CAP，总仓位上限是最终硬门禁。
   ├─ 总仓位硬门禁
   │  ├─ 当前仓位市值
   │  ├─ 单标的总仓位上限（元）
   │  ├─ 约合 xx.xx 万
   │  ├─ 来源：单独设置 / 系统默认值
   │  └─ [保存总上限] [恢复系统默认]
   ├─ 规则提示
   │  ├─ BUY-1 > BUY-2 > BUY-3
   │  └─ CAP-1 ≤ CAP-2 ≤ CAP-3；最终执行不超过总仓位上限
   └─ 分级补仓表
      ┌──────────┬────────────┬──────────────────┬──────┐
      │ 补仓等级 │ 触发价格(元)│ 阶段最大仓位(元) │ 启用 │
      ├──────────┼────────────┼──────────────────┼──────┤
      │ BUY-1    │ 价格输入    │ CAP-1 输入       │ 开关 │
      │ 第一档   │             │ 约合 xx.xx 万    │      │
      │ BUY-2    │ 价格输入    │ CAP-2 输入       │ 开关 │
      │ 第二档   │             │ 约合 xx.xx 万    │      │
      │ BUY-3    │ 价格输入    │ CAP-3 输入       │ 开关 │
      │ 第三档   │             │ 约合 xx.xx 万    │      │
      └──────────┴────────────┴──────────────────┴──────┘
      [全部开启] [全部关闭] [保存买入设置]
```

原“单笔止损”区块不再出现在该浮层。

## 4. UI/UX 细节

### 4.1 单位与格式

- 价格输入：单位“元”，精度 `0.001`，沿用现有价格精度；
- CAP 与总上限输入：数据和 `v-model` 继续使用“元”，步长 `10,000`，整数；
- 输入框下方或右侧展示只读换算：`约合 20.00 万`；
- 不把 `v-model` 改成万元，避免单位转换、浮点精度和保存合同扩散；
- 金额使用千分位展示，空值显示 `--`。
- 缺少有效 CAP 配置时，三个输入框分别预填 `200,000 / 350,000 / 500,000 元`；
  若当前总仓位上限低于默认 CAP，则保留默认值并显示超限警告，由用户先提高总上限
  或调低 CAP 后再保存，不静默裁剪默认配置。

### 4.2 语义文案

区块标题改为：

```text
Guardian 分级补仓
```

辅助说明：

```text
价格下跌进入对应区间后，每次按基础买入量补仓；
阶段 CAP 限制该区间可达到的最大仓位，总仓位上限是最终硬门禁。
```

三行分别明确显示：

```text
BUY-1 / CAP-1 / 第一档
BUY-2 / CAP-2 / 第二档
BUY-3 / CAP-3 / 第三档
```

### 4.3 总上限来源

总上限卡片必须展示：

- `using_override=true`：`单独设置`；
- `using_override=false`：`系统默认值`；
- `available=false`：禁用编辑和保存，并显示后端错误或“该标的不在仓位管理跟踪范围”；
- 当前仓位市值及总上限使用率（数据存在时）；
- 总上限是风险硬门禁，允许优先降低。

“恢复系统默认”仅在 `using_override=true` 时显示。点击后：

1. 强制刷新 Subject Management detail，取得服务端当前 `default_limit`；
2. 将最新默认值 POST 到现有 symbol-limit 接口；
3. 后端按既有逻辑移除 override；
4. 再刷新 detail，确认来源变为“系统默认值”。

该顺序避免使用过期默认值时误创建新的 override。

### 4.4 保存边界

总仓位上限不并入顶部“保存价格设置”：

- 总上限属于 Position Management 风险门禁；
- Guardian CAP 和止盈属于价格策略配置；
- 当前顶部保存本身是 Guardian 与止盈的顺序调用，不是事务；
- 把第三个数据源加入顶部保存会扩大部分成功的误解。

最终交互：

- 顶部按钮改名为“保存价格设置”，保持现有 Guardian + 止盈保存行为；
- Guardian 区块增加“保存买入设置”，直接复用现有
  `handleSaveGuardianPriceGuides()`；
- 总上限卡片使用独立“保存总上限”；
- “恢复系统默认”是独立明确动作。

## 5. 校验与运行边界

### 5.1 Guardian 保存前

前端提示并阻止明显无效输入：

```text
BUY-1 > BUY-2 > BUY-3 > 0
CAP-1 <= CAP-2 <= CAP-3
每个 CAP > 0
```

读取到有效总上限时，再校验：

```text
CAP-1 / CAP-2 / CAP-3 <= 当前 effective_limit
```

后端 Guardian upsert 的现有校验继续是最终保存保护，运行时
`min(stage_cap, global_symbol_limit)` 继续是最终交易保护。

### 5.2 降低总仓位上限

风险上限必须允许随时降低，即使新总上限低于已配置 CAP。此时：

- 总上限独立保存成功；
- Guardian 卡片显示警告：
  `部分阶段 CAP 高于总仓位上限，实际执行将按总上限裁剪，请调整后再保存买入设置`；
- 高于总上限的 CAP 输入显示警告态；
- 后续 Guardian 保存仍由前后端校验阻止，直到 CAP 调整合规；
- 不为了保持展示一致而阻止用户降低风险硬门禁。

这也覆盖用户从“仓位管理”页面降低总上限后的同一真值同步场景。

### 5.3 并发与刷新

- 打开浮层时继续并行加载价格 detail 和 subject detail；
- 总上限保存成功后强制刷新 subject detail；
- Guardian 保存前使用当前页面已加载上限做体验校验，后端使用最新 PM 真值做最终校验；
- 后端拒绝时展示后端错误，不伪装为保存成功；
- 切换标的沿用现有 `routeToken`，避免旧请求覆盖新标的。

## 6. 最小修改文件

### 必改

1. `morningglory/fqwebui/src/views/KlineSlim.vue`
   - 删除“单笔止损”可视区和“止损同步中”文案；
   - 重构 Guardian 区块为总上限卡片 + 三档补仓表；
   - 增加列头、单位、换算、来源、规则提示、保存与恢复默认按钮；
   - 增加桌面与窄屏样式；桌面浮层适度加宽，窄屏保持单列可滚动。

2. `morningglory/fqwebui/src/views/js/kline-slim.js`
   - 复用当前 subject detail 和 `savePositionLimit()`；
   - 将现有位置上限保存逻辑收敛为独立“保存总上限”动作；
   - 增加“恢复系统默认”的强制刷新—保存—再刷新编排；
   - 提供金额格式化、来源和告警所需的轻量 computed/method；
   - 不删除止损后端调用能力，不改交易逻辑。

3. `morningglory/fqwebui/src/views/js/kline-slim-price-panel.mjs`
   - 定义并复用 CAP 默认值 `[200000, 350000, 500000]`；
   - 只在三个 CAP 缺失或无效时初始化编辑草稿，不覆盖合法已保存值；
   - 为 Guardian 校验增加可选 `effectivePositionLimit`；
   - 增加 CAP 超总上限的明确错误；
   - 保持原函数在未提供上限时的兼容行为。

4. `morningglory/fqwebui/src/views/klineSlim.test.mjs`
   - 删除“浮层必须包含单笔止损”的旧断言；
   - 断言新标题、列头、总上限来源、独立保存、恢复默认和三档 CAP 结构；
   - 断言浮层不再渲染“单笔止损”区块。

5. `morningglory/fqwebui/src/views/js/kline-slim-price-panel.test.mjs`
   - 增加 CAP 与 effective total limit 的校验用例；
   - 保持价格顺序、CAP 顺序和保存 payload 用例。

6. `morningglory/fqwebui/src/views/js/kline-slim-subject-panel.test.mjs`
   - 覆盖总上限真值字段、保存和恢复默认编排需要的最小状态行为；
   - 证明保存仍调用 position-management symbol-limit 接口。

### 原则上不改

```text
freshquant/rear/position_management/routes.py
freshquant/position_management/dashboard_service.py
freshquant/rear/stock/routes.py
freshquant/strategy/guardian_buy_grid.py
freshquant/tpsl/**
freshquant/order_management/**
```

若实施中发现现有 detail 丢失 `available/error` 字段，仅允许补齐现有 read model
透传和相应后端测试，不新增第二份存储或新接口。

## 7. 测试

### 7.1 前端单元与静态合同

1. KlineSlim 浮层包含“Guardian 分级补仓”；
2. 包含“单标的总仓位上限”“系统默认值/单独设置”；
3. 包含 BUY-1/CAP-1、BUY-2/CAP-2、BUY-3/CAP-3；
4. 包含价格、阶段最大仓位和启用列头；
5. 不再渲染“单笔止损”区块；
6. CAP 输入仍绑定 `max_position_amounts[0..2]`，保存单位仍是元；
7. 无有效 CAP 配置时草稿默认为 `200000 / 350000 / 500000`，已有合法值保持原值；
8. 默认 CAP 只在用户保存后写入正式配置，页面加载不产生写操作；
9. 总上限保存调用现有 `saveSymbolPositionLimit`；
10. 恢复默认先刷新最新 default，再 POST，再刷新；
11. 价格逆序、CAP 非递增、CAP 超总上限均给出明确提示；
12. 总上限不可用时禁用相关编辑，不影响止盈与 Guardian detail 的只读展示。

### 7.2 构建

在 `morningglory/fqwebui` 执行：

```powershell
npm test
npm run build
```

若项目测试脚本不是全量入口，以 `package.json` 当前脚本为准，至少运行：

```powershell
node --test src/views/klineSlim.test.mjs
node --test src/views/js/kline-slim-price-panel.test.mjs
node --test src/views/js/kline-slim-subject-panel.test.mjs
npm run build
```

### 7.3 本机浏览器验收

部署本地 Web UI 后打开：

```text
http://192.168.1.116:18080/kline-slim
```

验收：

1. 选择一个已跟踪标的，打开“标的设置”；
2. 桌面宽度下信息层级清晰，无横向溢出；
3. 价格、CAP、总上限单位明确；
4. 三档行与列对齐，开关可识别；
5. 当前仓位、总上限来源和约合万元可读；
6. 保存总上限后刷新页面，“仓位管理”和 KlineSlim 显示同一 effective limit；
7. 从“仓位管理”修改后再打开或刷新浮层，KlineSlim 同步显示；
8. 恢复默认后来源变为“系统默认值”；
9. 降低总上限到 CAP 以下时出现裁剪警告，但总上限可保存；
10. 调整 CAP 合规后“保存买入设置”成功；
11. “单笔止损”区块不再出现；
12. 768px 左右窄屏下布局转为单列，按钮与输入不遮挡；
13. K 线、止盈线、Guardian 买入线仍正常显示与编辑。

## 8. 部署与验收范围

命中：

```text
morningglory/fqwebui/**
```

本任务最终验收以本机 Web UI 为准：

1. 构建 Web UI；
2. 重建/重启本地 `fq_webui`；
3. 检查 `/kline-slim` 页面可打开；
4. 使用浏览器实际检查设计与交互；
5. 运行相关前端测试及构建；
6. 将实施分支合并到本地 `main`；
7. 按用户要求不执行 `git push`。

## 9. Codex 与 Devin 一致意见

共同结论：

- 使用 Subject Management detail 已内嵌的 Position Management summary；
- 总上限直接复用现有 symbol-limit POST，保持 `pm_configs` 单一真值；
- 不新增后端接口和字段；
- 总上限独立保存，不加入顶部非事务保存；
- “恢复默认”先刷新服务端最新默认值再 POST；
- CAP 继续以元作为数据和输入真值，额外显示约合万元；
- CAP 缺失时前端默认初始化为 `20 万 / 35 万 / 50 万`，不覆盖合法配置、不自动写库；
- 删除 KlineSlim 浮层内“单笔止损”展示，但保留止损后端与其他页面能力；
- 后端校验与运行时 `min(stage_cap, global limit)` 继续作为最终保护；
- 总上限作为风险硬门禁允许优先降低，CAP 超限通过告警与后续保存校验收敛；
- 只修改实现该纵向切片所需的前端文件，不做无关重构。
