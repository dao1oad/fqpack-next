# 宿主机运行时切换到 Docker Mongo 设计

## 背景

当前 `broker / xtdata producer / xtdata consumer` 运行在 Windows 宿主机，由 `D:/fqpack/config/supervisord.fqnext.conf` 拉起，并统一读取 `D:/fqpack/config/envs.conf`。
`envs.conf` 仅设置了 `FRESHQUANT_MONGODB__HOST=127.0.0.1`，未设置 `FRESHQUANT_MONGODB__PORT` 与 `FRESHQUANT_REDIS__PORT`，因此这些宿主机进程默认连接宿主机 `127.0.0.1:27017` 与宿主机 Redis `127.0.0.1:6379`。

与此同时，Docker 并行部署的 Mongo 运行在 `fq_mongodb`，宿主机映射端口是 `27027`；Redis 运行在 `fq_redis`，宿主机映射端口是 `6380`。容器内 API 已连接 Docker Mongo/Redis，但宿主机进程仍连接宿主机 Mongo/Redis，导致 `params / xt_positions / xt_trades` 与订单队列分裂。

## 目标

- 让宿主机 `broker / producer / consumer` 统一连接 Docker Mongo `127.0.0.1:27027` 与 Docker Redis `127.0.0.1:6380`
- 初始化 Docker `freshquant` 库，确保存在 `params`、基础索引和基础策略
- 将宿主机 `freshquant.params` 同步到 Docker `freshquant.params`
- 验证三个宿主机进程均已读取 Docker Mongo

## 非目标

- 不迁移宿主机 Mongo 其他业务集合
- 不修改 Docker Compose 拓扑
- 不重构参数读取逻辑

## 方案

### 1. 宿主机运行时配置切换

在 `D:/fqpack/config/envs.conf` 中显式添加：

- `FRESHQUANT_MONGODB__HOST=127.0.0.1`
- `FRESHQUANT_MONGODB__PORT=27027`
- `FRESHQUANT_REDIS__HOST=127.0.0.1`
- `FRESHQUANT_REDIS__PORT=6380`

这样通过 supervisor 启动的三个宿主机进程会统一改连 Docker Mongo/Redis。

### 2. Docker Mongo 初始化

执行 `python -m freshquant.initialize --quiet`，在指向 Docker Mongo 的环境下创建：

- `params / strategies / subscribe_instruments / stock_realtime` 等基础索引
- `notification / monitor / xtquant / guardian` 基础参数骨架
- `Guardian / Manual` 基础策略字典

### 3. 参数同步

从宿主机 Mongo `127.0.0.1:27017/freshquant.params` 读取全部文档，按 `code` upsert 到 Docker Mongo `127.0.0.1:27027/freshquant.params`。
同步以宿主机当前参数为准，覆盖初始化写入的默认值。

### 4. 运行验证

重启：

- `fqnext_xtquant_broker`
- `fqnext_realtime_xtdata_producer`
- `fqnext_realtime_xtdata_consumer`

验证项：

- 进程读取到 `mongodb.host=127.0.0.1, mongodb.port=27027`
- 进程读取到 `redis.host=127.0.0.1, redis.port=6380`
- `findParam("xtquant")` 在 Docker Mongo 可查到值
- broker 手动触发 `sync-positions` 后，Docker Mongo `xt_positions` 有数据
- producer / consumer 读取到 Docker Mongo 的 `params`

## 回滚

- 将 `D:/fqpack/config/envs.conf` 中 `FRESHQUANT_MONGODB__PORT` / `FRESHQUANT_REDIS__PORT` 改回 `27017` / `6379`
- 重启三个宿主机进程
- Docker Mongo 中新增数据保留，不影响宿主机回切
