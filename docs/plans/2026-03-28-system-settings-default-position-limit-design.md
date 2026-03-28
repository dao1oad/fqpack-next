# 系统设置页默认持仓上限设计

## 背景

当前系统级单标的默认持仓上限真值是 `pm_configs.thresholds.single_symbol_position_limit`，默认值约为 `800000`。

用户期望在 `/system-settings -> 仓位门禁` 页面里直接看到这个当前值，并能把输入框里的数字改成新的值后保存，不需要跳去别的页面理解“80 万默认值”到底在哪里改。

## 目标

- 在 `/system-settings -> 仓位门禁` 中明确展示并编辑系统级默认持仓上限
- 输入框加载页面时直接显示当前真实配置值
- 保存系统设置时把新值稳定写回 `pm_configs.thresholds.single_symbol_position_limit`
- 同步审查还有哪些系统级参数适合继续放在 `/system-settings`

## 非目标

- 不把 `pm_configs.symbol_position_limits.overrides.<symbol>` 并入 `/system-settings`
- 不把 `instrument_strategy` 的单标的覆盖配置并入 `/system-settings`
- 不调整 `/position-management` 现有单标的 override 编辑入口

## 当前系统事实

- `freshquant/system_settings.py` 已把 `single_symbol_position_limit` 作为 `PositionManagementSettings` 的系统级字段读取
- `freshquant/system_config_service.py` 已在 `/api/system-config/dashboard` 和 `/api/system-config/settings` 里聚合并保存该字段
- `/system-settings` 当前已经消费 `position_management.single_symbol_position_limit`，但用户诉求是让它以“当前默认持仓上限”的语义更明确地露出，并保证输入框默认直接显示当前值

## 方案比较

### 方案 A：最小修正

仅确保字段继续显示在“仓位门禁”中。

- 优点：改动最小
- 缺点：页面语义仍然偏技术实现，用户不容易一眼确认“默认 80 万”就是这里

### 方案 B：一致性修正（采用）

保持系统级真值边界不变，同时把页面语义、默认值显示、测试和文档统一校准。

- 优点：既满足“当前值可改”，也避免系统级与标的级参数混淆
- 缺点：需要同步改前端文案、测试和文档

### 方案 C：把标的级配置一起收口

把单标的 override 与 `instrument_strategy` 也并到 `/system-settings`。

- 优点：入口表面上更集中
- 缺点：会混淆系统级默认值与标的级覆盖，不符合当前正式真值边界

## 采用设计

### 页面边界

`/system-settings` 继续只承载系统级正式真值，不接手标的级覆盖配置。

`仓位门禁` 分组固定只放 3 个系统级阈值：

- `allow_open_min_bail`
- `holding_only_min_bail`
- `single_symbol_position_limit`

### 页面语义

`single_symbol_position_limit` 在页面中的展示名称改为：

- `单标的默认持仓上限`

页面交互保持简单直接：

- 输入框默认显示当前真实配置值
- 用户直接修改数字
- 点击“保存系统设置”后落库
- 不新增切换态、恢复默认按钮或额外确认流

辅助文案需要强调：

- 未为某个标的单独设置上限时，默认使用这里的值

### 后端契约

保持现有真值模型不变，只要求契约稳定：

- `GET /api/system-config/dashboard` 稳定返回 `settings.values.position_management.single_symbol_position_limit`
- `POST /api/system-config/settings` 保存时稳定写回 `pm_configs.thresholds.single_symbol_position_limit`
- `/system-settings` 与 `/position-management` 读取到的系统默认值必须一致

### 参数审查结论

当前适合放在 `/system-settings` 的系统级参数，已经基本完整：

- `freshquant_bootstrap.yaml` 中的基础设施和运行入口配置
- `params.notification`
- `params.monitor`
- `params.xtquant`
- `params.guardian`
- `pm_configs.thresholds`
- `strategies` 只读字典

当前不适合放在 `/system-settings` 的参数：

- `pm_configs.symbol_position_limits.overrides.<symbol>`
- `instrument_strategy.*`
- 其他标的级 `lot_amount / threshold / grid` 覆盖

## 测试要求

### 后端

- 断言 dashboard 返回 `position_management.single_symbol_position_limit`
- 断言 settings 保存后会把新值写回 `pm_configs.thresholds.single_symbol_position_limit`

### 前端

- 断言“单标的默认持仓上限”输入框默认显示当前值
- 断言修改后保存会提交新的 `single_symbol_position_limit`

### 文档

同步更新：

- `docs/current/configuration.md`
- `docs/current/modules/position-management.md`

文案统一到“单标的默认持仓上限”，并明确它是系统默认值，不是标的级 override。

## 验收标准

- `/system-settings -> 仓位门禁` 可以直接看到当前默认值，例如 `800000`
- 用户可直接改成其他数字并保存
- 刷新页面后显示保存后的新值，不回弹
- `/position-management` 读取到的系统默认值与 `/system-settings` 一致
- 页面不引入标的级 override 或 `instrument_strategy` 编辑入口
