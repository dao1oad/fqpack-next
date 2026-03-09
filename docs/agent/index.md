---
name: agent-docs-index
description: FreshQuant AI 助手文档索引，覆盖目标仓当前代码现状、迁移治理、旧仓参考实现与各专项使用指南。
---

> NOTE (Windows PowerShell 5.1): 如果 `cat/type` 中文乱码，先执行：`. .\script\pwsh_utf8.ps1`

# FreshQuant AI 助手文档索引

本文档是 AI 编码助手和新接手开发者的统一入口。请先区分两类文档：

- **当前事实**：目标仓当前代码、运行方式、治理规则
- **旧仓参考**：旧仓 `D:\fqpack\freshquant` 的实现细节，仅用于迁移映射和 RFC 背景调研

## 当前状态快照（2026-03-09）

- 目标仓是 `D:\fqpack\freshquant-2026.2.23`
- `docs/migration/progress.md` 中 `0001` 到 `0025` 当前均已登记
- 已落地核心能力包括：
  - XTData producer/consumer
  - ETF `qfq`
  - 订单管理 / 仓位管理 / TPSL
  - Gantt / Shouban30 读模型与页面
  - KlineSlim
  - 运行观测与日志可视化（`/api/runtime/*` + `/runtime-observability`）
  - TradingAgents-CN 并行部署与配置治理
- 旧仓调研文档仍然重要，但不代表当前代码事实

## 建议阅读顺序（新接入 / 换人接手）

1. [项目目标与代码现状调研](./项目目标与代码现状调研.md)
2. [迁移进度（progress）](../migration/progress.md)
3. [破坏性变更清单](../migration/breaking-changes.md)
4. 按任务进入对应专项文档
5. 需要理解旧实现时，再读 [旧仓库freshquant-重点迁移模块调研](./旧仓库freshquant-重点迁移模块调研.md)

## 核心文档

### [项目目标与代码现状调研](./项目目标与代码现状调研.md)
`project-goals-and-codebase-survey`

**用途**：快速掌握目标仓当前代码现状、关键入口、配置/存储分层、测试与治理基线。

**适用场景**：

- 开始迁移/重构前做范围界定
- 需要定位 CLI/API/worker/web 入口
- 编写或评审 RFC 前做当前事实确认

**关键内容**：

- 目标仓当前迁移现状快照
- 仓库结构（`freshquant` / `morningglory` / `sunflower` / `third_party`）
- 关键入口与运行链路
- 配置、Mongo/Redis 分层与 CI 门禁

---

### [迁移进度（progress）](../migration/progress.md)

**用途**：查看各 RFC 当前状态、对应模块、更新时间与已落地范围。

**适用场景**：

- 判断某个迁移单元是否已经做完
- 评估当前代码的迁移覆盖范围
- 开始新任务前避免重复设计

---

### [破坏性变更清单](../migration/breaking-changes.md)

**用途**：查看已经落地的接口、配置、数据结构和行为语义调整。

**适用场景**：

- 修改 CLI / API / 配置 / 数据结构前核对已有不兼容调整
- 回滚、排障、部署前确认迁移步骤

---

### [旧仓库freshquant-重点迁移模块调研](./旧仓库freshquant-重点迁移模块调研.md)
`legacy-freshquant-migration-modules-survey`

**用途**：理解旧仓 `D:\fqpack\freshquant` 的 10 个重点模块实现、数据流、存储结构与迁移映射。

**适用场景**：

- 拆分 RFC
- 定位旧实现入口
- 对齐旧接口契约与验收口径

**关键提醒**：

- 文档主体以旧仓实现为主
- 顶部“迁移状态追加”用于说明目标仓当前落点
- 若与当前代码冲突，以当前代码和 `progress.md` 为准

---

### [Docker并行部署指南](./Docker并行部署指南.md)
`docker-parallel-deployment`

**用途**：在宿主机旧仓仍运行时，用 Docker 并行启动目标仓和 TradingAgents-CN。

**适用场景**：

- 避免端口冲突
- 验证目标仓新能力
- 部署 TradingAgents-CN 并行环境

**关键内容**：

- `docker/compose.parallel.yaml`
- 并行端口：Web `18080` / API `15000` / TDXHQ `15001` / Dagster `11003` / Redis `6380` / Mongo `27027`
- TradingAgents：`13000` / `13080`

---

### [配置管理指南](./配置管理指南.md)
`config-management`

**用途**：说明 Dynaconf、环境变量和订单域分库配置等现有配置体系。

**适用场景**：

- 需要读取或覆盖配置
- Docker 环境下设置 API / Mongo / Redis
- 对齐 `order_management` 等独立分库配置

---

### [TradingAgents-CN接入与运行说明](./TradingAgents-CN接入与运行说明.md)
`tradingagents-cn-integration-guide`

**用途**：说明如何在本仓库中启动 `ta_backend` / `ta_frontend`，并按当前配置治理语义完成登录、提交分析和排障。

**适用场景**：

- 启动 TradingAgents-CN
- 校验端口、Mongo、Redis 隔离
- 用 PowerShell 验证单股分析链路

**关键内容**：

- Docker 并行启动
- 根 `.env` 单一真相源
- Mongo `tradingagents_cn`
- Redis `db 8`

---

### [TradingAgents-CN股票分析流程调研](./TradingAgents-CN股票分析流程调研.md)
`tradingagents-cn-analysis-flow-survey`

**用途**：理解 TradingAgents-CN 从 FastAPI 请求进入、数据准备、任务系统到多智能体分析图的调用链。

**适用场景**：

- 评审 TradingAgents 相关 RFC
- 判断阶段 2 的数据替换切入点

---

### [股票池与持仓数据获取指南](./股票池与持仓数据获取指南.md)
`stock-pool-and-position`

**用途**：说明 `stock_pre_pools`、`stock_pools`、`must_pool` 以及当前持仓读取口径。

**适用场景**：

- 获取监控标的集合
- 读取当前持仓
- 理解股票池与订单域持仓投影的关系

---

### [Symphony本地安装与使用指南](./Symphony本地安装与使用指南.md)
`symphony-local-installation-guide`

**用途**：说明如何在 Windows 本机安装 OpenAI `Symphony` 官方 Elixir 参考实现，并给出在 FreshQuant 项目中的推荐使用边界。

**适用场景**：

- 本机验证 `Symphony` 是否可运行
- 需要 `memory` tracker 的最小 smoke test
- 评估未来是否要把多 agent 工作编排纳入本项目 RFC

---

### [行情数据获取指南](./行情数据获取指南.md)
`market-data-fetching`

**用途**：A 股行情数据获取与使用方式。

---

### [ETF行情数据获取指南](./ETF行情数据获取指南.md)
`etf-market-data-fetching`

**用途**：ETF 行情数据获取与与 A 股差异说明。

---

### [信号函数-CLXS系列](./信号函数-CLXS系列.md)
`signal-clxs-functions`

**用途**：缠论信号函数签名、模型类型和止损价格计算说明。

## 按任务类型查找

| 任务类型 | 参考文档 |
|---------|---------|
| 了解项目目标 / 代码现状 | [项目目标与代码现状调研](./项目目标与代码现状调研.md) |
| 查看迁移进度 | [迁移进度（progress）](../migration/progress.md) |
| 查看破坏性变更 | [破坏性变更清单](../migration/breaking-changes.md) |
| 了解旧仓库实现 / 迁移对象 | [旧仓库freshquant-重点迁移模块调研](./旧仓库freshquant-重点迁移模块调研.md) |
| Docker 并行部署 | [Docker并行部署指南](./Docker并行部署指南.md) |
| 配置文件 / 环境变量 | [配置管理指南](./配置管理指南.md) |
| 启动并运行 TradingAgents-CN | [TradingAgents-CN接入与运行说明](./TradingAgents-CN接入与运行说明.md) |
| 调研 TradingAgents-CN 调用链 | [TradingAgents-CN股票分析流程调研](./TradingAgents-CN股票分析流程调研.md) |
| 获取 A 股历史行情 | [行情数据获取指南](./行情数据获取指南.md) |
| 获取 ETF 历史行情 | [ETF行情数据获取指南](./ETF行情数据获取指南.md) |
| 获取股票池与持仓 | [股票池与持仓数据获取指南](./股票池与持仓数据获取指南.md) |
| 使用缠论信号函数 | [信号函数-CLXS系列](./信号函数-CLXS系列.md) |
| 本机安装/评估 OpenAI Symphony | [Symphony本地安装与使用指南](./Symphony本地安装与使用指南.md) |

## 使用说明

1. 开始编码前，先读“当前事实”文档，避免把旧仓实现当成目标仓现状。
2. 需要迁移旧能力时，先读旧仓调研，再回到 `progress.md` / RFC 判断是否已经落地。
3. 触及 CLI / API / 配置 / 数据结构时，务必同步检查 `breaking-changes.md`。

## 文档规范

所有 agent 文档采用 YAML frontmatter：

```yaml
---
name: document-id
description: 文档描述
---
```

AI 可据此快速识别文档用途与适用场景。
