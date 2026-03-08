# RFC 0010: 宿主机 XT/XTData 运行时对齐 Docker Mongo

- **状态**：Done
- **负责人**：Codex
- **评审人**：TBD
- **创建日期**：2026-03-07
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题

当前仓库支持 Docker 并行部署，MongoDB 在宿主机暴露端口为 `27027`。
但 MiniQMT / XTData 相关的 `broker`、`xtdata producer`、`xtdata consumer` 仍运行在 Windows 宿主机，且默认会读取 `freshquant.yaml` 中的 `mongodb.port=27017`。

这会带来两个问题：

- Docker 容器内 API 读写的是 `fq_mongodb`，而宿主机实盘链路读写的是宿主机 `mongod`，`params / xt_positions / xt_trades` 分裂为两份。
- 当 `xtquant.account_type=CREDIT` 时，broker 若只按默认 `STOCK` 构造 `StockAccount`，会导致信用账户持仓查询返回空结果。

## 2. 目标

- 在 Docker 并行部署模式下，明确宿主机 `broker / producer / consumer` 应统一连接 Docker Mongo `127.0.0.1:27027`。
- 明确 Docker `freshquant` 库需要先运行 `python -m freshquant.initialize --quiet` 建立基础索引与 `params` 骨架。
- 保留 MiniQMT/XTData 运行在 Windows 宿主机的约束，不尝试将 `broker` 移入 Linux 容器。
- 修复 broker 对 `xtquant.account_type` 的忽略问题。

## 3. 非目标

- 不迁移宿主机 Mongo 其他业务集合到 Docker Mongo。
- 不把 MiniQMT/XTData 二进制依赖移入 Docker。
- 不重构 dynaconf 与 Mongo `params` 的配置分层。

## 4. 范围

**In Scope**

- `broker` 连接 MiniQMT 时按 `xtquant.account_type` 构造账户对象。
- 文档明确宿主机 `envs.conf` 需要显式设置 `FRESHQUANT_MONGODB__HOST=127.0.0.1`、`FRESHQUANT_MONGODB__PORT=27027`。
- 提供宿主机 supervisor / env 样板文件，说明 `broker / xtdata producer / xtdata consumer` 的可运行配置。
- 记录初始化 Docker `freshquant` 库与同步 `freshquant.params` 的操作步骤。

**Out of Scope**

- 自动化迁移宿主机旧库中的 `xt_positions / xt_trades / xt_orders` 历史数据。
- 自动化关闭宿主机 `mongod`。

## 5. 模块边界

**负责**

- `morningglory/fqxtrade/fqxtrade/xtquant/`：MiniQMT broker 连接参数与账户类型修复。
- `docs/agent/*`、`docs/实盘对接说明.md`：部署文档与运维步骤。
- `docs/配置文件模板/*`：宿主机 env/supervisor 样板文件。

**不负责**

- Docker Compose 中新增 `xtquant broker` 容器。
- 容器内直接访问 Windows MiniQMT。

## 6. 依赖与集成点

- Windows 宿主机上的 MiniQMT / XTData。
- Docker 并行部署的 `fq_mongodb`（宿主机 `27027`）。
- Docker 并行部署的 `fq_redis`（宿主机 `127.0.0.1:6380`，容器内 `6379`）。
- Mongo `params` 初始化入口：`python -m freshquant.initialize --quiet`。

## 7. Public API

无新增 HTTP/CLI 接口。

对部署侧的约束如下：

- 宿主机 `broker / xtdata producer / xtdata consumer` 必须在环境中显式设置：
  - `FRESHQUANT_MONGODB__HOST=127.0.0.1`
  - `FRESHQUANT_MONGODB__PORT=27027`
  - `FRESHQUANT_REDIS__HOST=127.0.0.1`
  - `FRESHQUANT_REDIS__PORT=6380`
- `xtquant.account_type` 若配置为 `CREDIT`，broker 会按信用账户类型连接。

## 8. 数据与配置

- Docker 并行模式下，`freshquant.params`、`xt_positions`、`xt_trades` 的运行时事实源应为 Docker Mongo `freshquant` 库。
- `python -m freshquant.initialize --quiet` 用于为 Docker `freshquant` 库建立基础索引、`params` 骨架与基础策略。
- 若宿主机已有有效 `freshquant.params`，应按 `code` 同步到 Docker `freshquant.params`。

## 9. 破坏性变更

这是部署语义变更：

- Docker 并行模式下，宿主机实盘链路不再默认使用宿主机 Mongo `27017` 作为运行时事实源，而是切到 Docker Mongo `27027`。

影响面：

- `broker`
- `freshquant.market_data.xtdata.market_producer`
- `freshquant.market_data.xtdata.strategy_consumer`
- 所有依赖 Mongo `params / xt_positions / xt_trades` 排障的运维脚本

迁移步骤：

1. 备份宿主机 `freshquant.params`
2. 在 Docker Mongo 上执行 `python -m freshquant.initialize --quiet`
3. 将宿主机 `freshquant.params` 同步到 Docker `freshquant.params`
4. 更新宿主机 `envs.conf` 的 Mongo 端口为 `27027`
5. 重启 `broker / producer / consumer`

回滚：

1. 将宿主机 `envs.conf` 的 Mongo 端口改回 `27017`
2. 重启宿主机进程
3. Docker Mongo 中的数据保留，不影响回切

## 10. 测试与验收

- [x] `broker` 在 `xtquant.account_type=CREDIT` 时能正确构造 `StockAccount(account, "CREDIT")`
- [x] Docker Mongo `freshquant.params` 初始化成功
- [x] 宿主机 `freshquant.params` 可同步到 Docker `freshquant.params`
- [x] 宿主机 `broker / producer / consumer` 可在同一 supervisor 下重新拉起
- [x] 手动触发 `sync-positions` 后，Docker Mongo `freshquant.xt_positions` 出现持仓数据

## 11. 迁移映射

- 宿主机 supervisor 运行方式：`D:\fqpack\config\supervisord.fqnext.conf`
- 宿主机环境文件：`D:\fqpack\config\envs.conf`
- 本仓库文档与模板：
  - `docs/agent/Docker并行部署指南.md`
  - `docs/agent/配置管理指南.md`
  - `docs/实盘对接说明.md`
  - `docs/配置文件模板/envs.fqnext.example`
  - `docs/配置文件模板/supervisord.fqnext.example.conf`
