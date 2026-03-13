# 当前配置

## 配置真相源

FreshQuant 当前使用 Dynaconf。主入口在 `freshquant/config.py`，会按以下顺序搜索配置文件：

- `freshquant/` 包目录下的 `freshquant.yaml|yml|json`
- 可执行目录同名文件
- `~/.freshquant/freshquant.yaml|yml|json`
- 当前工作目录同名文件

同时支持 `freshquant_*.yaml|yml|json` 形式的 include 文件。环境变量前缀是 `FRESHQUANT_`。

## 当前优先级

1. 进程启动时显式传入的环境变量。
2. `.env` 或宿主机环境变量。
3. Dynaconf 读取到的 `freshquant.yaml` / `freshquant_*.yaml`。
4. 代码内默认值。

判断配置问题时，优先确认环境变量是否覆盖了文件配置。

## 关键配置项

### 基础设施

- `mongodb.host`
- `mongodb.port`
- `mongodb.db`
- `mongodb.gantt_db`
- `redis.host`
- `redis.port`
- `redis.db`

当前仓库默认文件 `freshquant/freshquant.yaml` 中：

- Mongo 默认 `127.0.0.1:27027`
- 主库默认 `freshquant`
- Gantt 库默认 `freshquant_gantt`
- Redis 默认 `127.0.0.1:6379 db=1`

Docker 并行模式通过 `deployment/examples/envs.fqnext.example` 把端口改到：

- Mongo `27027`
- Redis `6380`
- TDXHQ `15001`

vendored `QUANTAXIS` 当前 Mongo 解析规则：

- 显式 `MONGOURI` 或 `FRESHQUANT_MONGODB__URI` 优先。
- 其次读取 `FRESHQUANT_MONGODB__HOST/PORT`。
- 如果只拿到旧的本地 `localhost/127.0.0.1:27017` 默认值，会自动收口到宿主机 `27027`。
- 非本地目标例如 `fq_mongodb:27017` 保持不变，用于 Docker 容器内部链路。

### 订单与仓位

- `order_management.mongo_database`
- `order_management.projection_database`
- `position_management.thresholds.allow_open_min_bail`
- `position_management.thresholds.holding_only_min_bail`

订单管理默认单独使用 `freshquant_order_management`，投影仍写回 `freshquant`。
仓位管理默认单独使用 `freshquant_position_management`。
当前仓位管理页面只允许编辑 `pm_configs.thresholds` 下的两个保证金阈值。
阈值保存后不会直接改写现有 `pm_current_state`；它会在下一次 `PositionSnapshotService.refresh_once()` 刷新时进入状态判定链。
仓位管理阈值接口只接受有限数值；`nan`、`inf`、`-inf` 会被拒绝。若历史 `pm_configs.thresholds` 中存在非有限值，Dashboard 读取时会回退到默认阈值。

以下仍是代码默认语义，只读展示，不写入持久化配置：

- `state_stale_after_seconds`
- `default_state`

以下属于系统级 XT 连接参数，继续以系统设置为真值：

- `xtquant.path`
- `xtquant.account`
- `xtquant.account_type`

### XTData / 监控

- `monitor.xtdata.mode`
- `monitor.xtdata.max_symbols`
- `monitor.xtdata.queue_backlog_threshold`
- `XTQUANT_PORT` 环境变量

常见模式：

- `guardian_1m`
  - Guardian 事件驱动模式需要该值。
- `clx_15_30`
  - 更偏向结构/选股链路。

### 运行观测

- `FQ_RUNTIME_LOG_DIR`
  - 覆盖默认 `logs/runtime`

### Symphony

- `GITHUB_TOKEN`
- `GH_TOKEN`
- `FRESHQUANT_GITHUB_REPO`
- `FRESHQUANT_OPENAI_SYMPHONY_ROOT`

这些变量属于宿主机正式服务配置，不在仓库内保存 secret。

## 仓库文本换行

- `.gitattributes` 是仓库文本文件换行的真值来源。
- 仓库根目录的 `.gitattributes` / `.gitignore` / `.editorconfig` / `.dockerignore` 使用 `LF`。
- 源码、文档、YAML、PowerShell、Shell 与 Dockerfile 等正式文本文件默认使用 `LF`。
- Windows 启动脚本 `*.bat` / `*.cmd` 使用 `CRLF`。
- `pre-commit` 与 CI 会运行 `mixed-line-ending` 检查，阻止 mixed line endings 进入仓库。

## 当前宿主机模板

- `deployment/examples/envs.fqnext.example`
  - Docker 并行模式下 broker / xtdata / worker 连接 Docker Mongo/Redis 的标准模板。
- `deployment/examples/freshquant.yaml`
  - 宿主机配置样例。
- `deployment/examples/supervisord.fqnext.example.conf`
  - 宿主机进程编排样例。

## 配置变更约束

- 改配置值：属于普通改动，但应同步文档。
- 改配置语义：属于高风险改动，必须先过 `Design Review`。
- 运行面排障时，不要只看 `freshquant.yaml`；必须同时检查进程环境变量和 Docker `env_file`。
