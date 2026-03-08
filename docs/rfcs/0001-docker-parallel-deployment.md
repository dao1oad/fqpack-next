---
name: rfc-0001-docker-parallel-deployment
description: 在宿主机旧 freshquant 已运行且端口被占用的情况下，为 freshquant-2026.2.23 提供 Docker 并行部署方案（端口隔离、最小验证与排障）。
---

# RFC 0001: Docker 并行部署（与宿主机 `D:\\fqpack\\freshquant` 并行）

- **状态**：Done
- **负责人**：TBD
- **评审人**：TBD
- **创建日期**：2026-03-05
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

当前宿主机 `D:\\fqpack\\freshquant` 以“宿主机进程 + Supervisor”的方式运行，已占用核心端口（80/5000/5001/6379/27017 等）。在迁移与验证阶段，需要让目标仓库 `D:\\fqpack\\freshquant-2026.2.23` **同时运行**，以便：

- 不中断既有线上/宿主机运行链路
- 支持新仓库的功能对齐、回归验证与迭代
- 在端口隔离的前提下完成 Web UI/API/Redis/MongoDB 等最小闭环

## 2. 目标（Goals）

- 提供一键可复现的 Docker Compose 并行启动方式（不依赖修改 `D:\\fqpack\\config/`、`supervisord/`、`mongodb/`、`redis/` 等宿主机部署目录）。
- 明确端口隔离与访问入口，保证与宿主机旧项目并行运行不冲突。
- 提供最小验证与排障手册，降低环境问题导致的启动失败成本。

## 3. 非目标（Non-Goals）

- 不替换现有宿主机 Supervisor 部署策略，不改动其端口/配置/数据目录。
- 不对业务逻辑做功能迁移/重构（仅限并行部署与必要的小修复）。
- 不承诺生产环境安全加固与高可用方案（本 RFC 面向本机并行验证）。

## 4. 范围（Scope）

**In Scope**
- 新增 `docker/compose.parallel.yaml`：并行部署（Web UI / API / TDXHQ / Dagster Web UI + daemon / QAWebServer / Redis / MongoDB）。
- 端口映射与文档：避免与宿主机旧项目冲突。
- 让 Web UI 反代在容器重建后不易出现 502（Docker DNS 动态解析）。
- 修复 `tdxhq` 网关对 `int` 返回值的错误处理（避免 500）。

**Out of Scope**
- Huey worker / 各类采集任务的并行编排（后续如需可另起 RFC）。
- 与宿主机共享数据/连接宿主机 Mongo/Redis（默认使用 Docker 内独立实例）。

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**
- Docker Compose 仅作为本仓库并行运行入口，提供清晰的启动/停止/清理方式。
- 严格避免占用宿主机旧项目端口。

**不负责（Must Not）**
- 不触碰宿主机部署目录与敏感配置（例如 `D:\\fqpack\\config/envs.conf`）。

**依赖（Depends On）**
- Docker Desktop（含 `docker compose`）
- 访问 Docker Hub / npm/pypi 镜像（必要时可预拉取基础镜像）

## 6. 对外接口（Public API）

本 RFC 的“对外接口”主要是端口与访问入口（均为本机 localhost）：

- Web UI：`http://127.0.0.1:18080/`
- Dagster UI：`http://127.0.0.1:11003/`（容器内 `10003`）
- API Server：`http://127.0.0.1:15000/api/*`
- TDXHQ：`http://127.0.0.1:15001/*`
- Redis：`127.0.0.1:6380`
- MongoDB：`127.0.0.1:27027`
- QAWebServer：`http://127.0.0.1:18010/`（供 Web UI 的 `/api/qa/*` 反代使用）

## 7. 数据与配置（Data / Config）

- 后端容器使用仓库根 `.env` 注入必要环境变量（不包含敏感信息）。
- Mongo/Redis 使用 Docker named volumes（与宿主机 `D:\\fqpack\\mongodb/redis` 目录隔离）。

## 8. 破坏性变更（Breaking Changes）

无。该方案为新增并行部署入口，不改变宿主机旧项目端口与行为。

## 9. 迁移映射（From `D:\\fqpack\\freshquant`）

本 RFC 不涉及业务能力迁移，仅提供并行运行环境与最小问题修复。

## 10. 测试与验收（Acceptance Criteria）

- [ ] 执行 `docker compose -f docker/compose.parallel.yaml up -d --build` 可成功启动全部服务
- [ ] 访问 `http://127.0.0.1:18080/` 返回 200
- [ ] 访问 `http://127.0.0.1:11003/` 返回 200
- [ ] `dagster-daemon liveness-check` 返回 `Daemon live`
- [ ] 访问 `http://127.0.0.1:18080/api/get_stock_pools_list?page=1` 返回 200（说明反代链路 OK）
- [ ] 访问 `http://127.0.0.1:15001/get_security_count?market=0` 返回 200（说明 tdxhq 基本可用）
- [ ] 宿主机旧项目端口（80/5000/5001/6379/27017 等）仍保持占用且不被影响

## 11. 风险与回滚（Risks / Rollback）

- 构建耗时：`docker/Dockerfile.rear` 与 `docker/Dockerfile.web` 首次 build 较慢。
- 网络波动：Docker Hub 鉴权偶发失败可通过预拉取基础镜像缓解。
- 回滚：`docker compose -f docker/compose.parallel.yaml down -v` 清理本 RFC 引入的容器/网络/卷即可。

## 12. 里程碑与拆分（Milestones）

- M1：Compose 与端口隔离落地
- M2：部署文档与 agent 指令更新
- M3：并行启动验证通过（Done）
