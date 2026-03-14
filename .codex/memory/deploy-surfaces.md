# Deploy Surfaces

- `freshquant/rear/**` -> redeploy API Server.
- `freshquant/order_management/**` -> redeploy API and restart the `order_management` host surface.
- `freshquant/position_management/**` -> restart the `position_management` host surface.
- `freshquant/tpsl/**` -> restart the `tpsl` host surface.
- `freshquant/market_data/**` -> restart the `market_data` host surface; prewarm again when required.
- `freshquant/strategy/**` or `freshquant/signal/**` -> restart the `guardian` host surface.
- `freshquant/data/**` changes that affect Gantt or Shouban30 -> redeploy API and, when needed, rerun Dagster surfaces.
- `sunflower/QUANTAXIS/**` -> redeploy `fq_qawebserver` and any dependent host strategy surface.
- `morningglory/fqwebui/**` -> rebuild and redeploy Web UI.
- `morningglory/fqdagster/**` or `morningglory/fqdagsterconfig/**` -> restart Dagster webserver and daemon.
- `third_party/tradingagents-cn/**` -> rebuild `ta_backend` and `ta_frontend`.
- `runtime/symphony/**` -> sync the formal Symphony service and restart `fq-symphony-orchestrator`.
- Use `py -3.12 script/freshquant_deploy_plan.py` as the formal deploy-scope calculator before deciding the final release batch.
- All host deployment surfaces should go through `script/fqnext_host_runtime_ctl.ps1`, not ad-hoc process restarts.

Use this file as derived agent memory only. Formal runtime truth still comes from deploy results and `docs/current/**`.
