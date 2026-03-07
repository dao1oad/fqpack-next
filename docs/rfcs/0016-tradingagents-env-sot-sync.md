# RFC 0016: TradingAgents-CN 根 `.env` 单一真相源配置同步

- **状态**：Done
- **负责人**：Codex
- **评审人**：用户已确认
- **创建日期**：2026-03-07
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

`D:\fqpack\freshquant-2026.2.23\third_party\tradingagents-cn` 当前对 DeepSeek 和 Tushare 的配置存在多处来源并行：

- Docker Compose 为 `ta_backend` 注入仓库根 [`D:\fqpack\freshquant-2026.2.23\.env`](D:/fqpack/freshquant-2026.2.23/.env)
- 镜像构建时又把 [`D:\fqpack\freshquant-2026.2.23\third_party\tradingagents-cn\.env.docker`](D:/fqpack/freshquant-2026.2.23/third_party/tradingagents-cn/.env.docker) 复制进容器
- MongoDB 中还保存 `llm_providers` 和 `system_configs` 的厂家级、模型级、数据源级配置
- 运行期 `bridge_config_to_env()`、`TradingAgentsGraph`、`TushareProvider`、`DataSourceManager` 对这些来源的优先级并不一致

实际排查结果表明：

- 仓库根 `.env` 当前并未配置 `DEEPSEEK_API_KEY` / `TUSHARE_TOKEN`
- [`D:\fqpack\freshquant-2026.2.23\third_party\tradingagents-cn\.env`](D:/fqpack/freshquant-2026.2.23/third_party/tradingagents-cn/.env) 中存在有效 DeepSeek/Tushare 配置
- 当前激活 `system_configs` 中 DeepSeek 模型级配置和 Tushare 数据源级配置仍是旧占位值
- 运行中的 `ta_backend` 容器内 `DEEPSEEK_API_KEY` / `TUSHARE_TOKEN` 为空

这导致“宿主配置、容器环境、数据库镜像、任务执行”四条链路无法收敛，最近任务失败就属于该问题的直接表现。

## 2. 目标（Goals）

- 将仓库根 [`D:\fqpack\freshquant-2026.2.23\.env`](D:/fqpack/freshquant-2026.2.23/.env) 明确为 DeepSeek/Tushare 的唯一真相源（source of truth）。
- `ta_backend` 启动时自动把根 `.env` 中的 DeepSeek/Tushare 配置同步到：
  - `llm_providers` 厂家级配置
  - `system_configs.llm_configs` 模型级配置
  - `system_configs.data_source_configs` 数据源级配置
- 统一运行期优先级为 `.env > 数据库 > fallback`，禁止数据库旧值在启动后反向覆盖 `.env`。
- 保证任务中心 DeepSeek 初始化链路、Tushare 最小连接链路和配置展示链路使用同一套值。

## 3. 非目标（Non-Goals）

- 本 RFC 不统一其他 LLM 厂家或其他数据源的配置来源。
- 本 RFC 不重构 TradingAgents-CN 的整个配置系统，也不移除现有 Mongo 配置集合。
- 本 RFC 不新增对外公开 API，不改动前端配置页交互。
- 本 RFC 不处理宿主机其他服务（如 FreshQuant 主服务）对 `envs.conf` 的配置来源。

## 4. 范围（Scope）

**In Scope**

- 为 `ta_backend` 增加启动期 `.env -> Mongo` 同步逻辑。
- 将 DeepSeek 厂家级配置写入 `llm_providers.deepseek`。
- 将 `deepseek-chat` / `deepseek-reasoner` 模型级配置写入激活的 `system_configs.llm_configs`。
- 将 Tushare Token 写入激活的 `system_configs.data_source_configs`。
- 统一 `config_bridge`、`TushareProvider`、`DataSourceManager` 的 DeepSeek/Tushare 读取优先级。
- 移除容器运行期对 `.env.docker` 默认占位文件的依赖。
- 将当前有效的 `third_party/tradingagents-cn/.env` 中 DeepSeek/Tushare 配置提升到仓库根 `.env`。

**Out of Scope**

- 通过 Web 后台动态修改 DeepSeek/Tushare 后仍保持重启后生效。
- 对 `llm_providers` / `system_configs` 的 schema 做破坏性调整。
- 引入新的配置存储服务或 Secret Manager。

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- 仓库根 `.env` 保存 DeepSeek/Tushare 的最终配置值。
- `ta_backend` 启动时在 DB 已连接后完成配置写库。
- 运行期桥接与消费链优先使用环境变量。
- DB 中保留与 `.env` 一致的镜像值，供配置页展示、任务链读取和调试排障使用。

**不负责（Must Not）**

- 不保证手工改 DB 后无需重启容器即可长期生效。
- 不把 `third_party/tradingagents-cn/.env` 或 `config/envs.conf` 继续作为 `ta_backend` 的真相源。

**依赖（Depends On）**

- `docker/compose.parallel.yaml`
- `ta_backend` 启动生命周期
- MongoDB `tradingagents_cn`
- 已存在的 `ConfigService`、`config_bridge`、`TushareProvider`

**禁止依赖（Must Not Depend On）**

- 不能依赖 `.env.docker` 里的默认占位值驱动生产运行
- 不能依赖用户手工先点配置页写库再让服务可用

## 6. 对外接口（Public API）

本 RFC 不新增对外 HTTP API。

运行时行为调整如下：

- `ta_backend` 启动时新增一次内部“环境配置落库同步”。
- `reload_config` 继续只做配置桥接，不新增外部请求参数。
- `TradingAgentsGraph` 与 Tushare 数据链读到的 DeepSeek/Tushare 配置将与仓库根 `.env` 一致。

错误语义：

- 若根 `.env` 缺失 `DEEPSEEK_API_KEY`，DeepSeek 模型初始化仍按现有逻辑失败，但错误会是真实缺失，而不是数据库占位值误用。
- 若根 `.env` 缺失 `TUSHARE_TOKEN`，Tushare 链路按现有逻辑降级或报错，不再被旧数据库值误导。

## 7. 数据与配置（Data / Config）

唯一真相源：

- [`D:\fqpack\freshquant-2026.2.23\.env`](D:/fqpack/freshquant-2026.2.23/.env)
  - `DEEPSEEK_API_KEY`
  - `DEEPSEEK_BASE_URL`
  - `TUSHARE_TOKEN`

数据库镜像：

- `tradingagents_cn.llm_providers`
  - `name=deepseek`
  - `api_key`
  - `default_base_url`
- `tradingagents_cn.system_configs`
  - `llm_configs[]` 中 `provider=deepseek`
  - `data_source_configs[]` 中 `type=tushare`

运行期环境：

- `os.environ["DEEPSEEK_API_KEY"]`
- `os.environ["DEEPSEEK_BASE_URL"]`
- `os.environ["TUSHARE_TOKEN"]`

## 8. 破坏性变更（Breaking Changes）

- `ta_backend` 的 DeepSeek/Tushare 配置来源将从“多源并行”收敛为“仓库根 `.env` 单一真相源”。
- 用户通过 Web 后台或直接改 Mongo 修改 DeepSeek/Tushare 密钥后，这些改动在容器重启后不会保留；重启时会被根 `.env` 覆盖回去。
- `.env.docker` 不再作为运行期默认密钥来源。

影响面：

- `ta_backend` 启动逻辑
- TradingAgents 配置页展示与调试体验
- DeepSeek 任务执行链
- Tushare 数据同步与调用链

迁移步骤：

1. 将当前有效的 DeepSeek/Tushare 配置写入仓库根 `.env`
2. 重建并重启 `ta_backend`
3. 验证容器环境变量、Mongo 镜像配置和运行链一致

回滚方案：

- 回退启动同步逻辑、`config_bridge`/Tushare 读取优先级和 Dockerfile 改动
- 恢复 `.env.docker` 运行期注入
- 允许 DB 再次作为 DeepSeek/Tushare 的长期主来源

## 9. 迁移映射（From `D:\fqpack\freshquant`）

本 RFC 不从旧仓库迁移业务模块，属于目标仓库内 `TradingAgents-CN` 集成配置治理。

- 目标能力：`TradingAgents-CN` 配置收敛
- 归属位置：
  - `third_party/tradingagents-cn/app/*`
  - `third_party/tradingagents-cn/tradingagents/*`
  - `docker/compose.parallel.yaml`
  - 根 `.env`

## 10. 测试与验收（Acceptance Criteria）

- [x] 仓库根 `.env` 包含有效 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`TUSHARE_TOKEN`
- [x] `ta_backend` 重建后容器内 `printenv DEEPSEEK_API_KEY` / `printenv TUSHARE_TOKEN` 非空
- [x] `llm_providers.deepseek` 中 `api_key/default_base_url` 与根 `.env` 一致
- [x] 激活 `system_configs.llm_configs` 中的 DeepSeek 模型项与根 `.env` 一致
- [x] 激活 `system_configs.data_source_configs` 中的 Tushare 配置与根 `.env` 一致
- [x] 任务中心失败点 `engine_initialization` 的 DeepSeek 初始化链路通过
- [x] Tushare 最小连接测试通过
- [x] 新增回归测试覆盖 `.env -> DB` 同步和 `TUSHARE_TOKEN` 优先级

## 11. 风险与回滚（Risks / Rollback）

- 风险点：根 `.env` 缺失或写错会在重启时把错误值同步到数据库。
- 风险点：配置页仍允许用户编辑 DB，可能造成“运行前后不一致”的短时观感。
- 缓解：
  - 启动同步前校验 API Key/Token 有效性
  - 只同步 DeepSeek/Tushare，避免扩大影响面
  - 保留 DB 镜像配置，便于排障
- 回滚：见第 8 节

## 12. 里程碑与拆分（Milestones）

- M1：RFC 与设计确认
- M2：根 `.env`、Dockerfile、启动同步逻辑落地
- M3：DeepSeek/Tushare 回归测试通过
- M4：Docker 重建并验证 Mongo/任务/Tushare 全链路可用
