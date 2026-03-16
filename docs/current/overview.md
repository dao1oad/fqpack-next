# 当前总览

## 项目定位

FreshQuant 当前已经完成第一阶段的模块收口，现阶段进入第二阶段：以修复潜在 bug、降低跨模块漂移、稳定部署与排障链路为主。仓库不再保存过程型治理文档，正式文档只描述当前系统事实。

## 当前已落地能力

- HTTP API 已统一挂载 `future / stock / general / gantt / order / position-management / subject-management / runtime / tpsl` 九组蓝图。
- CLI 已收口到 `stock / etf / index / future / xt-* / om-order` 等命令组。
- XTData producer/consumer 已形成实时 tick、1 分钟 bar、结构计算与缓存链路。
- Guardian 已形成事件驱动的策略执行入口，并与订单管理、仓位管理、TPSL 解耦。
- 订单管理、仓位管理、TPSL 已形成三段式交易链路。
- Gantt、Shouban30、KlineSlim、订单管理、仓位管理、标的管理、股票 TPSL 管理、Runtime Observability 等前端页面已落地。
- TradingAgents-CN 已作为并行子系统接入 Docker 并行环境。
- Symphony 正式 orchestrator 已切到 GitHub-first 工作流。

## 目录与职责

- `freshquant/`
  - 后端 API、CLI、数据接入、策略、订单、仓位、TPSL 与运行观测代码。
- `morningglory/fqwebui/`
  - Vue Web UI，包括 Gantt、Shouban30、KlineSlim、订单管理、仓位管理、标的管理、股票 TPSL 管理、Runtime Observability 页面。
- `morningglory/fqdagster/` 与 `morningglory/fqdagsterconfig/`
  - Gantt/Shouban30 读模型的 Dagster 运行面。
- `runtime/symphony/`
  - GitHub-first 正式工作流模板、服务同步脚本、cleanup finalizer。
- `third_party/tradingagents-cn/`
  - TradingAgents-CN 源码与 Docker 构建入口。
- `deployment/examples/`
  - 宿主机环境与 supervisor 模板，不再放在 `docs/` 下。

## 运行拓扑

- Windows 宿主机承担 XTQuant、XTData、Guardian、position worker、TPSL worker 与 Symphony 正式服务。
- Docker 并行环境承担 Mongo、Redis、API Server、TDXHQ、Dagster、Web UI、TradingAgents-CN。
- API Server 提供对外 HTTP 面；Guardian、TPSL、position worker 等后台进程依赖相同的 Mongo/Redis。
- Runtime Observability 以旁路方式记录事件，不参与主交易决策。

## 当前真相源

- 代码真相源：远程 `origin/main`。
- 运行真相源：`fq-symphony-orchestrator` 正式服务与受影响模块的部署结果。
- 文档真相源：`docs/current/**`。
- 任务真相源：Issue-managed 任务使用 GitHub Issue；轻量更新允许直接走 `feature branch -> PR`。
- 对 `Symphony` 接管的任务，GitHub Issue body 即执行合同；direct PR 应在 PR body 写清范围与部署影响。

## 当前维护重点

- 修复 XTData、Guardian、订单管理、仓位门禁与 TPSL 之间的边界 bug。
- 保持 Mongo 主事实、投影集合与前端视图的一致性。
- 把部署矩阵、健康检查与 cleanup 做成闭环，而不是停留在代码合并。
- 让 `docs/current/**` 跟随代码演进，避免再次回到“过程文档多、现状文档少”的状态。
