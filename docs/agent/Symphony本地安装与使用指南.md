---
name: symphony-local-installation-guide
description: OpenAI Symphony 本机安装结果、Windows 本地验证步骤，以及在 FreshQuant 项目中的推荐使用方式说明。
---

# Symphony 本地安装与使用指南

- 更新日期：2026-03-09
- 适用仓库：`D:\fqpack\freshquant-2026.2.23`
- 目标：说明 **本机安装 + 使用手册**；正式接入治理已转为仓库正式方案，另见 `docs/agent/Symphony正式接入治理说明.md` 与 `docs/rfcs/0028-symphony-first-governance.md`

## 1. 结论先看

当前机器已经完成 `openai/symphony` 官方 Elixir 参考实现的本机安装与最小验证：

- 上游仓库：`https://github.com/openai/symphony`
- 本机克隆路径：`D:\fqpack\tools\openai-symphony`
- 当前本机基线 commit：`b0e0ff0082236a73c12a48483d0c6036fdd31fe1`
- 本机额外安装：
  - `mise`：`D:\fqpack\tools\mise\mise\bin\mise.exe`
  - `Erlang`：`28.4`
  - `Elixir`：`1.19.5-otp-28`
- 已验证通过：
  - `mise exec -- mix setup`
  - `mise exec -- mix build`
  - `codex app-server --help`
  - `memory` tracker 本地 smoke test：`http://127.0.0.1:40123/api/v1/state` 返回 `200`

## 2. Symphony 是什么

按上游 README，`Symphony` 的定位不是项目内 SDK，而是一个 **工作编排器（work orchestrator）**：

- 轮询 issue tracker（默认是 `Linear`）
- 为每个 issue 创建隔离工作区
- 在工作区内启动 `codex app-server`
- 把工作流 prompt 发给 Codex 持续执行

上游当前提供两层内容：

- `SPEC.md`：产品/系统规格
- `elixir/`：实验性质（experimental）的 Elixir/OTP 参考实现

对 FreshQuant 而言，它更像“无人值守多任务编排参考实现”，不是可直接并入当前 Docker/Flask/Dagster 运行面的组件。

## 3. 本机安装结果

### 3.1 目录

- Symphony 源码：`D:\fqpack\tools\openai-symphony`
- 本地工作区建议根目录：`D:\fqpack\runtime\symphony-workspaces`

### 3.2 已执行安装步骤

1. 克隆上游仓库：

```powershell
git clone https://github.com/openai/symphony D:\fqpack\tools\openai-symphony
```

2. 直接从 `mise` GitHub Release 下载 Windows x64 包并解压到本机：

```powershell
Invoke-WebRequest `
  https://github.com/jdx/mise/releases/download/v2026.3.5/mise-v2026.3.5-windows-x64.zip `
  -OutFile D:\fqpack\tools\mise\mise-windows-x64.zip
Expand-Archive D:\fqpack\tools\mise\mise-windows-x64.zip D:\fqpack\tools\mise -Force
```

3. 按 `elixir/mise.toml` 安装运行时：

```powershell
$env:PATH = 'D:\fqpack\tools\mise\mise\bin;' + $env:PATH
Set-Location D:\fqpack\tools\openai-symphony\elixir
mise trust
mise install
```

4. 安装依赖并构建：

```powershell
mise exec -- mix setup
mise exec -- mix build
```

### 3.3 Windows 注意事项

`mix build` 期间会看到一条 `Phoenix.LiveView.ColocatedJS` 的 symlink warning；当前机器上该 warning **不阻塞构建成功**。
如果后续要消除此 warning，按上游提示，用管理员权限启动一次终端即可。

## 4. 本机最小验证（不接 Linear）

上游默认工作流依赖 `Linear`。如果只是验证本机安装是否可用，建议先使用 `memory` tracker。

### 4.1 新建最小工作流文件

示例文件：`D:\fqpack\tools\openai-symphony\elixir\WORKFLOW.memory.md`

```md
---
tracker:
  kind: memory
workspace:
  root: D:/fqpack/runtime/symphony-workspaces
agent:
  max_concurrent_agents: 1
  max_turns: 2
codex:
  command: codex app-server
server:
  port: 40123
---

Local smoke test workflow for FreshQuant.
```

### 4.2 启动方式

在 Windows 本机上做临时 smoke test 时，建议用 `mix run --no-start` 先注入工作流路径和端口，再手动启动应用，避免 `mix run` 先按默认 `WORKFLOW.md` 自动启动。

示例脚本：`smoke_test.exs`

```elixir
SymphonyElixir.Workflow.set_workflow_file_path(
  "D:/fqpack/tools/openai-symphony/elixir/WORKFLOW.memory.md"
)

Application.put_env(:symphony_elixir, :server_port_override, 40123)
{:ok, _} = Application.ensure_all_started(:symphony_elixir)
Process.sleep(:infinity)
```

启动：

```powershell
$env:PATH = 'D:\fqpack\tools\mise\mise\bin;' + $env:PATH
Set-Location D:\fqpack\tools\openai-symphony\elixir
mise exec -- mix run --no-start smoke_test.exs
```

验证：

```powershell
Invoke-WebRequest http://127.0.0.1:40123/api/v1/state
```

本机实测返回 `200`，返回体示例：

```json
{
  "running": [],
  "retrying": [],
  "counts": {
    "running": 0,
    "retrying": 0
  }
}
```

说明：

- 这一步只证明 `Symphony + Phoenix dashboard/API + memory tracker` 在本机可启动
- 如果后续要真正派发 Codex 任务，仍然需要本机 `codex` CLI 已可正常登录和调用
- `codex app-server --help` 能运行，只能说明命令存在，不等于会话认证已经就绪

## 5. 在 FreshQuant 项目中如何使用

### 5.1 当前推荐用法

当前文档仍只覆盖“安装与本机验证”。正式接入治理已单独收口到：

- `docs/agent/Symphony正式接入治理说明.md`
- `docs/rfcs/0028-symphony-first-governance.md`

本页更适合把 `Symphony` 当作：

- 本机研究/演示工具
- 无人值守工作流编排参考实现
- 将来如需引入多 agent 调度时的 RFC 背景材料

当前 **不建议** 直接把它当成 FreshQuant 正式运行组件，原因有三点：

1. 本仓库当前治理要求非常强：
   - 禁止在本地 `main` 直接开发
   - 强制 `git worktree + feature branch`
   - 新增入口/依赖/破坏性变更要先过 RFC

2. 上游参考实现默认模型是：
   - issue -> repo copy/workspace -> unattended Codex
   - 这和本仓库当前“人工评审 + RFC 前置 + worktree 开发”的治理习惯并不完全一致

3. 上游默认依赖 `Linear`：
   - 当前 FreshQuant 仓库并没有现成的 Linear 流程和状态机配置

### 5.2 建议的使用层级

### 层级 A：本机评估（推荐）

只做以下事情：

- 安装并跑通 `memory` tracker
- 理解 `WORKFLOW.md` 契约
- 评估它是否适合未来的多任务调度需求

这是当前最稳妥的使用方式。

### 层级 B：面向文档/RFC 的半自动化试点（可选）

如果确实要在本项目试用，建议先把范围限制为：

- 只生成/更新文档
- 只写 RFC 草案
- 只处理低风险、可回滚、无需外部部署的工作

不建议一开始就让它直接改交易域、运行时配置、Docker 编排或生产数据链路。

### 层级 C：正式接入项目运行链（已转正式治理方案）

现在如果要把 `Symphony` 作为 FreshQuant 的正式编排能力纳入项目，应按仓库正式治理执行：

- 使用 `Linear issue` 作为唯一任务入口
- 使用 `Todo / Human Review / In Progress / Rework / Merging / Done` 状态机
- 把唯一人工门收敛为 `Human Review -> In Progress`
- 使用正式治理说明与 RFC 0028 作为边界依据

本页不重复展开正式治理细节，详见：

- `docs/agent/Symphony正式接入治理说明.md`
- `docs/rfcs/0028-symphony-first-governance.md`

### 5.3 如果要做 FreshQuant 本地试点，建议这样配

建议把自定义工作流文件放在仓库外，例如：

- `D:\fqpack\runtime\symphony\WORKFLOW.freshquant.md`

最小示例：

```md
---
tracker:
  kind: linear
  api_key: $LINEAR_API_KEY
  project_slug: your-linear-project-slug
workspace:
  root: D:/fqpack/runtime/symphony-workspaces
hooks:
  after_create: |
    git clone --depth 1 ssh://git@ssh.github.com:443/dao1oad/fqpack-next.git .
agent:
  max_concurrent_agents: 1
  max_turns: 20
codex:
  command: codex --config shell_environment_policy.inherit=all app-server
  approval_policy: never
  thread_sandbox: workspace-write
server:
  port: 40123
---

你正在 FreshQuant 仓库中工作，必须遵守仓库根 AGENTS.md：

- 默认使用简体中文
- 禁止在 main 直接开发
- 涉及新增入口/依赖/破坏性变更时，先写 RFC
- 优先做文档、RFC、低风险改动
- 不要直接修改生产部署配置，除非 issue 明确要求且验收标准完整
```

### 5.4 使用前提

如果要从 `memory` tracker 切到真实工作流，至少还需要：

- 本机 `codex` CLI 已完成登录，且 `codex app-server` 可实际启动
- `LINEAR_API_KEY`
- 一个可用的 Linear project slug
- 按上游工作流要求补齐状态：
  - `Todo`
  - `In Progress`
  - `Human Review`
  - `Rework`
  - `Merging`
  - 终态如 `Done / Closed / Cancelled / Duplicate`

如果没有 Linear，当前就只能把它当作本机参考实现使用。

## 6. 与当前项目治理的冲突点

在 FreshQuant 中使用 `Symphony` 前，需要先知道这些边界：

- **工作区模型已经定稿**
  - 正式治理接受 `Symphony-managed workspace/repo copy`
  - 不再把全仓强制 `git worktree + feature branch` 作为唯一合法模型

- **无人值守边界已定稿**
  - 设计批准前仍然禁止编码
  - 设计批准后允许自动编码、测试、PR、合并

- **外部依赖已定稿**
  - 正式运行依赖 `Linear`
  - 这已经不只是“工具安装”，而是仓库正式治理的一部分

因此，当前最合理的结论是：

- 本次安装结果可用于 **本机评估**
- 正式开发流程请转到正式治理说明，而不是只看安装手册

## 7. 常用命令

### 查看运行时版本

```powershell
$env:PATH = 'D:\fqpack\tools\mise\mise\bin;' + $env:PATH
Set-Location D:\fqpack\tools\openai-symphony\elixir
mise exec -- elixir --version
```

### 重新拉取上游最新代码

```powershell
Set-Location D:\fqpack\tools\openai-symphony
git fetch --all --tags --prune
git pull --ff-only
```

### 上游更新后重装依赖

```powershell
$env:PATH = 'D:\fqpack\tools\mise\mise\bin;' + $env:PATH
Set-Location D:\fqpack\tools\openai-symphony\elixir
mise trust
mise install
mise exec -- mix setup
mise exec -- mix build
```

## 8. 参考链接

- 上游仓库：`https://github.com/openai/symphony`
- 上游规格：`https://github.com/openai/symphony/blob/main/SPEC.md`
- 上游 Elixir 说明：`https://github.com/openai/symphony/blob/main/elixir/README.md`
- Codex App Server 说明：`https://developers.openai.com/codex/app-server/`
