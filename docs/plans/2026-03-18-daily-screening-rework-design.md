# 每日选股重构设计

## 背景

当前每日选股模块已经具备正式页面、API 和 Dagster 定时任务，但整体语义仍然是“执行工作台”：

- 前端页面可以手动发起扫描
- 页面通过 SSE 展示运行阶段事件
- Dagster 只是触发一次 `model=all` 的黑盒执行
- 前端交集筛选建立在既有 `CLXS -> chanlun -> shouban30_agg90 -> market_flags` 流程结果之上

这和新的业务目标不一致。新的目标不是继续增强“单次扫描执行过程”，而是把每日选股页面改成“Dagster 预计算结果集合 + 前端自由组合交集”的查询工作台。

另外，当前 Dagster 实现仍是单个 op 包裹整个每日选股执行过程，不符合“可观察、可补跑、可定位失败节点”的编排要求。新的设计必须参考 `stock_data_job` 的依赖式编排形式，而不是继续保留黑盒 job。

## 目标

- 前端页面移除手动执行区和 SSE 事件流，只保留结果查询、条件组合、交集结果和标的详情。
- 每日选股正式结果只允许由 Dagster 任务生成，前端不再触发筛选执行。
- Dagster 按节点依赖编排每日选股结果准备过程，不再通过单个黑盒 op 一次跑完。
- 后端为前端准备统一条件索引，支持前端任意组合条件并取交集。
- 前端所有查询都锚定在 `(A ∪ B)` 基础池，不允许二级条件直接回到全市场。
- 沿用现有 `fqscreening` 作为正式结果真值，但把语义调整为“条件 membership + 指标快照”。

## 非目标

- 不保留前端手动发起每日选股运行的能力。
- 不保留 SSE 运行事件展示。
- 不在本期把 provider 维度暴露给前端做独立条件。
- 不在本期引入用户级、会话级或个人工作区隔离。
- 不在本期把每日选股页面重新扩展为 `.blk` 同步工作台；工作区动作不是本次重构核心。

## 已确认需求

### 1. 前端定位

- 页面改成纯查询工作台。
- 去掉手动运行入口。
- 去掉 SSE 事件流。
- 前端只读取 Dagster 已落库的正式结果。

### 2. 条件总体语义

- 前端所有条件进入统一条件池。
- 用户可以任意混选条件。
- 页面结果为所选条件的交集。
- 查询基准永远锚定 `(A ∪ B)`。
- 当用户不选任何条件时，默认结果就是 `(A ∪ B)`。

### 3. 一级结果集合

一级结果集合的入口全集统一为：

- 全市场股票
- 排除名称包含 `ST` 的标的
- 排除北交所标的

一级结果包括：

- `A`：`CLS` 所有模型筛选结果
  - 每个模型作为前端独立条件
- `B`：热门标的 4 个时间窗口
  - `30/45/60/90` 天
  - `xgb + jygs` 聚合后作为统一热门结果
  - 不按 provider 拆条件

### 4. 二级结果集合

先对 `A` 和 `B` 取并集，得到唯一基础池 `(A ∪ B)`，然后在这个基础池上继续准备二级条件：

- `C`：年线附近
- `D`：优质标的
- `E`：融资标的
- `F`：`/gantt/shouban30` 页面缠论数值指标
  - 高级段倍数
  - 段倍数
  - 笔涨幅%
  - 前端按数值阈值筛选，不是固定布尔条件
- `G`：`chanlun` 条件
  - 周期：`30m / 60m / 1d`
  - 信号：沿用当前 6 个信号
  - 周期和信号都作为独立页面条件
  - 周期和信号分维度取交集，不要求命中来自同一条 `(period, signal)` 记录

## 当前实现与目标差异

当前实现：

- 页面仍有执行区、模型切换、参数 schema、开始扫描按钮
- 页面消费 SSE 事件流
- Dagster 通过 `DailyScreeningService.start_run(model=all)` 黑盒触发
- 页面交集筛选仍围绕旧全链路输出组织

目标实现：

- 页面不再承担执行职责，只承担条件筛选和详情展示职责
- Dagster 负责准备正式结果集合
- 后端正式真值不再强调“某次运行过程”，而是强调“某个正式交易日 scope 下的条件索引和指标快照”

## 总体方案

推荐方案是“基于条件索引的 Dagster 结果准备架构”：

- Dagster 使用多节点依赖编排，而不是单个黑盒 op
- `fqscreening` 继续作为正式结果存储
- 后端把各种结果统一整理成：
  - 条件 membership
  - 股票快照
  - 运行审计
- 前端只消费：
  - 最新正式 scope
  - 条件目录
  - 交集查询结果
  - 标的详情

不推荐继续使用“全链路黑盒运行 + 页面展示过程”的模式，原因是它不适合当前“前端自由组合条件”的产品定位，也不满足 Dagster 编排可观察性的要求。

## Dagster 编排设计

### 设计原则

- 参考 `stock_data_job` 的依赖式编排风格
- 不再使用单个 op 包裹整个每日选股逻辑
- 节点粒度按“计算来源 / 阶段”拆分，而不是按“每个前端条件”拆到过细
- 正式结果发布必须是最后一步，避免半成品覆盖正式 scope

### 建议节点

#### 1. `daily_screening_context`

职责：

- 解析本次 `trade_date`
- 生成正式 `scope_id = trade_date:<YYYY-MM-DD>`
- 初始化运行审计上下文

#### 2. `daily_screening_upstream_guard`

职责：

- 校验上游数据是否齐备
- 重点校验热门标的相关快照是否对 `30/45/60/90` 窗口可用
- 上游不齐备时直接 fail，本次不发布正式结果

#### 3. `daily_screening_universe`

职责：

- 生成统一初始股票池
- 固定执行：
  - 排除 `ST`
  - 排除北交所

#### 4. 一级节点

- `daily_screening_cls`
  - 生成全部 `CLS` 模型命中结果
  - 落库时按模型拆 membership
- `daily_screening_hot_30`
- `daily_screening_hot_45`
- `daily_screening_hot_60`
- `daily_screening_hot_90`
  - 都从热门读模型中聚合 `xgb + jygs`

#### 5. `daily_screening_base_union`

职责：

- 对 `CLS` 全模型结果和 `30/45/60/90` 热门结果取并集
- 该结果是所有二级条件的唯一基准池

#### 6. 二级节点

- `daily_screening_flag_near_long_term_ma`
- `daily_screening_flag_quality_subject`
- `daily_screening_flag_credit_subject`
- `daily_screening_shouban30_chanlun_metrics`
  - 准备 `higher_multiple / segment_multiple / bi_gain_percent`
- `daily_screening_chanlun_variants`
  - 准备周期 membership
  - 准备信号 membership

#### 7. `daily_screening_snapshot_assemble`

职责：

- 汇总各节点结果
- 写股票快照
- 生成前端详情所需聚合字段

#### 8. `daily_screening_publish_scope`

职责：

- 正式发布 `trade_date` scope
- 只有全部上游节点成功时才覆盖正式结果

### 节点粒度约束

- Dagster 节点粒度不等于前端条件粒度。
- 不建议为每个 `CLS` 模型或每个 `chanlun` 信号单独建 Dagster 节点。
- 推荐节点按来源和阶段拆分，membership 在节点内部按前端条件粒度展开并落库。

## 正式存储设计

继续使用 `fqscreening` 三张集合，但调整语义。

### 1. `daily_screening_runs`

用途：

- 保存 Dagster 执行审计信息
- 用于排障，不作为前端业务查询主入口

建议内容：

- `run_id`
- `trade_date`
- `scope_id`
- Dagster job / run 标识
- 各阶段状态
- 开始时间 / 结束时间 / 错误信息

### 2. `daily_screening_memberships`

用途：

- 保存“股票属于哪些前端条件”的正式索引
- 是前端自由组合交集查询的核心

建议唯一粒度：

- `scope_id + code + condition_key`

建议条件编码：

- `cls:S0001`
- `cls:S0002`
- ...
- `hot:30d`
- `hot:45d`
- `hot:60d`
- `hot:90d`
- `flag:near_long_term_ma`
- `flag:quality_subject`
- `flag:credit_subject`
- `chanlun_period:30m`
- `chanlun_period:60m`
- `chanlun_period:1d`
- `chanlun_signal:buy_zs_huila`
- `chanlun_signal:buy_v_reverse`
- `chanlun_signal:macd_bullish_divergence`
- `chanlun_signal:sell_zs_huila`
- `chanlun_signal:sell_v_reverse`
- `chanlun_signal:macd_bearish_divergence`
- `base:union`

### 3. `daily_screening_stock_snapshots`

用途：

- 保存单股票在当前正式 scope 下的展示字段和数值指标
- 支撑数值阈值筛选与详情页展示

建议按 `scope_id + code` 唯一。

建议字段：

- 基础字段
  - `code`
  - `name`
  - `symbol`
  - `trade_date`
- 基础池字段
  - `in_base_union`
- `F` 数值字段
  - `higher_multiple`
  - `segment_multiple`
  - `bi_gain_percent`
- 聚合展示字段
  - 命中的 `CLS` 模型列表
  - 命中的热门窗口列表
  - 命中的 `chanlun` 周期列表
  - 命中的 `chanlun` 信号列表
  - 热门理由摘要
  - 市场属性摘要

### 4. scope 语义

前端正式只消费：

- `trade_date:<YYYY-MM-DD>`

不再把 `run:<run_id>` 暴露为主业务查询范围。

## 查询语义设计

### 1. 默认查询

当用户未选择任何条件时：

- 返回 `(A ∪ B)` 基础池

### 2. 条件查询

当用户选择任意条件组合时：

- 查询语义固定为：
  - `base_union ∩ 条件1 ∩ 条件2 ∩ ...`

### 3. 数值条件

`F` 的 3 个条件不是普通 membership，而是数值阈值过滤：

- `higher_multiple <= x`
- `segment_multiple <= x`
- `bi_gain_percent <= x`

### 4. 周期与信号

`G` 的周期和信号分别是独立条件：

- 周期通过 membership 取交集
- 信号通过 membership 取交集
- 不要求它们来自同一条组合记录

## 前端页面设计

页面从“执行工作台”改成“筛选工作台”，保留结果与详情区域，移除执行区域。

### 1. 顶部摘要区

显示：

- 当前正式 `trade_date`
- 当前基础池数量
- 当前交集结果数量
- 刷新按钮

移除：

- 手动运行状态
- 当前 `run_id`
- `SSE` 状态
- schema / runs 刷新按钮
- 开始扫描按钮

### 2. 条件区

按条件族分组展示：

- `CLS` 模型
- 热门窗口
- 市场属性
- `Shouban30` 缠论数值指标
- `Chanlun` 周期
- `Chanlun` 信号

交互原则：

- 所有布尔 / membership 条件使用可多选 chip
- 数值条件使用阈值输入控件
- 支持重置条件

### 3. 结果列表区

默认结果：

- `(A ∪ B)`

建议字段：

- 代码
- 名称
- 命中 `CLS` 数
- 命中热门窗口
- 年线 / 优质 / 融资
- `higher_multiple`
- `segment_multiple`
- `bi_gain_percent`
- 命中 `chanlun` 周期摘要
- 命中 `chanlun` 信号摘要

### 4. 详情区

点击单标的后展示统一画像：

- 基础信息
- 命中 `CLS` 模型
- 命中热门窗口
- 市场属性
- 三个缠论数值指标
- 命中 `chanlun` 周期
- 命中 `chanlun` 信号
- 热门理由摘要

## API 设计

页面改成查询工作台后，API 也要从执行导向切到查询导向。

### 保留

- `/api/daily-screening/scopes/latest`
- `/api/daily-screening/scopes/<scope_id>/summary`
- `/api/daily-screening/query`
- `/api/daily-screening/stocks/<code>/detail`

### 新增或重构

- `/api/daily-screening/filters`
  - 返回条件目录
  - 返回默认数值阈值
  - 返回各条件命中数量
- `/api/daily-screening/query`
  - 接受统一条件池参数
  - 接受数值阈值参数
  - 后端内部固定锚定 `base_union`

### 废弃

前端不再使用：

- `/api/daily-screening/schema`
- `/api/daily-screening/runs`
- `/api/daily-screening/runs/<run_id>`
- `/api/daily-screening/runs/<run_id>/stream`

兼容策略：

- 可以短期保留旧接口供排障使用
- 页面不再调用旧接口
- SSE 相关接口最终应删除

## 失败处理

### 1. 发布策略

- 只有全部上游节点成功时才发布正式 scope
- 任一节点失败，不覆盖当天正式结果

### 2. 前端缺数提示

当当天正式 scope 不存在时：

- 不展示“空列表即成功”
- 应明确提示“今日正式结果未生成”
- 同时返回最近可用交易日

### 3. 查询错误区分

接口应明确区分：

- `scope` 不存在 / 尚未发布
- 查询参数非法
- 单标的详情不存在

## 测试策略

### 1. Dagster 编排测试

- 锁定节点依赖关系
- 锁定 `base_union` 只来源于 `A/B`
- 锁定二级节点只吃 `base_union`

### 2. 服务层测试

- 锁定 universe 过滤规则
  - 排除 `ST`
  - 排除北交所
- 锁定热门窗口是 `xgb + jygs` 聚合
- 锁定二级条件只作用于 `(A ∪ B)`
- 锁定 `chanlun` 周期和信号分维度 membership

### 3. API 测试

- 无条件查询默认返回 `(A ∪ B)`
- 多条件交集返回正确
- 数值阈值筛选正确
- 详情接口返回统一画像

### 4. 前端测试

- 页面不再渲染执行区和 SSE 区块
- 条件分组渲染正确
- 数值阈值控件生效
- 点击结果行联动详情正确

## 部署影响

- `freshquant/daily_screening/**` 改动后，需重建 API Server。
- `morningglory/fqwebui/**` 改动后，需重建 Web UI。
- `morningglory/fqdagster/**` 改动后，需重启 Dagster Webserver / Daemon。
- 因 Dagster 编排语义变化，部署后需要补跑新的每日选股正式任务，确认正式 scope 已发布。

## 迁移策略

建议按以下顺序推进：

1. 先补新的 Dagster 编排与新的 `fqscreening` 查询语义
2. 再把前端切到新查询工作台
3. 然后移除页面对手动运行和 SSE 的依赖
4. 最后删除后端旧执行接口和 SSE 逻辑

这样可以避免一次性切换导致排障面过大。

## 结论

本次重构的本质不是“继续增强每日选股执行链路”，而是把每日选股正式能力改造成：

- Dagster 负责结果准备
- `fqscreening` 负责正式真值
- 前端负责条件组合、交集查询和详情展示

正式查询永远锚定 `(A ∪ B)`，Dagster 则以多节点依赖方式准备：

- `CLS` 全模型结果
- `30/45/60/90` 热门结果
- 基础池并集
- 年线 / 优质 / 融资
- `Shouban30` 缠论数值指标
- `Chanlun` 周期与信号 membership

这套结构既满足前端自由组合交集的目标，也满足 Dagster 可观察、可补跑、可排障的运行要求。
