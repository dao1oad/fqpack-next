# 当前配置

## 配置真相源

- Dynaconf
- 环境变量
- Mongo / Redis 参数
- 根 `.env`（尤其对 TradingAgents-CN）

## 当前关注的配置域

- `mongodb.*`
- `redis.*`
- `order_management.*`
- `position_management.*`
- `xtquant.*`
- `runtime_observability.*`

## 配置优先级

- 环境变量覆盖文件默认值
- Docker 并行环境优先使用映射后的宿主机端口
- TradingAgents-CN 以根 `.env` 为单一真相源

## 当前模板位置

- `deployment/examples/freshquant.yaml`
- `deployment/examples/envs.fqnext.example`
- `deployment/examples/supervisord.fqnext.example.conf`
