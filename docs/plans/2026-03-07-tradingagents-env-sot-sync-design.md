# TradingAgents-CN 根 .env 单一真相源配置同步设计

## 背景

`ta_backend` 当前同时从根 `.env`、镜像内 `.env.docker`、Mongo `llm_providers`、Mongo `system_configs` 四处读取 DeepSeek/Tushare 配置。
这些链路在以下位置优先级不一致：

- [`app/core/config_bridge.py`](D:/fqpack/freshquant-2026.2.23/third_party/tradingagents-cn/app/core/config_bridge.py)
- [`tradingagents/dataflows/providers/china/tushare.py`](D:/fqpack/freshquant-2026.2.23/third_party/tradingagents-cn/tradingagents/dataflows/providers/china/tushare.py)
- [`tradingagents/dataflows/data_source_manager.py`](D:/fqpack/freshquant-2026.2.23/third_party/tradingagents-cn/tradingagents/dataflows/data_source_manager.py)
- [`app/services/simple_analysis_service.py`](D:/fqpack/freshquant-2026.2.23/third_party/tradingagents-cn/app/services/simple_analysis_service.py)
- [`tradingagents/graph/trading_graph.py`](D:/fqpack/freshquant-2026.2.23/third_party/tradingagents-cn/tradingagents/graph/trading_graph.py)

结果是：

- 容器环境变量可能为空
- DB 中厂家级、模型级、数据源级值不一致
- 运行链可能吃到占位值或旧值

## 目标设计

### 1. 单一真相源

唯一真相源固定为仓库根 [`D:\fqpack\freshquant-2026.2.23\.env`](D:/fqpack/freshquant-2026.2.23/.env)：

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `TUSHARE_TOKEN`

其他位置都只允许做镜像或 fallback，不再承担真相源职责。

### 2. 启动期同步

在 [`app/main.py`](D:/fqpack/freshquant-2026.2.23/third_party/tradingagents-cn/app/main.py) 的 `lifespan` 中新增一步：

1. `await init_db()`
2. `await sync_env_runtime_config_to_db()`
3. `bridge_config_to_env()`

也就是说，先把根 `.env` 同步进 Mongo，再把最终值桥接进运行时环境。

### 3. Mongo 镜像策略

新增内部同步服务，负责：

- upsert `llm_providers.deepseek`
  - `api_key`
  - `default_base_url`
  - `is_active=True`
- 修正激活 `system_configs.llm_configs`
  - 更新现有 `provider=deepseek` 项
  - 若不存在，则补齐 `deepseek-chat` / `deepseek-reasoner`
  - 同步 `api_key`、`api_base`、`enabled`
  - 同步 `default_llm=deepseek-chat`
  - 同步 `system_settings.quick_analysis_model=deepseek-chat`
  - 同步 `system_settings.deep_analysis_model=deepseek-reasoner`
  - 同步 `system_settings.default_model=deepseek-chat`
- 修正激活 `system_configs.data_source_configs`
  - 更新或补齐 `type=tushare`
  - 同步 `api_key`、`endpoint`、`enabled`
  - 同步 `default_data_source=Tushare`

这样 DB 就是根 `.env` 的持久化镜像，而不是并列主来源。

### 4. 运行期优先级

统一规则为：

- `.env > 数据库 > fallback`

具体体现在：

- `config_bridge` 不再允许 Tushare 的 `DB > .env`
- `TushareProvider` 先读环境变量，再用 DB 降级
- `DataSourceManager` 判断 Tushare 可用时先看环境变量，再看 DB
- DeepSeek 任务链继续沿用已修复的“无效配置值不覆盖环境变量”语义

### 5. Docker 收口

Docker 配置同步调整为：

- [`docker/compose.parallel.yaml`](D:/fqpack/freshquant-2026.2.23/docker/compose.parallel.yaml) 保持 `env_file: ../.env`
- [`Dockerfile.backend`](D:/fqpack/freshquant-2026.2.23/third_party/tradingagents-cn/Dockerfile.backend) 删除 `COPY .env.docker ./.env`

这样容器运行期不会再被 `.env.docker` 中的占位值干扰。

## 数据流

### 启动时

1. Compose 把根 `.env` 注入 `ta_backend`
2. `lifespan` 建立 Mongo 连接
3. 启动同步服务读取 `os.environ`
4. 同步服务修正 `llm_providers` 和激活 `system_configs`
5. `bridge_config_to_env()` 把 DB 非密钥运行配置写回环境变量，同时保留 DeepSeek/Tushare 的 `.env` 优先级
6. 任务链、TushareProvider、DataSourceManager 使用统一结果

### 运行中

- DB 可用于配置展示、调试、查询
- 若用户手工改 DB，运行中部分链路可能短时看到新值
- 但重启后会重新收敛到根 `.env`

## 影响与风险

- 这是明确的行为变更：DeepSeek/Tushare 不再允许 Mongo 作为长期主来源。
- 可能影响依赖 Web 后台直接改密钥且不重启容器的用法。
- 风险通过“仅同步 DeepSeek/Tushare + 启动前有效性校验 + 回归测试”控制。

## 验证方案

### 自动化

- 新增单元测试覆盖：
  - 启动同步会把根 `.env` 值写入 `llm_providers` / `system_configs`
  - `config_bridge` 对 `TUSHARE_TOKEN` 改成 `.env > DB`
  - `TushareProvider` 改成 `.env > DB`

### 手工验证

- 检查根 `.env` 中三项变量存在
- 重建 `ta_backend`
- 检查容器环境变量
- 检查 Mongo 中 DeepSeek/Tushare 镜像值
- 检查最近任务初始化
- 检查 Tushare 最小连接
