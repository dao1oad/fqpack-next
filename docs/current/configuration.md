# 当前配置

## 正式真值

新系统正式配置只保留两处真值：

1. `freshquant_bootstrap.yaml`
2. Mongo `params / strategies / pm_configs / instrument_strategy`

对应代码入口：

- `freshquant/bootstrap_config.py`
- `freshquant/system_settings.py`
- `freshquant/runtime_constants.py`

旧 `freshquant/config.py`、旧 `queryParam(...)`、旧 `/api/get_settings` `/api/update_settings` 不再属于新系统正式配置入口。

## Bootstrap 文件

正式文件名：`freshquant_bootstrap.yaml`

建议位置：

- 样例：`deployment/examples/freshquant_bootstrap.yaml`
- 宿主机正式文件：`D:/fqpack/config/freshquant_bootstrap.yaml`

搜索顺序：

1. `FRESHQUANT_BOOTSTRAP_FILE`
2. `freshquant/` 包目录下的 `freshquant_bootstrap.yaml|yml|json`
3. 可执行目录同名文件
4. `~/.freshquant/freshquant_bootstrap.yaml|yml|json`
5. `D:/fqpack/config/freshquant_bootstrap.yaml|yml|json`
6. 当前工作目录同名文件

环境变量前缀仍是 `FRESHQUANT_`，但在新系统里只用于覆盖 bootstrap 配置，不再作为业务设置真值。

当前 vendored `fqxtrade` 的 broker / puppet / Mongo / Redis / Redis 锁相关连接也跟随 `freshquant_bootstrap.yaml` 的基础设施配置，不再单独依赖旧 `freshquant.yaml`。

当前正式运行面默认无代理：

- 宿主机 supervisor `envs.conf` 会显式清空 `ALL_PROXY`、`HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY` 及其小写变量
- `freshquant` / vendored `fqxtrade` / `TradingAgents-CN` 后端进程启动时会再次清理这些代理环境变量
- `deployment/examples/envs.fqnext.example` 与 `third_party/tradingagents-cn/.env.example` 不再保留任何 `*_PROXY` / `*_proxy` 示例键，避免把运行环境误配成代理环境
- 旧 `freshquant.yaml` 的 `proxy` 段与旧 `freshquant.config.Config.PROXIES` 不再保留，也不再属于任何正式真值

内存层运行真值仍要求保留：

- `FQ_MEMORY_CONTEXT_PATH`
- `FQ_MEMORY_CONTEXT_ROLE`

它们和 `freshquant_bootstrap.yaml` 一起决定当前进程加载哪个 context pack，不属于 Mongo 业务设置。

## 配置优先级

### 启动配置

1. 显式环境变量
2. `freshquant_bootstrap.yaml`
3. 代码默认值

### 运行参数

1. Mongo `params / strategies / pm_configs / instrument_strategy`
2. 代码默认值

排障时先判断问题属于“启动配置”还是“运行参数”，再去对应真值源排查。

## Mongo 系统设置（params）

除基础设施配置外，当前系统仍通过 `freshquant.params` 保存一部分运行时业务参数。

当前正式使用的 `code` 只有：

- `notification`
- `monitor`
- `xtquant`
- `guardian`

这些参数的字段含义、可选值和缺省行为，统一见：

- [系统设置参数（params）](./reference/system-settings-params.md)

## Bootstrap 配置项

### 基础设施

- `mongodb.host`
- `mongodb.port`
- `mongodb.db`
- `mongodb.gantt_db`
- `redis.host`
- `redis.port`
- `redis.db`
- `redis.password`
- `memory.mongodb.host`
- `memory.mongodb.port`
- `memory.mongodb.db`
- `memory.cold_root`
- `memory.artifact_root`

默认值：

- Mongo `127.0.0.1:27027`
- 主库 `freshquant`
- Gantt 库 `freshquant_gantt`
- Redis `127.0.0.1:6379 db=1`
- Memory 热库 `fq_memory`
- 冷目录 `.codex/memory`
- Artifact 根目录 `D:/fqpack/runtime/artifacts/memory`

### 订单与仓位数据库

- `order_management.mongo_database`
- `order_management.projection_database`
- `position_management.mongo_database`

默认值：

- `freshquant_order_management`
- `freshquant`
- `freshquant_position_management`

### TDX / API / XTData / Runtime

- `tdx.home`
- `tdx.hq.endpoint`
- `api.base_url`
- `xtdata.port`
- `runtime.log_dir`

当前口径：

- `freshquant.shouban30_pool_service` 写 `.blk` 时先读 `bootstrap_config.tdx.home`，未配置时回退 `TDX_HOME`
- `FQ_RUNTIME_LOG_DIR` 可以覆盖 `runtime.log_dir`
- `XTQUANT_PORT` 可以覆盖 `xtdata.port`

## Mongo 系统设置

### `params`

- `notification.webhook.dingtalk.private`
- `notification.webhook.dingtalk.public`
- `monitor.xtdata.mode`
- `monitor.xtdata.max_symbols`
- `monitor.xtdata.queue_backlog_threshold`
- `monitor.xtdata.prewarm.max_bars`
- `xtquant.path`
- `xtquant.account`
- `xtquant.account_type`
- `xtquant.broker_submit_mode`
- `guardian.stock.lot_amount`
- `guardian.stock.threshold.*`
- `guardian.stock.grid_interval.*`

### `strategies`

- `Guardian`
- `Manual`

### `pm_configs`

- `thresholds.allow_open_min_bail`
- `thresholds.holding_only_min_bail`

当前仓位管理页面只允许编辑 `pm_configs.thresholds` 下这两个阈值。

### `instrument_strategy`

用于单标的覆盖配置，当前只做：

- `instrument_code`
- `instrument_type`
- `strategy_name`
- `lot_amount`
- 可选阈值/网格覆盖

初始化程序只补缺失记录，不覆盖已有单标的配置。

## 前端设置页

新系统正式设置页：

- 路由：`/system-settings`
- API：
  - `GET /api/system-config/dashboard`
  - `POST /api/system-config/bootstrap`
  - `POST /api/system-config/settings`

页面当前使用固定视口三列工作台：

- 左列展示基础设施 / 存储类设置
- 中列展示运行接入 / 系统链路设置
- 右列展示交易控制 / 策略字典
- Bootstrap 与 Mongo 两类正式设置项都直接以内嵌 dense ledger 行展示，不再使用卡片式编辑区
- 所有正式设置项都会出现在主视图中；`guardian.stock.threshold.*` 与 `guardian.stock.grid_interval.*` 不再因 mode 切换而隐藏，只对未生效行做弱化
- 页面内使用列内局部滚动，不再依赖浏览器页面滚动
- 页面顶部保留 `刷新 / 保存启动配置 / 保存系统设置` 三个主操作，并分别统计 Bootstrap 与 Mongo 的未保存项

`guardian.stock.threshold.*` 与 `guardian.stock.grid_interval.*` 保留。
旧 SMTP / 邮件收件人配置不再进入新系统正式设置面。

## 初始化入口

宿主机正式入口：

- `D:/fqpack/initialize.bat`

Python 入口：

```powershell
python -m freshquant.initialize
```

当前初始化程序默认执行：

1. 交互式覆盖 `freshquant_bootstrap.yaml`
2. 交互式覆盖 Mongo 系统设置
3. 自动做运行态 bootstrap
   - 先按当前 `xtquant` 配置尝试建立一次 XT 交易连接
   - XT 资产/持仓/委托/成交同步
   - `om_credit_subjects` 同步
   - 为当前监控标的补缺失 `instrument_strategy`

## Docker / 宿主机并行口径

Docker 并行模式通过 `deployment/examples/envs.fqnext.example` 把关键端口收口到：

- Mongo `27027`
- Redis `6380`
- API `15000`
- TDXHQ `15001`

vendored `QUANTAXIS` 当前 Mongo 解析规则：

- 显式 `MONGOURI` 或 `FRESHQUANT_MONGODB__URI` 优先
- 其次读取 `FRESHQUANT_MONGODB__HOST/PORT`
- 如果只拿到旧的本地 `localhost/127.0.0.1:27017` 默认值，会自动收口到宿主机 `27027`
- 非本地目标例如 `fq_mongodb:27017` 保持不变，用于 Docker 容器内部链路

若本地要复现同一模式，优先保证 `PYTHONPATH` 指向仓库源码、`morningglory/fqxtrade` 与 `sunflower/QUANTAXIS`。

## 当前宿主机模板

- `deployment/examples/envs.fqnext.example`
- `deployment/examples/freshquant_bootstrap.yaml`
- `deployment/examples/supervisord.fqnext.example.conf`

正式宿主机入口当前收敛为：

- service：`fqnext-supervisord`
- 配置：`D:/fqpack/config/supervisord.fqnext.conf`
- RPC：`http://127.0.0.1:10011/RPC2`
- 初始化入口：`D:/fqpack/initialize.bat`
- 管理员桥接任务：`fqnext-supervisord-restart`
- 兼容人工启动器：`D:/fqpack/supervisord/frequant-next.bat`

## 配置变更约束

- 改配置值：属于普通改动，但应同步文档
- 改配置语义：属于高影响改动，Issue 中必须先写清新语义、验收标准与部署影响，再进入 `In Progress`
- 运行面排障时，不要只看 bootstrap 文件；必须同时检查环境变量和 Mongo 系统设置
