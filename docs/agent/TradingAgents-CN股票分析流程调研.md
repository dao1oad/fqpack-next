---
name: tradingagents-cn-analysis-flow-survey
description: TradingAgents-CN 股票分析全流程代码调研，聚焦调用链、本地数据依赖、Mongo/Redis 读写与后续可替换切入点。
---

# TradingAgents-CN 股票分析流程调研

## 1. 调研目标

本调研用于回答三个问题：

1. `TradingAgents-CN` 的股票分析全流程是如何跑起来的。
2. 哪些分析步骤依赖本地数据支持，哪些可以在线回退。
3. 后续若要用 FreshQuant 数据替换，应优先替换哪一层。

本轮调研结论仅用于阶段 1 和后续 RFC 设计，不涉及实现替换。

## 2. 调研基线

- 调研日期：2026-03-06
- 上游仓库：`https://github.com/hsliuping/TradingAgents-CN`
- 调研基线提交：`bd599607e83cd0d249482e57869216d52b1cb2aa`
- 调研方式：本地临时克隆 + 代码静态阅读

## 3. 结论摘要

`TradingAgents-CN` 的股票分析不是单次函数调用，而是“任务系统 + 数据准备 + 多智能体图”的完整闭环。

最关键的结论有四条：

1. A 股分析前一定会先经过 `prepare_stock_data_async(...)`。
2. 这一步当前强依赖本地 Mongo 缓存检查；本地不足时会触发按股票补数。
3. 市场分析师和基本面分析师是数据依赖最重的两个节点。
4. Redis 主要用于任务队列和进度，不是行情数据源。

因此，后续如果要替换为 FreshQuant 数据，最先替换的应当是 A 股数据准备和统一数据入口，而不是分析图本身。

## 4. 主调用链

### 4.1 API 入口

后端主入口位于：

- `app/routers/analysis.py`

当前主路径是：

1. `POST /single`
2. `get_simple_analysis_service().create_analysis_task(...)`
3. `BackgroundTasks` 异步调用 `execute_analysis_background(...)`

### 4.2 后台任务执行

核心服务位于：

- `app/services/simple_analysis_service.py`

关键步骤：

1. 创建任务 ID
2. 写内存任务状态
3. 写 Mongo `analysis_tasks`
4. 调用 `prepare_stock_data_async(...)`
5. 初始化 RedisProgressTracker
6. 调用 `_execute_analysis_sync(...)`
7. 保存最终分析结果

### 4.3 分析图入口

分析引擎位于：

- `tradingagents/graph/trading_graph.py`

真正的全流程入口是：

- `TradingAgentsGraph.propagate(company_name, trade_date, progress_callback, task_id)`

## 5. 分析图顺序

图结构定义位于：

- `tradingagents/graph/setup.py`
- `tradingagents/graph/conditional_logic.py`

默认分析阶段顺序如下：

1. `Market Analyst`
2. `Social Analyst`
3. `News Analyst`
4. `Fundamentals Analyst`
5. `Bull Researcher`
6. `Bear Researcher`
7. `Research Manager`
8. `Trader`
9. `Risky Analyst`
10. `Safe Analyst`
11. `Neutral Analyst`
12. `Risk Judge`

其中：

- 各分析师节点会先让 LLM 决定是否调用工具；
- 工具调用完成后回到对应分析师；
- 研究员和风控员之间有轮次控制；
- 最终由风险裁决节点产出最终策略结论。

## 6. 数据准备 gate

### 6.1 统一入口

股票数据准备入口位于：

- `tradingagents/utils/stock_validator.py`

统一入口：

- `prepare_stock_data_async(stock_code, market_type, period_days, analysis_date)`

流程为：

1. 校验股票代码格式
2. 自动识别市场类型
3. 按市场进入不同准备逻辑

### 6.2 A 股准备逻辑

A 股路径位于：

- `_prepare_china_stock_data_async(...)`

关键步骤：

1. 根据 `MARKET_ANALYST_LOOKBACK_DAYS` 计算实际回看区间
2. 调用 `_check_database_data(...)` 检查 Mongo 历史数据是否存在、是否够新
3. 若本地数据不足，调用 `_trigger_data_sync_async(...)`
4. 读取股票基础信息
5. 再次读取历史数据并判断是否可用于分析

这说明：

- A 股分析启动前，当前实现会强制先确认“本地数据可用”
- 若本地数据不可用，则会按其原生逻辑补数后再继续

### 6.3 A 股补数内容

`_trigger_data_sync_async(...)` 当前会按优先级尝试数据源，并补三类数据：

1. 历史行情
2. 财务/基本面数据
3. 实时行情快照

因此，A 股的“按需分析”本质上是“按股票触发补数后分析”，不是纯在线直取。

### 6.4 港股 / 美股

港股和美股路径相对更轻：

- 港股更多直接走 provider 获取并校验返回内容
- 美股更多直接走 provider / cache 获取

相比之下，A 股对“本地缓存或本地补数”的依赖更强。

## 7. 各分析阶段对本地数据的依赖

| 阶段 | 主要入口 | 是否依赖本地数据 | 说明 |
|---|---|---|---|
| 数据准备 | `prepare_stock_data_async` | 强依赖 | A 股先查本地 Mongo，不足就补数 |
| 市场分析 | `get_stock_market_data_unified` | 强依赖 | 需要历史 K 线、最近价格、技术指标原料 |
| 基本面分析 | `get_stock_fundamentals_unified` | 强依赖 | 需要最近价格 + 财务/估值信息 |
| 新闻分析 | `get_stock_news_unified` | 中等依赖 | 优先读本地新闻，缺失时会尝试同步/回退 |
| 社交分析 | `get_stock_sentiment_unified` | 弱依赖 | A 股当前更多是轻量或占位逻辑 |
| 研究辩论/交易/风控 | 图内部状态 | 不直接依赖 | 主要消费前面阶段产出的文本报告 |

## 8. 当前本地数据读取入口

### 8.1 统一数据管理器

核心入口位于：

- `tradingagents/dataflows/data_source_manager.py`

关键方法：

- `get_stock_data(...)`
- `get_stock_info(...)`
- `get_fundamentals_data(...)`
- `get_news_data(...)`

当前总体策略是：

- 优先读 Mongo 缓存
- 不命中或质量不足时回退到 provider

### 8.2 市场数据

市场分析工具最终会落到：

- `get_china_stock_data_unified(...)`
- `DataSourceManager.get_stock_data(...)`

其返回内容包含：

- 历史行情
- 最近价格
- 技术指标格式化结果

### 8.3 基本面数据

基本面分析工具位于：

- `tradingagents/agents/utils/agent_utils.py`

对 A 股的逻辑是：

1. 先抓最近 1-2 天价格
2. 再生成基本面分析报告

本地可命中的关键集合包括：

- `stock_basic_info`
- `market_quotes`

### 8.4 新闻数据

统一新闻工具位于：

- `tradingagents/tools/unified_news_tool.py`

逻辑为：

1. 先读本地 `stock_news`
2. 没有则尝试同步新闻到库
3. 再没有则回退其他新闻来源

## 9. Mongo / Redis 的职责区别

### 9.1 Redis

Redis 当前主要负责：

- 任务进度
- 状态跟踪
- 队列 / pubsub

Redis 不是当前股票分析所需行情的核心来源。

### 9.2 Mongo

Mongo 既承担业务存储，也承担分析所需缓存：

- `analysis_tasks`
- `stock_basic_info`
- `market_quotes`
- `stock_news`
- `system_configs`

对 A 股分析来说，Mongo 不只是“结果存储”，也是启动分析前的数据 gate。

## 10. 对 FreshQuant 的含义

### 10.1 阶段 1

阶段 1 不替换任何数据接口时，应保证：

- `TradingAgents-CN` 能使用自己的 Mongo / Redis
- 其 A 股本地缓存检查逻辑可用
- 本地不足时其按股票补数逻辑可用
- 完整分析图能走完并输出最终结果

### 10.2 后续替换优先级

后续若要用 FreshQuant 数据替换，优先级应为：

1. `prepare_stock_data_async(...)`
2. `get_china_stock_data_unified(...)`
3. `get_stock_fundamentals_unified(...)`

不建议先动：

- `TradingAgentsGraph`
- 各分析师 prompt
- 研究/交易/风控节点顺序

原因很直接：

- 图本身负责推理协作，不负责数据取数
- 先替换数据入口，风险最小，行为也最可控

## 11. 与 FreshQuant 现有数据能力的对照

当前 FreshQuant 已有较成熟的 A 股行情能力：

- `freshquant/data/stock.py`
- `freshquant/KlineDataTool.py`
- `freshquant/rear/stock/routes.py`
- `freshquant/market_data/xtdata/strategy_consumer.py`

已有能力主要覆盖：

- 历史 K 线
- 分钟线
- Redis 实时缓存
- Mongo `stock_realtime/index_realtime`

但当前未发现与 `TradingAgents-CN` 等价的统一“基本面 + 股票基础信息 + 新闻”正式数据层。

因此：

- 阶段 1 先保留 `TradingAgents-CN` 原生数据逻辑是合理的
- 阶段 2 最可能先替换的是 A 股行情入口，不是完整基本面/新闻层

## 12. 当前建议

当前建议按两阶段推进：

### 阶段 1

- 不替换数据接口
- 保持 `TradingAgents-CN` 原生本地数据逻辑
- 先把“单股分析可闭环完成”跑通

### 阶段 2

- 再单独起 RFC
- 逐步用 FreshQuant 数据替换 A 股数据准备和市场数据入口
- 最后再考虑基本面、新闻和结果融合
