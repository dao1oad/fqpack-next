# 部署影响面

- `freshquant/rear/**` -> 重部署 API Server。
- `freshquant/order_management/**` -> 重部署 API，并重启 `order_management` 宿主机运行面。
- `freshquant/position_management/**` -> 重部署 API，并重启 `position_management` 宿主机运行面。
- `freshquant/tpsl/**` -> 重部署 API，并重启 `tpsl` 宿主机运行面。
- `freshquant/market_data/**` -> 重启 `market_data` 宿主机运行面；需要时重新执行 prewarm。
- `freshquant/strategy/**` 或 `freshquant/signal/**` -> 重启 `guardian` 宿主机运行面。
- `freshquant/data/**` 中影响 Gantt 或 Shouban30 的改动 -> 重部署 API，并在需要时重跑 Dagster 运行面。
- `sunflower/QUANTAXIS/**` -> 重部署 `fq_qawebserver` 及其依赖的宿主机策略运行面。
- `morningglory/fqwebui/**` -> 重新构建并重部署 Web UI。
- `morningglory/fqdagster/**` 或 `morningglory/fqdagsterconfig/**` -> 重启 Dagster webserver 和 daemon。
- `third_party/tradingagents-cn/**` -> 重新构建 `ta_backend` 和 `ta_frontend`。
- `runtime/symphony/**` -> 同步正式 Symphony service，并重启 `fq-symphony-orchestrator`。
- 在决定最终发布批次前，先用 `py -3.12 script/freshquant_deploy_plan.py` 计算正式部署范围。
- 所有宿主机部署面都应通过 `script/fqnext_host_runtime_ctl.ps1` 执行，不要临时用 ad-hoc 进程重启替代。

本文件只作为派生 agent memory 使用；正式运行真值仍来自部署结果与 `docs/current/**`。
