---
name: agent-docs-index
description: FreshQuant AI 助手文档索引。列出了所有面向 AI 编码助手的参考文档，涵盖信号函数、行情数据获取、股票池与持仓管理等核心模块的使用指南。
---

> NOTE (Windows PowerShell 5.1): If Chinese looks garbled in `cat/type`, run: `. .\script\pwsh_utf8.ps1`

# FreshQuant AI 助手文档索引

本文档目录包含面向 AI 编码助手的技术参考文档。当 AI 需要编写与 FreshQuant 相关的代码时，应根据任务类型查阅对应文档。

## 建议阅读顺序（新接入/换人接手）

1. `项目目标与代码现状调研.md`：先对齐“本期迁移目标 + 当前代码/入口/依赖/CI 门禁”
2. `旧仓库freshquant-重点迁移模块调研.md`：理解“旧仓库实现/数据流/接口/存储”，为后续 RFC 拆分与迁移验收打底
3. 再按任务类型查阅下方具体模块文档（信号、行情、股票池、配置等）

## 核心文档

### [项目目标与代码现状调研](./项目目标与代码现状调研.md)
`project-goals-and-codebase-survey`

**用途**：快速掌握“本仓库的迁移治理目标”与“当前代码现状/关键入口/集成点”。

**适用场景**：
- 开始迁移/重构前做范围界定
- 需要定位关键入口（CLI/API/worker/web）与外部依赖（MongoDB/Redis/MiniQMT）
- 编写/评审 RFC 前的背景调研

**关键内容**：
- 迁移治理规则（RFC + progress + breaking changes）
- 仓库组成（freshquant/morningglory/sunflower/ikebana）
- 关键入口与运行形态（fqctl、TDX 网关、rear API、Dagster、Huey worker）

---

### [旧仓库freshquant-重点迁移模块调研](./旧仓库freshquant-重点迁移模块调研.md)
`legacy-freshquant-migration-modules-survey`

**用途**：掌握旧仓库 `D:\fqpack\freshquant` 的代码结构与运行逻辑，聚焦 10 个后续重点迁移模块。

**适用场景**：
- 拆分 RFC（按“模块边界/输入输出/依赖/验收”）
- 定位旧实现入口（producer/consumer、guardian、stoploss、gantt、KlineSlim 等）
- 迁移对齐对外契约（API/WS/Redis key/Mongo collections）与验收口径

**关键内容**：
- xtdata 生产者/消费者模式（tick → bar 事件 → fullcalc → Redis cache + Pub/Sub）
- guardian / grid / stoploss / position 风控链路
- 订单管理：Redis 队列优先级（high/normal/low）+ broker/puppet 执行 + `xt_orders/xt_trades` 落库 + remark 追踪
- 结构化日志（JSONL）+ SystemLogs 可视化
- KlineSlim：前端 3 级缓存 + WebSocket 实时刷新 + 后端 `/api/stock_data`
- XGB/JYGS 数据同步与甘特图数据结构（plates/stocks matrix）
- 30 日热门（Shouban30）导出 + 缠论 calc/cache/filter + 预选池/blk 闭环

---

### [信号函数-CLXS系列](./信号函数-CLXS系列.md)
`signal-clxs-functions`

**用途**：缠论信号计算

**适用场景**：
- 股票筛选与选股系统
- MACD 背驰信号识别
- 中枢拉回信号识别
- V 型反转信号识别

**关键内容**：
- `fq_clxs` 函数签名与参数
- `model_opt` 信号模型类型表
- 止损价格计算方法
- 配合 `fq_recognise_bi` 使用

---

### [行情数据获取指南](./行情数据获取指南.md)
`market-data-fetching`

**用途**：A 股行情数据获取

**适用场景**：
- 技术分析需要历史数据
- 选股系统需要行情数据
- 信号计算需要 OHLCV 数据

**关键内容**：
- 交易日历获取 `fq_trading_fetch_trade_dates`
- 股票列表获取 `fq_inst_fetch_stock_list`
- 日线/分钟线数据获取 `fq_data_stock_fetch_day/min`
- 数据源与缓存策略

---

### [股票池与持仓数据获取指南](./股票池与持仓数据获取指南.md)
`stock-pool-and-position`

**用途**：股票池与持仓数据管理

**适用场景**：
- 选股后保存候选股票池
- 读取股票池进行监控
- 获取持仓数据进行分析
- 组合监控代码集合

**关键内容**：
- 候选股票池 (`stock_pre_pools`) 操作
- 股票池 (`stock_pools`) 操作
- 必选池 (`must_pool`) 查询
- 持仓数据 (`stock_fills`) 获取

---

### [ETF行情数据获取指南](./ETF行情数据获取指南.md)
`etf-market-data-fetching`

**用途**：ETF 行情数据获取

**适用场景**：
- 获取 ETF 历史行情数据
- 处理混合持仓（A 股 + ETF）
- ETF 信号计算

**关键内容**：
- ETF 日线/分钟线获取 `queryEtfCandleSticksDay/min`
- ETF vs A 股数据获取差异对比
- 标的类型判断方法

---

### [配置管理指南](./配置管理指南.md)
`config-management`

**用途**：配置管理与环境变量

**适用场景**：
- 需要从配置文件获取参数
- Docker 环境下配置 API 地址
- 环境变量覆盖配置

**关键内容**：
- dynaconf 配置系统用法
- 环境变量命名规范 `freshquant_<SECTION>__<KEY>`
- API 地址配置模式

---

### [Docker并行部署指南](./Docker并行部署指南.md)
`docker-parallel-deployment`

**用途**：宿主机旧项目已占用端口时，本仓库用 Docker **并行运行**（端口隔离 + 最小验证 + 排障）。

**适用场景**：
- `D:\\fqpack\\freshquant` 在宿主机运行中，仍需启动 `D:\\fqpack\\freshquant-2026.2.23` 做迁移/验证
- 避免端口冲突（80/5000/5001/6379/27017 等）

**关键内容**：
- Compose 文件：`docker/compose.parallel.yaml`
- 并行端口映射：Web UI 18080 / API 15000 / TDXHQ 15001 / Dagster 11003 / Redis 6380 / Mongo 27027

---

## 按任务类型查找

| 任务类型 | 参考文档 |
|---------|---------|
| 使用缠论信号计算 | [信号函数-CLXS系列](./信号函数-CLXS系列.md) |
| 获取 A 股历史行情数据 | [行情数据获取指南](./行情数据获取指南.md) |
| 获取 ETF 历史行情数据 | [ETF行情数据获取指南](./ETF行情数据获取指南.md) |
| 保存选股结果到候选池 | [股票池与持仓数据获取指南](./股票池与持仓数据获取指南.md) |
| 获取持仓数据 | [股票池与持仓数据获取指南](./股票池与持仓数据获取指南.md) |
| 计算止损价格 | [信号函数-CLXS系列](./信号函数-CLXS系列.md#止损价格计算) |
| 批量处理股票数据 | [行情数据获取指南](./行情数据获取指南.md#批量处理模式) |
| 判断标的类型（A 股/ETF） | [ETF行情数据获取指南](./ETF行情数据获取指南.md#判断标的类型) |
| 使用配置文件/环境变量 | [配置管理指南](./配置管理指南.md) |
| Docker 环境 API 配置 | [配置管理指南](./配置管理指南.md#docker-环境配置) |
| Docker 并行部署（与宿主机并行） | [Docker并行部署指南](./Docker并行部署指南.md) |
| 了解项目目标/代码现状 | [项目目标与代码现状调研](./项目目标与代码现状调研.md) |
| 了解旧仓库实现/迁移对象 | [旧仓库freshquant-重点迁移模块调研](./旧仓库freshquant-重点迁移模块调研.md) |

## 使用说明

1. **开始编码前**：先查阅相关文档了解函数签名和用法
2. **遇到问题时**：参考文档中的完整示例代码
3. **数据结构不明确时**：查看文档中的数据结构表
4. **需要最佳实践时**：参考文档中的"注意事项"部分

## 文档规范

所有文档采用 YAML frontmatter 格式：

```yaml
---
name: document-id
description: 文档描述，说明内容和适用场景
---
```

AI 可通过读取 frontmatter 快速识别文档用途。
