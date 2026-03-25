# System Settings Dense Ledger Refactor Design

## 目标

把 [`morningglory/fqwebui/src/views/SystemSettings.vue`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/SystemSettings.vue) 当前的“Hero + 两块表单 + 摘要块”改造成高信息密度的三列工作台，在浏览器 `1920x1080`、缩放 `100%` 下尽可能一屏展示完整设置面，优先通过列内滚动而不是页面滚动查看全部设置项。

页面必须满足：

- 不再使用卡片式信息组织。
- 所有正式系统设置项都直接显示在主视图内。
- 保留“直接在列表里编辑并保存”的能力，不改成先看后编辑的二段式交互。
- 主体布局和列表语法向 [`morningglory/fqwebui/src/views/RuntimeObservability.vue`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/RuntimeObservability.vue) 的 dense ledger 靠拢。

## 当前实现事实

- 当前页面分为“启动配置”和“系统设置”两大块，每块都是左侧大表单、右侧摘要块。
- 当前页面在 [`morningglory/fqwebui/src/views/systemSettings.mjs`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/systemSettings.mjs) 中只负责把后端 `sections` 格式化成摘要项，没有为高密度行渲染提供统一 row schema。
- 后端真值由 [`freshquant/system_config_service.py`](D:/fqpack/freshquant-2026.2.23/freshquant/system_config_service.py) 统一组装：
  - Bootstrap 启动配置：`mongodb / redis / order_management / position_management / memory / tdx / api / xtdata / runtime`
  - Mongo 运行参数：`notification / monitor / xtquant / guardian / position_management`
  - 只读策略字典：`strategies`
- Guardian 当前前端交互会按 `mode` 条件显示/隐藏 `percent` 与 `atr.*` 字段，导致布局跳动，不符合“一屏完整查看所有设置项”的目标。

## 设计原则

### 1. 后端 `sections` 继续做字段真值

前端不再手写第二份设置分组真值，继续以 `/api/system-config/dashboard` 返回的 `bootstrap.sections` 与 `settings.sections` 为正式字段清单。前端只负责：

- 把 section items flatten 成密集 row
- 为每个字段路径选择合适编辑控件
- 做列分配、脏状态、行级状态展示

### 2. 三列工作台优先于分块表单

页面不再保留大 Hero 和两块重型 section。改成：

- 顶部压缩工具条
- 下方固定三列工作台
- 每列内部按 section 连续排列 dense ledger

### 3. 全量可见优先于条件隐藏

所有正式设置项都应在主视图内可见。对于 `guardian.stock.threshold.*`、`guardian.stock.grid_interval.*` 这类受 mode 影响的字段：

- 继续显示全部字段
- 用“当前模式未使用”弱化非活跃字段
- 不再根据 mode 动态删行

### 4. 页面级不滚动，列内滚动

延续当前 workbench viewport shell 约束：

- 页面根容器固定 `100vh/100dvh`
- 浏览器级页面滚动尽量为零
- 长列表只在列体内部滚动

## 信息架构

## 顶部工具条

顶部压缩工具条取代现有 hero，包含：

- 页面标题：`系统设置`
- Bootstrap 文件路径
- 真值说明：`Bootstrap 文件 + Mongo`
- 操作按钮：
  - `刷新`
  - `保存启动配置`
  - `保存系统设置`
- 汇总状态：
  - Bootstrap 脏项计数
  - Mongo 脏项计数
  - `需重启`
  - `即时生效`

## 三列布局

主内容固定三列：

- 左列：基础设施 / 存储
  - `MongoDB`
  - `Redis`
  - `Memory`
- 中列：运行接入 / 系统链路
  - `订单管理`
  - `仓位管理库`
  - `TDX`
  - `API`
  - `XTData`
  - `Runtime`
  - `通知`
  - `监控`
- 右列：交易控制 / 策略
  - `XTQuant`
  - `Guardian`
  - `仓位门禁`
  - `策略字典（只读）`

列分配以字段阅读路径和操作频率为准，而不是简单按 Bootstrap / Mongo 二分。这样可以在一屏内减少视线往返。

## 行级交互

每条设置使用统一 dense row，而不是 `el-form-item` 卡片块。建议列结构：

- 设置项
- 当前值编辑区
- 生效方式
- 真值来源
- 状态

每行内容包括：

- 主标题：字段中文名
- 次信息：完整字段路径，例如 `guardian.stock.threshold.atr.multiplier`
- 编辑控件：直接内嵌在“当前值”列
- 状态标签：
  - `已修改`
  - `只读`
  - `当前模式未使用`
  - `当前生效`

保存仍按 Bootstrap / Mongo 两个保存按钮统一提交，不做每行单独保存。

## 字段编辑模型

前端为 row 建立 editor registry，按字段路径选择控件：

- `monitor.xtdata.mode` -> `el-select`
- `xtquant.account_type` -> `el-select`
- `xtquant.broker_submit_mode` -> `el-select`
- `guardian.stock.threshold.mode` -> `el-select` 或紧凑单选
- `guardian.stock.grid_interval.mode` -> `el-select` 或紧凑单选
- 数值字段 -> `el-input-number`
- 普通文本 -> `el-input`
- `strategies.*` -> 只读文本

前端继续维护两份 form state：

- `bootstrapForm`
- `settingsForm`

并维护对应 baseline，用于计算：

- 行级 dirty
- Bootstrap 脏项总数
- Mongo 脏项总数

## Guardian 复合字段展示

`guardian.stock.threshold` 与 `guardian.stock.grid_interval` 都展开为稳定的连续 4 行：

- `mode`
- `percent`
- `atr.period`
- `atr.multiplier`

规则：

- 当前 mode 对应的字段正常显示
- 非当前 mode 字段保持可见但弱化
- 允许用户先录入另一组值，再切换 mode，不丢输入

这样用户能在不跳动布局的前提下完整检查 Guardian 配置。

## 视觉与滚动

页面视觉向 runtime dense ledger 靠拢：

- 不使用 `panel-card`
- 分组只保留扁平 divider 和细边界
- 行高压缩，控件统一 `small`
- 列头和分组头 sticky
- 三列分别 `overflow: auto`

桌面目标：

- `1920x1080 / 100%` 下三列同时可见
- 浏览器层不出现主纵向滚动
- 每列可在本列内部滚动较少距离浏览全部设置

响应式退化：

- `>= 1600px` 三列
- `< 1280px` 两列
- `< 900px` 单列

即使退化，也保持 dense ledger 语法，不退回卡片布局。

## 数据整形方案

在 [`morningglory/fqwebui/src/views/systemSettings.mjs`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/systemSettings.mjs) 新增：

- row flatten helper
- 列分配 helper
- editor type resolver
- dirty state helper
- guardian inactive row helper

[`morningglory/fqwebui/src/views/SystemSettings.vue`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/SystemSettings.vue) 负责：

- 渲染顶部工具条
- 渲染三列 dense ledger
- 绑定内嵌编辑控件
- 调用现有 `loadDashboard / saveBootstrap / saveSettings`

后端接口协议保持不变，除非前端落地时发现缺少最小必要元数据，否则不扩 API。

## 校验与错误处理

保留现有前端校验：

- `allow_open_min_bail > holding_only_min_bail`

并补充：

- 每行错误优先映射到字段路径
- 无法精确映射时挂到所属 section
- Bootstrap 保存成功后继续明确提示“需重启相关服务”

## 测试与验收

### 自动化测试

需要更新或新增：

- [`morningglory/fqwebui/src/views/system-settings.test.mjs`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/system-settings.test.mjs)
  - 断言三列 dense ledger 结构存在
  - 断言不再使用旧 `panel-card`
- [`morningglory/fqwebui/src/views/systemSettings.test.mjs`](D:/fqpack/freshquant-2026.2.23/morningglory/fqwebui/src/views/systemSettings.test.mjs)
  - 断言 section flatten 为稳定 row
  - 断言 editor type 映射
  - 断言 Guardian mode 切换时相关行不消失，只改变状态

### 人工验收

在浏览器 `1920x1080 / 100%` 下：

- 三列同时可见
- 所有正式设置项都出现在主视图
- 页面不出现卡片块式布局
- 编辑控件可直接在行内修改
- Bootstrap 与 Mongo 可分别保存
- Guardian 全字段始终可见

## 非目标

- 不改 `/api/system-config/*` 接口协议
- 不调整系统设置的正式字段语义
- 不把设置页改成详情抽屉或弹窗编辑器
- 不引入新的设计系统或组件库
