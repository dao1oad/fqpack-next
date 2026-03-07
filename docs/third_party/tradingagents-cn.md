---
name: third-party-tradingagents-cn
description: 记录 TradingAgents-CN 第三方源码纳入本仓库的来源、基线、运行边界和受控接入约束。
---

# TradingAgents-CN 第三方源码记录

## 1. 上游来源

- 上游仓库：`https://github.com/hsliuping/TradingAgents-CN`
- 纳入日期：2026-03-06
- 纳入基线：`bd599607e83cd0d249482e57869216d52b1cb2aa`
- 纳入方式：vendored source，存放于 `third_party/tradingagents-cn/`

## 2. 受控接入边界

- 本仓库按“受控第三方源码”方式纳入，不做子模块引用。
- 授权边界由接入方确认后执行，本仓库仅记录该接入决策，不替代法律审查。
- 阶段 1 运行形态仅包含：
  - `app/` FastAPI backend
  - `frontend/` Vue frontend
- `web/` 源码保留在 vendored tree 中，但本阶段不单独部署 Streamlit 服务。

## 3. 本仓库中的运行约束

- 运行编排：`docker/compose.parallel.yaml`
- 运行时配置单一真相源（single source of truth）：项目根目录 `.env`
- `third_party/tradingagents-cn/.env` 不再是本仓库正式运行入口；Docker 并行模式按 RFC `0016` 统一从根 `.env` 注入
- 共享基础设施：
  - MongoDB：`fq_mongodb:27017`
  - Redis：`fq_redis:6379`
- 逻辑隔离：
  - MongoDB 数据库：`tradingagents_cn`
  - Redis DB：`8`
- 运行时目录：
  - `runtime/tradingagents-cn/data`
  - `runtime/tradingagents-cn/logs`

## 4. 阶段 1 保留的上游行为

- 保留上游原生 A 股数据准备逻辑：
  - 本地 Mongo 检查
  - 按需补数
  - 分析结果落库
- 保留上游启动后触发一次股票基础信息同步的现状。
- 不替换 `TradingAgents-CN` 的数据源接口，不并入 FreshQuant 现有数据访问层。

## 5. 后续升级原则

- 如需升级上游版本，先记录新的上游 commit，再评估：
  - Dockerfile 变化
  - 环境变量变化
  - Mongo/Redis schema 变化
  - 分析 API 和前端反代契约变化
- 如需把数据源替换为 FreshQuant 内部数据接口，需另起 RFC。
