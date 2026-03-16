# 标的管理统一页设计

## 背景

当前标的级设置分散在多个页面和接口里：

- `must_pool` 基础设置分散在旧版股票池页面
- Guardian 加仓阶梯价只有后端接口，没有正式前端入口
- 止盈止损集中在 `/tpsl`，但页面只覆盖 TPSL 语义
- 账户级仓位门禁在 `/position-management` 和 `/system-settings`

这导致“一个标的现在怎么配、应该去哪改、改完会影响什么”都不够直观。用户希望有一个统一前端页面，按标的集中查看和维护设置。

## 目标

- 新增一个“标的管理统一页”，集中展示并维护单标的配置。
- 页面采用 `/gantt/shouban30` 风格的高密度表格工作台，不使用卡片式列表。
- 左侧高密度表格直接展示当前配置摘要，右侧负责编辑当前选中标的。
- 止盈区默认直接显示三层，并带每层启停开关。
- 账户级仓位门禁只做只读联动展示，不在本页编辑。

## 非目标

- 不在第一期开放 `instrument_strategy` 的编辑能力。
- 不在第一期做批量编辑、批量保存或批量导入。
- 不把账户级仓位门禁挪到本页编辑。
- 不把 Guardian 运行态重置、TPSL rearm 等运行动作混入第一期主流程。

## 当前真值边界

### 1. 标的基础设置

来源：`must_pool`

当前单标的基础设置字段：

- `code`
- `name`
- `category`
- `stop_loss_price`
- `initial_lot_amount`
- `lot_amount`
- `forever`
- `disabled`

说明：

- `stop_loss_price / initial_lot_amount / lot_amount / forever` 属于本页第一期可编辑真值。
- `disabled` 当前代码里存在，但第一期不额外暴露开关，避免和其他语义混淆。

### 2. Guardian 加仓设置

来源：

- `guardian_buy_grid_configs`
- `guardian_buy_grid_states`

当前配置真值：

- `enabled`
- `BUY-1`
- `BUY-2`
- `BUY-3`

当前运行态：

- `buy_active`
- `last_hit_level`
- `last_hit_price`
- `last_hit_signal_time`
- `last_reset_reason`

说明：

- 本页第一期只编辑 `guardian_buy_grid_configs`。
- `guardian_buy_grid_states` 只读展示，不作为配置项保存。

### 3. 止盈止损

来源：

- `om_takeprofit_profiles`
- `om_takeprofit_states`
- `om_stoploss_bindings`
- `om_buy_lots`

止盈当前语义：

- 按标的维护 `tiers`
- 每层字段为 `level / price / manual_enabled`
- 运行态通过 `armed_levels` 表示

止损当前语义：

- 按 `buy_lot_id` 维护
- 每条字段为 `stop_price / ratio / enabled`
- 当前正式前端只暴露 `stop_price + enabled`

说明：

- 本页第一期继续沿用“止盈按标的、止损按 buy lot”的边界。
- 不尝试把 buy lot 止损强行拍平成标的级统一字段。

### 4. 账户级仓位门禁

来源：`pm_configs.thresholds`

字段：

- `allow_open_min_bail`
- `holding_only_min_bail`

说明：

- 本页只读展示当前门禁状态和阈值，不提供编辑。
- 页面目标是标的管理，不扩展到账户级配置维护。

## 页面结构

页面采用固定双栏工作台：

- 左栏：标的总览表
- 右栏：当前标的编辑区

### 顶部工具栏

顶部保留紧凑工具栏，包含：

- 搜索框
- 分类筛选
- `仅 must_pool`
- `仅持仓中`
- `仅已配置止盈`
- `仅有活跃止损`
- 刷新按钮
- 只读仓位门禁摘要

仓位门禁摘要展示：

- `effective_state`
- `allow_open_min_bail`
- `holding_only_min_bail`

### 左栏：高密度标的总览表

左栏视觉语言直接参考 `/gantt/shouban30`：

- `el-table`
- `size="small"`
- `border`
- 行点击切换右栏
- 当前选中行高亮

左表目标：

- 不点进去也能看出一个标的现在的配置概况
- 尽量减少在不同页面来回切换确认真值

建议列定义：

1. `代码`
2. `名称`
3. `分类`
4. `基础设置`
   - `止损价`
   - `首笔/常规金额`
   - `forever`
5. `Guardian`
   - `开关`
   - `B1/B2/B3`
6. `止盈`
   - `L1/L2/L3`
   - 每层 `价格 + 开/关`
7. `止损`
   - `活跃 lot 数 / open lot 数`
8. `运行态`
   - `持仓数量`
   - `last_hit_level`
   - `最近触发时间`
9. `操作`
   - `编辑`

展示规则：

- 空值统一显示 `-`
- 金额和价格统一格式化为两位小数
- `B1/B2/B3` 与 `L1/L2/L3` 用紧凑 monospace 表达
- 左表只读，不支持行内编辑

### 右栏：当前标的编辑区

右栏按单标的固定拆成四个 panel：

1. `基础设置`
2. `Guardian 加仓设置`
3. `止盈止损`
4. `只读运行态`

#### 基础设置

可编辑字段：

- `stop_loss_price`
- `initial_lot_amount`
- `lot_amount`
- `forever`
- `category`

保存动作：

- `保存基础设置`

#### Guardian 加仓设置

可编辑字段：

- `enabled`
- `BUY-1`
- `BUY-2`
- `BUY-3`

只读字段：

- `buy_active`
- `last_hit_level`
- `last_hit_price`
- `last_hit_signal_time`

保存动作：

- `保存 Guardian 设置`

#### 止盈止损

上半区：止盈三层固定表格

字段：

- `Level`
- `Price`
- `Enabled`
- `Armed`

下半区：buy lot 止损表格

字段：

- `buy_lot_id`
- `买入时间`
- `买入价`
- `原始/剩余数量`
- `stop_price`
- `enabled`
- `保存`

#### 只读运行态

展示：

- 当前持仓数量
- Guardian 运行态
- `armed_levels`
- 活跃止损数量
- 最近 trigger / request / order / trade 摘要

## 默认交互

### 1. 左看右改

- 页面初始化先加载总览
- 默认选中第一条标的
- 点击左表行后，右栏切换到该标的
- 左表摘要只读，所有编辑都发生在右栏

### 2. 分区保存

每个 panel 独立保存：

- `基础设置`
- `Guardian`
- `止盈`
- `止损`

不做整页一次性提交，避免不同真值源互相污染。

### 3. 止盈默认三层

这是本页的重要交互约束。

规则：

- 如果标的已有 takeprofit profile，则按真实 tiers 展示
- 如果标的没有 profile，则默认生成 `L1 / L2 / L3` 三层草稿
- 三层默认都直接显示，不需要用户先点击“新增层级”
- 每层默认：
  - `manual_enabled = true`
  - `price = null`

保存前要求：

- 三层都存在
- 每层 `price > 0`

这样既满足“默认显示三层”，又不伪造用户未确认的价格。

## 接口设计

### 聚合读接口

新增两个聚合读接口，统一服务左表和右栏：

- `GET /api/subject-management/overview`
- `GET /api/subject-management/<symbol>`

#### `overview` 返回字段

每行至少返回：

- `symbol`
- `name`
- `category`
- `must_pool`
  - `stop_loss_price`
  - `initial_lot_amount`
  - `lot_amount`
  - `forever`
- `guardian`
  - `enabled`
  - `buy_1`
  - `buy_2`
  - `buy_3`
- `takeprofit`
  - `tiers`
    - `level`
    - `price`
    - `enabled`
- `stoploss`
  - `active_count`
  - `open_buy_lot_count`
- `runtime`
  - `position_quantity`
  - `last_hit_level`
  - `last_trigger_time`

#### `detail` 返回字段

- `subject`
- `must_pool`
- `guardian_buy_grid_config`
- `guardian_buy_grid_state`
- `takeprofit`
  - `tiers`
  - `state`
- `buy_lots`
  - 含 `stoploss`
- `runtime_summary`
- `position_management_summary`

### 写接口

建议按分区保存，避免大接口：

- `POST /api/subject-management/<symbol>/must-pool`
- `POST /api/subject-management/<symbol>/guardian-buy-grid`
- `POST /api/tpsl/takeprofit/<symbol>` 继续复用
- `POST /api/order-management/stoploss/bind` 继续复用

## 校验规则

### 基础设置

- `stop_loss_price > 0`
- `initial_lot_amount >= 0`
- `lot_amount >= 0`
- `category` 非空

可选提示：

- `initial_lot_amount < lot_amount` 仅 warning，不强制拦截

### Guardian

- `BUY-1 / BUY-2 / BUY-3 >= 0`
- 如果开启但阶梯价为空，允许保存，但给 warning
- 第一版不强制要求 `BUY-1 <= BUY-2 <= BUY-3`

### 止盈

- 固定三层
- 每层 `price > 0`
- `level` 固定为 `1 / 2 / 3`
- 全部关闭时允许保存，但提示当前无启用止盈层

### 止损

- `enabled = true` 时，`stop_price` 不能为空
- `stop_price > 0`
- 单条保存，不做批量保存

## 刷新策略

- 页面加载：
  - 拉 `overview`
  - 默认选中第一条并拉 `detail`
- 点击左表行：
  - 只拉当前标的 `detail`
- 保存成功：
  - 重新拉当前 `detail`
  - 再刷新 `overview`
  - 保留左表筛选条件和当前选中行
- 保存失败：
  - 保留右栏草稿
  - 在当前 panel 顶部报错

## 影响文件

后端预计涉及：

- `freshquant/rear/api_server.py`
- `freshquant/rear/subject_management/routes.py`
- `freshquant/subject_management/dashboard_service.py`
- `freshquant/subject_management/write_service.py`

前端预计涉及：

- `morningglory/fqwebui/src/router/index.js`
- `morningglory/fqwebui/src/views/MyHeader.vue`
- `morningglory/fqwebui/src/api/subjectManagementApi.js`
- `morningglory/fqwebui/src/views/SubjectManagement.vue`
- `morningglory/fqwebui/src/views/subjectManagement.mjs`
- `morningglory/fqwebui/src/views/subjectManagementPage.mjs`
- 相关测试文件

文档预计涉及：

- `docs/current/interfaces.md`
- `docs/current/modules/kline-webui.md`
- 必要时补充新的 `docs/current/modules/*.md`

## 测试策略

后端：

- 先补聚合服务测试
- 再补 route 测试
- 最后补写接口测试

前端：

- 先补 `subjectManagement.mjs` 和 `subjectManagementPage.mjs` 的 node test
- 再跑 `vite build`

建议验证命令：

- `pytest freshquant/tests/test_subject_management_service.py freshquant/tests/test_subject_management_routes.py -q`
- `node --test src/views/subjectManagement.test.mjs src/views/subjectManagementPage.test.mjs`
- `npm run build`

## 部署影响

本次改动预计同时影响：

- `freshquant/rear/**`
- `morningglory/fqwebui/**`

按仓库规则需要：

- 重建并部署 API Server
- 重建并部署 Web UI
- 完成对应健康检查后才能视为 Done
