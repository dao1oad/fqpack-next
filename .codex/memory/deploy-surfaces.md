# Deploy Surfaces

- `freshquant/rear/**` affects API deployment.
- `runtime/symphony/**` affects the formal Symphony orchestrator service.
- `morningglory/fqwebui/**` requires rebuilding and redeploying Web UI.
- `freshquant/market_data/**` changes usually require host runtime restart for producer or consumer.

Use this file as derived agent memory only. Formal runtime truth still comes from deploy results and `docs/current/**`.
