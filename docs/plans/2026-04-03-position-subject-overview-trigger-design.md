# Position Subject Overview Trigger Design

**背景**

`/position-management` 中栏“标的总览”已经在源码里切到统一总览面板，但线上/本地运行时仍存在旧 bundle 展示，导致用户截图中的列定义与当前源码不一致。与此同时，overview 接口只返回最近触发时间，不返回触发类型，前端只能把“最近触发”混在运行态里展示，语义容易错位。

**目标**

- 修正“最近触发”列的语义，让列表明确区分触发类型与触发时间。
- 让 `/api/subject-management/overview` 与 `/api/subject-management/<symbol>` 在最近触发字段上保持一致。
- 在不把主表做成超宽平铺表的前提下，尽量把接口已返回的数据清晰展示出来。

**非目标**

- 不在本次改动里重做整页布局。
- 不新增新的后端写接口。
- 不在本次改动里处理正式部署。

**方案**

1. 后端 `overview` 补齐 `runtime.last_trigger_kind`，数据源继续复用 TPSL 最新事件。
2. 前端 `buildOverviewRows` 同步消费 `last_trigger_kind`，输出标准化的 overview 行模型。
3. `PositionSubjectOverviewPanel.vue` 将“运行态”与“最近触发”拆开：
   - `运行态` 只保留分类、持仓、市值。
   - 新增 `门禁` 列，直接展示 detail 已有的 `positionManagementSummary`。
   - 新增 `最近触发` 列，展示 `last_trigger_kind + last_trigger_time`。
4. 保留已完成的 `Guardian 层级买入`、`止盈价格` 与统一配置编辑列，使主表继续承担“摘要 + 编辑入口”的职责。

**数据展示原则**

- 主表展示摘要，不重复把所有 detail 字段平铺成十几列。
- 运行态、门禁、Guardian、止盈、基础配置、止损、最近触发各自独立，避免一列混多个语义。
- detail 已返回但不适合主表平铺的字段，继续留在统一配置列和 entry 明细列里展示。

**验收**

- `/api/subject-management/overview` 返回 `runtime.last_trigger_kind`。
- 中栏“最近触发”列显示“类型 + 时间”，不再与 Guardian 命中或配置列混淆。
- “默认买入金额”“单标的仓位上限”继续分别显示各自正确值。
- 相关前后端测试通过，前端 build 通过。
