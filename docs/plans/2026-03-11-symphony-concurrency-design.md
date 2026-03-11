# Symphony 按状态并发配置设计

## 背景

FreshQuant 已将 `Symphony` 作为正式开发编排器接入，但当前正式 workflow 仍配置为：

- `agent.max_concurrent_agents: 1`

这意味着所有活跃 `Linear issue` 都只能串行处理。对正式接入来说，这不是 `Symphony` 的产品限制，而是当前仓库模板主动收紧后的运行策略。随着真实 issue 数量增长，这会造成两个直接问题：

1. `Todo` 设计票和 `In Progress` 实现票互相阻塞。
2. 一个长时间运行的实现票会让其他待处理 issue 长时间无法被领取。

同时，FreshQuant 的 `Merging` 阶段已经绑定自动部署与宿主机服务重启，因此不能简单把全局并发直接放大到默认的 `10`。

## 目标

- 将正式 workflow 从“全局串行”调整为“按状态并发”。
- 保持设计阶段和部署阶段保守，避免资源争抢和部署冲突。
- 让实现阶段最多允许两个 issue 同时运行，提高吞吐但不引入明显运维风险。
- 保证仓库模板、宿主机运行目录和治理说明一致。

## 非目标

- 本次不引入多实例 `Symphony` 服务。
- 本次不改 `Linear` 状态机。
- 本次不引入 webhook 驱动。
- 本次不扩大 `Merging` 的自动部署权限边界。

## 方案对比

### 方案 1：保持全局串行

- 配置保持 `max_concurrent_agents: 1`
- 优点：最稳定，部署与服务重启不会互相影响
- 缺点：吞吐最低，真实多票场景下等待时间长

### 方案 2：全局并发 2

- 只把 `max_concurrent_agents` 改成 `2`
- 优点：实现最简单
- 缺点：`Todo`、`Rework`、`Merging` 都会共享这 2 个槽位，部署阶段可能与实现阶段抢占资源

### 方案 3：按状态并发，推荐

- 全局上限 `2`
- 状态级覆盖：
  - `Todo: 1`
  - `In Progress: 2`
  - `Rework: 1`
  - `Merging: 1`
- 优点：
  - 设计阶段仍然保守，不会并发读仓库上下文导致噪声放大
  - 实现阶段允许 2 个 issue 并发，提高吞吐
  - `Rework` 与 `Merging` 保持单槽，避免部署、重启和返工争抢
- 缺点：比单一全局参数多一层配置说明，需要文档同步

## 推荐方案

采用方案 3。

理由：

- 当前正式治理已经把 `Merging` 定义为 `merge + deploy + health check`，因此部署阶段天然需要串行化。
- 真实瓶颈主要出现在 `In Progress`，而不是 `Todo` 或 `Merging`。
- 上游 Symphony 已支持 `max_concurrent_agents_by_state`，改动只需要调整 workflow 模板和治理文档，不需要修改 orchestrator 代码。

## 具体配置

正式 workflow 调整为：

```yaml
agent:
  max_concurrent_agents: 2
  max_concurrent_agents_by_state:
    Todo: 1
    In Progress: 2
    Rework: 1
    Merging: 1
  max_turns: 60
```

解释：

- `Todo=1`：设计仍串行，避免多个设计票同时占用上下文和 token
- `In Progress=2`：允许两个实现票并发
- `Rework=1`：返工通常伴随 review/CI/排障，先保持保守
- `Merging=1`：部署和宿主机服务操作保持串行

## 文件改动范围

- `runtime/symphony/WORKFLOW.freshquant.md`
- `runtime/symphony/README.md`
- `docs/agent/Symphony正式接入治理说明.md`
- `docs/migration/progress.md`

必要时同步：

- `D:\fqpack\runtime\symphony-service\config\WORKFLOW.freshquant.md`

## 验收标准

- 仓库内正式 workflow 模板包含 `max_concurrent_agents_by_state`
- `runtime/symphony/README.md` 和治理说明明确写出并发策略
- 宿主机运行目录同步后，服务读取到新的并发上限
- `/api/v1/state` 在存在多个活跃 issue 时，允许最多 2 个实现阶段 issue 同时运行
