# 当前总览

## 项目定位

FreshQuant 当前阶段以修复潜在 bug、降低跨模块漂移、稳定部署与排障链路为主。仓库不再保留过程型治理文档，正式文档只描述当前系统事实。

## 当前已落地能力

- HTTP API 已统一挂载 `future / stock / general / gantt / daily-screening / order / position-management / subject-management / runtime / tpsl` 十组蓝图。
- CLI 已收口到 `stock / etf / index / future / xt-* / om-order` 等命令组。
- XTData producer / consumer 已形成实时 tick、1 分钟 bar、结构计算与缓存链路。
- Guardian、订单管理、仓位管理、TPSL 已形成解耦的宿主机交易链。
- FuturesControl、StockControl、StockPools、StockCjsd、Gantt、Shouban30、KlineSlim、订单管理、仓位管理、股票 TPSL 管理、Runtime Observability 等前端页面已落地。
- `morningglory/fqwebui` 主要工作台页面当前统一使用固定 viewport shell；在 `1920x1080 / 100%` 下优先避免浏览器级页面滚动，长列表改为组件内部滚动。
- `KlineSlim` 标的设置面板当前去掉硬编码 `must_pool` 提示；单标的仓位上限只保留当前生效值、市值、买入门禁与设置输入框。
- `OrderManagement` 的多字段筛选框当前默认折叠到“高级筛选”；`PositionManagement` 左栏改为先看规则矩阵，再看压缩后的仓位状态与 inventory。
- `SubjectManagement` 在单标的仓位上限摘要不可用时降级返回 `available=false / error`，不再因为未跟踪 symbol 让整页 `500`；`TPSL` 的 `stock_fills` 方向当前由后端 `direction_label` 和来源字段补齐。
- `Runtime Observability` 的组件侧栏当前保持显式选择 sticky，并对重复的 Event 请求做 query-key 去重，避免点左栏时被自动回退和重复加载拖慢；`1920x1080 / 100%` 下浏览页会把右侧详情下沉为第二行，步骤 ledger 和步骤详情都只在组件内部滚动。
- TradingAgents-CN 已作为并行子系统接入 Docker 并行环境。

## 目录与职责

- `freshquant/`
  - 后端 API、CLI、数据接入、策略、订单、仓位、TPSL 与运行观测代码。
- `morningglory/fqwebui/`
  - Vue Web UI，包括 FuturesControl、StockControl、StockPools、StockCjsd、Gantt、Shouban30、每日选股、KlineSlim、订单管理、仓位管理、标的管理、股票 TPSL 管理、Runtime Observability 页面。
- `morningglory/fqdagster/` 与 `morningglory/fqdagsterconfig/`
  - Gantt/Shouban30 读模型的 Dagster 运行面。
- `runtime/memory/`
  - 冷/热记忆刷新、context pack 编译与自由会话 bootstrap。
- `third_party/tradingagents-cn/`
  - TradingAgents-CN 源码与 Docker 构建入口。
- `deployment/examples/`
  - 宿主机环境与 supervisor 模板。

## 运行拓扑

- Windows 宿主机承担 XTQuant、XTData、Guardian、position worker、TPSL worker 与其他需要 Windows 资源的 Python 进程。
- Docker 并行环境承担 Mongo、Redis、API Server、TDXHQ、Dagster、Web UI、TradingAgents-CN。
- API Server 提供对外 HTTP 面；Guardian、TPSL、XT account sync worker 等后台进程依赖相同的 Mongo/Redis。
- Runtime Observability 以旁路方式记录事件，不参与主交易决策。

## 当前真相源

- 代码真相源：远程 `origin/main`。
- 运行真相源：最新远程 `origin/main` 的正式 deploy 结果。
- 文档真相源：`docs/current/**`。
- 任务真相源：高影响变更优先使用 GitHub Issue；轻量更新允许直接走 `feature branch -> PR`。
- 本地会话完成后先合并到远程 `main`，再从最新远程 `main` 发起正式 deploy。

## 当前维护重点

- 修复 XTData、Guardian、订单管理、仓位门禁与 TPSL 之间的边界 bug。
- 保持 Mongo 主事实、投影集合与前端视图的一致性。
- 把部署矩阵、健康检查与 cleanup 做成闭环，而不是停留在代码合并。
- 让 `docs/current/**` 跟随代码演进。
