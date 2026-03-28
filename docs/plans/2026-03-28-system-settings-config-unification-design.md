# System Settings Config Unification Design

## 目标

把 [`/system-settings`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/SystemSettings.vue) 调整为“系统级正式配置总览页”，解决两个当前问题：

- 系统级正式配置项没有完全出现在页面上，`pm_configs.thresholds.single_symbol_position_limit` 这类真实生效项被漏掉。
- 三栏分组按实现来源拆散，同一模块设置没有聚在一起，尤其是 Mongo / 库配置被分散在多处。

本次改动只收口系统级真值，不把标的级配置入口并入该页。

## 范围

### 纳入 `/system-settings` 的正式真值

- Bootstrap 文件配置
- Mongo `params`
- Mongo `pm_configs.thresholds`
- Mongo `strategies` 只读字典

### 明确不纳入本页的配置

- `pm_configs.symbol_position_limits.overrides`
- `instrument_strategy`
- `must_pool`
- 其他标的级覆盖配置

边界保持为：

- `/system-settings` 管系统级真值
- `/position-management` / `/subject-management` 继续管理标的级覆盖

## 当前实现事实

- 后端系统配置聚合入口在 [`freshquant/system_config_service.py`](D:/fqpack/freshquant-2026.2.23/freshquant/system_config_service.py)。
- 前端页面使用 [`morningglory/fqwebui/src/views/systemSettings.mjs`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/systemSettings.mjs) 对 dashboard sections 做二次整形和三栏分配。
- 当前 `settings.position_management` 只暴露：
  - `allow_open_min_bail`
  - `holding_only_min_bail`
- 但仓位管理真实生效阈值还包含：
  - `single_symbol_position_limit`
- [`freshquant/position_management/dashboard_service.py`](D:/fqpack/freshquant-2026.2.23/freshquant/position_management/dashboard_service.py) 与 [`morningglory/fqwebui/src/views/PositionManagement.vue`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/PositionManagement.vue) 已经把 `single_symbol_position_limit` 当作全局真值使用。

这说明 `/system-settings` 当前不是完整系统级配置聚合页，前后端存在配置真值漂移。

## 设计原则

### 1. 后端 dashboard 必须成为完整系统级配置出口

页面不应靠前端猜测还有哪些真实生效项。凡是系统级正式真值，且属于 `/system-settings` 的边界，就必须由 `/api/system-config/dashboard` 显式返回。

### 2. 页面按“模块”分组，不按“存储来源”分组

用户关注的是模块语义，而不是某项来自 bootstrap 还是 Mongo。三栏应按模块归并，避免同类配置分散。

### 3. 系统级与标的级严格分层

本页只展示系统级真值，不把 symbol override 和 instrument override 混进来，避免设置层级混乱。

### 4. `/position-management` 与 `/system-settings` 必须共享同一套 PM 阈值口径

若一个字段已经被仓位管理页视作全局真值，则系统设置页也必须完整呈现并支持维护。

## 信息架构

三栏改为以下固定语义：

### 左栏：基础设施 / 存储

- `mongodb`
- `redis`
- `order_management`
- `position_management` 数据库配置
- `memory`

### 中栏：交易接入 / 运行链路

- `xtquant`
- `monitor`
- `tdx`
- `xtdata`
- `api`
- `runtime`
- `notification`

### 右栏：交易规则 / 门禁

- `guardian`
- `position_management` 阈值配置
- `strategies`

其中 `position_management` 的“数据库配置”和“门禁阈值”允许分别出现在左栏与右栏，因为它们属于两个不同配置域：

- Bootstrap 中的 `position_management.mongo_database` 属于存储层
- Mongo 中的 `pm_configs.thresholds.*` 属于交易门禁层

## 数据契约调整

### `freshquant/system_settings.py`

补齐系统级 PM 阈值默认值与聚合对象：

- `DEFAULT_PM_CONFIG.thresholds.single_symbol_position_limit`
- `PositionManagementSettings.single_symbol_position_limit`
- `SystemSettings.reload()` 对应读取逻辑

这样 `system_settings.position_management` 本身就成为完整 PM 系统级阈值快照。

### `freshquant/system_config_service.py`

补齐 `settings.position_management` section：

- `single_symbol_position_limit`

并同步更新：

- `SETTINGS_SECTION_META`
- `_settings_values_from_provider()`
- `_normalize_settings_values()`
- `update_settings()`

保存 `/system-settings` 时，`pm_configs.thresholds` 应一次性写回：

- `allow_open_min_bail`
- `holding_only_min_bail`
- `single_symbol_position_limit`

## 前端落地

### 页面数据

[`morningglory/fqwebui/src/views/systemSettings.mjs`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/systemSettings.mjs) 需要：

- 为 `position_management.single_symbol_position_limit` 增加 number editor 元数据
- 调整 section -> column 分组规则，使同一模块聚在一起
- 继续保持 Guardian 全字段常驻、未生效行弱化

### 页面表单

[`morningglory/fqwebui/src/views/SystemSettings.vue`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/SystemSettings.vue) 的默认 `settingsForm.position_management` 需要补齐：

- `single_symbol_position_limit`

同时保持现有校验：

- `allow_open_min_bail > holding_only_min_bail`

`single_symbol_position_limit` 只需要有限数字校验，不增加新的联动规则。

## 测试策略

### 后端

更新：

- [`freshquant/tests/test_system_settings.py`](D:/fqpack/freshquant-2026.2.23/freshquant/tests/test_system_settings.py)
- [`freshquant/tests/test_system_config_service.py`](D:/fqpack/freshquant-2026.2.23/freshquant/tests/test_system_config_service.py)

验证：

- `SystemSettings` 能读取 `single_symbol_position_limit`
- dashboard 返回完整的 `position_management` section
- `update_settings()` 能写回三项 PM 阈值

### 前端

更新：

- [`morningglory/fqwebui/src/views/systemSettings.test.mjs`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/systemSettings.test.mjs)

验证：

- `position_management.single_symbol_position_limit` 出现在 row schema 中
- 使用 number editor
- `position_management` section 落在右栏
- 左栏聚合 Mongo / Redis / order / position_management 库 / memory

### 文档

同步更新：

- [`docs/current/configuration.md`](D:/fqpack/freshquant-2026.2.23/docs/current/configuration.md)

修正 `/system-settings` 对 `pm_configs.thresholds` 的描述，使其与真实实现一致。

## 验收标准

- `/system-settings` 页面能看到并编辑全局 `single_symbol_position_limit`
- 同模块配置按新的三栏语义聚合，不再把 Mongo / 库配置拆散
- `/system-settings` 保存后，`pm_configs.thresholds` 三项阈值都能正确落库
- 后端和前端相关单测通过
- `docs/current/configuration.md` 与代码同步

## 非目标

- 不把 symbol-level overrides 并入 `/system-settings`
- 不改变 `PositionManagement` 页面现有单标的覆盖交互
- 不修改正式部署流程
