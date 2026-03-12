# TradingAgents-CN

## 职责

负责 TradingAgents-CN 的当前接入、部署与运行边界。

## 入口

- `ta_backend`
- `ta_frontend`

## 依赖

- 根 `.env`
- Mongo
- Redis
- Docker 并行部署

## 数据流

frontend -> backend -> analysis workflow -> Mongo / Redis

## 存储

使用独立的 TradingAgents-CN 数据边界。

## 配置

根 `.env` 是当前单一真相源。

## 部署/运行

并行部署端口默认：

- backend：`13000`
- frontend：`13080`

## 排障点

- `.env` 不一致
- Mongo / Redis 端口错误
- 分析请求卡住
