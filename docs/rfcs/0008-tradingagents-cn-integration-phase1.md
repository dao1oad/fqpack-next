# RFC 0008: TradingAgents-CN 集成（阶段 1：保持原生本地数据逻辑可用）

- **状态**：Done
- **负责人**：Codex
- **评审人**：TBD
- **创建日期**：2026-03-06
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

目标仓库 `D:\fqpack\freshquant-2026.2.23` 需要引入第三方项目 `TradingAgents-CN`，并在本仓库的 Docker 并行部署体系下运行，用于提供“股票分析全流程”能力，最终输出完整分析结果。

经代码调研，`TradingAgents-CN` 的股票分析并不是简单的 LLM 调用，而是完整的多智能体工作流：

- FastAPI 后端接收分析请求并创建任务；
- 进入 `prepare_stock_data_async(...)` 进行股票校验、数据准备与必要的本地补数；
- 进入 `TradingAgentsGraph.propagate(...)`，依次执行市场/社交/新闻/基本面分析师、研究辩论、交易员、风险辩论与风险裁决；
- 将进度写入 Redis，将任务/结果/配置与数据缓存写入 MongoDB。

当前用户已经明确本次阶段 1 的边界：

- 不替换 `TradingAgents-CN` 的任何数据接口；
- 先保证它按照自身设计的“本地缓存 + 按需补数 + 全流程分析”逻辑可用；
- 仅集成 `v1.0.0-preview` 的 `FastAPI backend + Vue frontend`；
- 复用 Docker 中现有的 `fq_mongodb` / `fq_redis`，但使用独立 MongoDB 库名与 Redis DB 号隔离；
- `web/` 源码保留，但不单独运行 Streamlit 服务。

因此，本 RFC 需要明确：

- 第三方源码如何受控纳入本仓库；
- Docker 运行边界如何定义；
- `TradingAgents-CN` 自身的数据获取、缓存、补数逻辑在本仓库中的保留范围；
- 阶段 1 的验收口径是什么。

## 2. 目标（Goals）

- 将 `TradingAgents-CN` 作为受控第三方源码纳入本仓库，供后续集成与升级。
- 在本仓库 Docker 并行部署体系下启动其 `backend + frontend`。
- 复用当前 Docker 中的 `fq_mongodb` / `fq_redis`，但做逻辑隔离：
  - MongoDB：`tradingagents_cn`
  - Redis：`db 8`
- 保持 `TradingAgents-CN` 原生股票分析入口、任务流转、进度写入、结果写入、缓存读取、启动同步与数据准备逻辑可用。
- 保持 `TradingAgents-CN` 原生 A 股数据准备路径可用：
  - 先查本地 Mongo 缓存；
  - 不足时按其自身逻辑触发补数；
  - 之后进入完整分析图并输出最终结果。
- 为后续“使用本项目数据替换 TradingAgents-CN 数据层”预留清晰替换点，但不在本阶段实施。

## 3. 非目标（Non-Goals）

- 本阶段不使用 FreshQuant 现有行情/缓存/基本面接口替换 `TradingAgents-CN` 数据入口。
- 本阶段不修改 `TradingAgentsGraph` 的分析节点、提示词、工作流顺序和最终决策逻辑。
- 本阶段不将 `TradingAgents-CN` 的页面、路由或 API 合并到 FreshQuant 现有前后端中。
- 本阶段不运行 `web/` Streamlit 入口。
- 本阶段不统一两边 Mongo collection schema、Redis key 规范或任务模型。
- 本阶段不解决后续单点登录、权限统一、页面集成、API 统一网关等问题。
- 本阶段不以“减少本地存储占用”作为设计约束，不主动为了控库而裁剪上游原生同步行为。

## 4. 范围（Scope）

**In Scope**

- 在仓库中新增受控第三方源码目录，保存 `TradingAgents-CN` 上游代码。
- 新增 `TradingAgents-CN` 的 Docker 编排、环境变量与运行目录挂载。
- 接入共享的 `fq_mongodb` / `fq_redis`，并配置独立库/DB 号。
- 保留 `TradingAgents-CN` 的分析任务、进度跟踪、结果保存、Mongo 缓存读取、按需补数、启动同步与调度逻辑。
- 明确并记录 A 股分析流程中哪些步骤依赖本地数据。
- 为后续替换本项目数据层编写调研文档，但不落地替换代码。

**Out of Scope**

- 把 `TradingAgents-CN` 改造成 FreshQuant 内部模块或公共 Python API。
- 把 `TradingAgents-CN` 所有 Mongo/Redis 数据迁移进 FreshQuant 既有 schema。
- 在本阶段完成对 `TradingAgents-CN` 的性能优化、提示词优化、模型切换治理。
- 在本阶段不把 `TradingAgents-CN` 改造成 FreshQuant 的统一行情/基本面主数据仓库。

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- `FreshQuant` 仓库负责：
  - 托管第三方源码；
  - 负责 Docker 编排、运行环境与基础设施接入；
  - 提供清晰的存储隔离；
  - 记录调研、RFC、迁移进度与后续替换边界。
- `TradingAgents-CN` 负责：
  - 保持自身分析工作流、任务状态机、数据准备与本地缓存/补数逻辑；
  - 保持自身启动同步、定时同步、配置读取和任务调度语义；
  - 保持自身 Mongo / Redis 数据模型与前后端契约。

**不负责（Must Not）**

- 不在阶段 1 内改写 `TradingAgents-CN` A 股行情、基本面、新闻数据接口为 FreshQuant 接口。
- 不在阶段 1 内承诺 `TradingAgents-CN` 与 FreshQuant 共享同一数据 schema。
- 不在阶段 1 内将其结果纳入 FreshQuant 现有页面或业务流程。

**依赖（Depends On）**

- `docker/compose.parallel.yaml` 所在的并行部署体系；
- `fq_mongodb` 容器；
- `fq_redis` 容器；
- `TradingAgents-CN` 上游源码；
- 可用的 LLM 配置；
- 至少一种可用的 A 股数据源能力（例如 Tushare / AKShare / BaoStock 中的一种或多种）。

**禁止依赖（Must Not Depend On）**

- 不依赖 FreshQuant 现有 `freshquant/data/*`、`freshquant/market_data/*` 作为阶段 1 必选数据源；
- 不依赖旧仓库 `D:\fqpack\freshquant` 的宿主机进程或其本地数据目录；
- 不依赖运行 `TradingAgents-CN/web` Streamlit 服务。

## 6. 对外接口（Public API）

本 RFC 新增的是“运行入口”，不是 FreshQuant 现有 API 的破坏性变更。

- 新增 Docker 服务：
  - `ta_backend`
  - `ta_frontend`
- 新增访问入口（端口待实现时最终确定）：
  - `ta_backend` HTTP API
  - `ta_frontend` Web UI
- 保持 `TradingAgents-CN` 后端原生 API 语义：
  - 提交单股分析任务；
  - 查询任务状态与进度；
  - 获取最终分析结果。
- FreshQuant 现有对外 API 不改名、不兼容改造、不复用同一路由。

错误语义：

- 若 `TradingAgents-CN` 自身股票校验失败，应返回其原生错误信息。
- 若 Mongo / Redis / 数据源不可用，应由其自身服务返回失败状态，不由 FreshQuant 包装或吞错。

兼容策略：

- 阶段 1 以“保持第三方行为”为主，不重写其错误码、响应体和任务状态语义。

## 7. 数据与配置（Data / Config）

源码与运行目录：

- 第三方源码目录：`third_party/tradingagents-cn/`
- 运行期目录：
  - `runtime/tradingagents-cn/logs`
  - `runtime/tradingagents-cn/data`
  - `runtime/tradingagents-cn/config`

MongoDB / Redis 隔离：

- MongoDB 主机：`fq_mongodb:27017`
- MongoDB 库名：`tradingagents_cn`
- Redis 主机：`fq_redis:6379`
- Redis DB：`8`

需接入并明确的关键配置：

- `MONGODB_ENABLED=true`
- `MONGODB_HOST=fq_mongodb`
- `MONGODB_PORT=27017`
- `MONGODB_DATABASE=tradingagents_cn`
- `REDIS_ENABLED=true`
- `REDIS_HOST=fq_redis`
- `REDIS_PORT=6379`
- `REDIS_DB=8`
- `TA_USE_APP_CACHE=true`

阶段 1 的同步/缓存策略：

- 以 `TradingAgents-CN` 上游原生行为为准，不主动为了减少写入而裁剪启动同步与定时同步；
- 允许保留其“应用启动即触发一次股票基础信息同步”的现状；
- 允许保留其原生行情、财务、新闻、本地缓存与按需补数逻辑；
- 隔离手段以独立 MongoDB 库名和 Redis DB 号为主，而不是通过关闭同步任务来减写。

阶段 1 保留的关键本地数据路径：

- 任务与结果：
  - `analysis_tasks`
- A 股基础信息：
  - `stock_basic_info`
- A 股行情快照：
  - `market_quotes`
- 新闻缓存：
  - `stock_news`
- 系统配置：
  - `system_configs`

阶段 1 保留的关键原生数据逻辑：

- `prepare_stock_data_async(...)`
- `_prepare_china_stock_data_async(...)`
- `_check_database_data(...)`
- `_trigger_data_sync_async(...)`
- `DataSourceManager.get_stock_data(...)`
- `DataSourceManager.get_fundamentals_data(...)`
- `UnifiedNewsAnalyzer.get_stock_news_unified(...)`

已确认的重要现状：

- `TradingAgents-CN` 的 A 股分析启动前会先做本地 Mongo 检查；
- 本地数据不足时会触发历史、财务、实时行情补数；
- `app/main.py` 当前包含一次“应用启动即触发股票基础信息全量同步”的逻辑，即使 `SYNC_STOCK_BASICS_ENABLED=false` 也不会阻止该一次性启动任务；
- 阶段 1 已确认保留该行为，以优先保证上游原生分析流程跑通。

## 8. 破坏性变更（Breaking Changes）

对 FreshQuant 现有外部接口：

- 无直接破坏性变更。

对仓库结构与部署形态：

- 新增第三方源码目录与新 Docker 服务；
- 仓库体积会增加；
- Docker Compose 将新增 `TradingAgents-CN` 相关服务与环境变量。

迁移步骤：

1. 将第三方源码纳入仓库；
2. 增加 Docker 服务与运行目录挂载；
3. 配置 Mongo / Redis 隔离；
4. 联通其原生数据准备与分析流程；
5. 完成阶段 1 验收后，再另起 RFC 讨论数据层替换。

回滚方案：

- 回滚 `TradingAgents-CN` 新增服务与编排；
- 保留 FreshQuant 原有并行部署与业务功能不受影响；
- `tradingagents_cn` Mongo 数据库与 Redis `db 8` 可独立清理，不影响 FreshQuant 既有数据。

## 9. 迁移映射（From `D:\fqpack\freshquant`）

本 RFC 不是从旧仓库 `D:\fqpack\freshquant` 迁移已有模块，而是新增受控第三方能力。

- 旧仓库来源：N/A
- 外部来源：`TradingAgents-CN`
- 新归属：
  - 第三方源码：`third_party/tradingagents-cn/`
  - 运行时集成：Docker 并行部署体系
  - 调研文档：`docs/agent/`

## 10. 测试与验收（Acceptance Criteria）

- [x] Docker 编排可启动 `ta_backend` / `ta_frontend`，并成功连接 `fq_mongodb` / `fq_redis`。
- [x] `TradingAgents-CN` 能在 `MongoDB=tradingagents_cn`、`Redis=db 8` 下正常初始化索引、配置与任务状态。
- [x] 在 `tradingagents_cn` 库为空的情况下，提交一只 A 股分析任务时，`prepare_stock_data_async(...)` 能按其原生逻辑完成：
  - 先检查本地缓存；
  - 本地不足时按需补数；
  - 之后继续进入完整分析图。
- [x] 单股分析任务能完整走完市场/社交/新闻/基本面/研究/交易/风控全流程，并返回最终分析结果。
- [x] 任务执行期间，Redis 进度数据可见；Mongo 中任务状态和结果可查询。
- [x] 同一股票二次分析时，可复用已写入的本地数据缓存，不需要人工预热。
- [x] FreshQuant 现有服务与端口不受影响。

## 11. 风险与回滚（Risks / Rollback）

- 风险点：`TradingAgents-CN` 的 A 股可用性依赖其自身数据源和凭证，尤其是 Tushare Token 与 AKShare/BaoStock 可用性。
- 风险点：其存在“应用启动即尝试一次基础信息全量同步”的现状，会带来较大初始化写入量和较长首启时间。
- 风险点：其 `TA_USE_APP_CACHE`、MongoDB cache adapter、sync service、分析入口之间耦合较深，阶段 1 若同时尝试裁剪会增加排障成本。
- 缓解：
  - 阶段 1 不替换数据接口，并保留上游原生同步行为；
  - 通过独立 MongoDB 库 `tradingagents_cn` 与 Redis `db 8` 做逻辑隔离；
  - 先以“单股分析闭环可用”为验收口径；
  - 后续用独立 RFC 处理数据层替换和调度裁剪。
- 回滚：
  - 下线新增 Docker 服务；
  - 清理 `tradingagents_cn` Mongo 库与 Redis `db 8`；
  - 不影响 FreshQuant 原生模块。

## 12. 里程碑与拆分（Milestones）

- M1：RFC 评审通过
- M2：第三方源码入库 + Docker 服务可启动
- M3：Mongo / Redis 隔离联通
- M4：A 股单股分析按原生数据逻辑跑通
- M5：完整分析结果可查询
- M6：进入阶段 2 RFC，讨论以 FreshQuant 数据替换 `TradingAgents-CN` 数据层

## 13. 完成说明（Completion Notes）

- **完成日期**：2026-03-07
- **完成结论**：阶段 1 已完成，不再处于 Implementing。
- **验收依据**：
  - `ta_backend` / `ta_frontend` 在 Docker 并行部署下稳定运行，并持续复用 `fq_mongodb` / `fq_redis`。
  - `tradingagents_cn` 中已存在 `analysis_tasks`、`analysis_reports`、`stock_basic_info`、`market_quotes` 等运行数据，说明本地缓存、补数与结果落库链路已闭环。
  - 已使用真实任务 `c4ffec0d-5878-4cdd-8c45-35cdc36db6e0` 完整验收 `002682`：任务状态为 `completed`，结果已返回最终投资建议，`model_info=ChatDeepSeek:deepseek-reasoner`。
