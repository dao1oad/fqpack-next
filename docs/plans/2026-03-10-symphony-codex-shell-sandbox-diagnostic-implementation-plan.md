# Symphony Codex Shell Sandbox Diagnostic Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 通过最小配置变更验证正式 Symphony 服务中的 Codex `workspace-write` 沙箱是否导致 Windows `shell_command` 初始化失败。

**Architecture:** 仅修改正式 workflow 的 Codex sandbox 配置，不改服务安装、Linear 状态机或 issue prompt。通过同步部署副本并重启服务，对 `FRE-5` 做一次对照验证。

**Tech Stack:** PowerShell, Elixir Symphony runtime, Codex app-server, Linear-backed workflow

---

### Task 1: 写入设计与计划文档

**Files:**
- Create: `docs/plans/2026-03-10-symphony-codex-shell-sandbox-diagnostic-design.md`
- Create: `docs/plans/2026-03-10-symphony-codex-shell-sandbox-diagnostic-implementation-plan.md`

**Step 1: 写设计文档**

记录背景、候选方案、推荐方案、变更范围与验收标准。

**Step 2: 写实施计划**

把配置修改、同步部署与运行验证拆成独立步骤。

**Step 3: Commit**

```bash
git add docs/plans/2026-03-10-symphony-codex-shell-sandbox-diagnostic-design.md docs/plans/2026-03-10-symphony-codex-shell-sandbox-diagnostic-implementation-plan.md
git commit -m "docs: 记录 codex shell sandbox 对照实验"
```

### Task 2: 修改正式 workflow sandbox 配置

**Files:**
- Modify: `runtime/symphony/WORKFLOW.freshquant.md`

**Step 1: 编辑 workflow**

在 `codex` 段加入：

```yaml
thread_sandbox: danger-full-access
turn_sandbox_policy:
  type: dangerFullAccess
```

保留现有 `command: codex --config shell_environment_policy.inherit=all app-server` 不变。

**Step 2: 静态检查**

核对 YAML front matter 结构仍合法，且仅 sandbox 配置发生变化。

**Step 3: Commit**

```bash
git add runtime/symphony/WORKFLOW.freshquant.md
git commit -m "fix: 放宽 codex sandbox 做正式对照实验"
```

### Task 3: 同步部署副本

**Files:**
- Modify (deployed copy via sync): `D:/fqpack/runtime/symphony-service/config/WORKFLOW.freshquant.md`

**Step 1: 运行同步脚本**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File D:\fqpack\freshquant-2026.2.23\.worktrees\brainstorm-symphony-governance\runtime\symphony\scripts\sync_freshquant_symphony_service.ps1
```

Expected: 同步成功，运行目录中的 `WORKFLOW.freshquant.md` 与仓库版本一致。

**Step 2: 核对部署副本**

Run:

```powershell
Get-Content D:\fqpack\runtime\symphony-service\config\WORKFLOW.freshquant.md
```

Expected: 能看到 `thread_sandbox: danger-full-access` 和 `type: dangerFullAccess`。

### Task 4: 重启服务并验证 FRE-5

**Files:**
- Observe: `D:/fqpack/runtime/symphony-service/logs/app-server.trace.log`
- Observe: `C:/Users/Administrator/.codex/sessions/...`

**Step 1: 重启服务**

Run:

```powershell
Restart-Service fq-symphony-orchestrator
```

**Step 2: 触发刷新**

Run:

```powershell
Invoke-WebRequest -Method Post -UseBasicParsing http://127.0.0.1:40123/api/v1/refresh
```

**Step 3: 检查 issue 运行态**

Run:

```powershell
Invoke-RestMethod http://127.0.0.1:40123/api/v1/FRE-5 | ConvertTo-Json -Depth 8
```

Expected: `recent_events` 不再长期停在 `error`。

**Step 4: 检查 session / trace**

Run:

```powershell
Get-Content D:\fqpack\runtime\symphony-service\logs\app-server.trace.log -Tail 120
```

Expected: 不再出现 `shell_command` 秒退 `0xC0000142`。

### Task 5: 评估结果并决定回退/继续

**Files:**
- Observe: `runtime/symphony/WORKFLOW.freshquant.md`

**Step 1: 若对照实验成功**

记录该结论，继续推进 `FRE-5` 的真实实现诊断。

**Step 2: 若对照实验失败**

回退 workflow 中的 sandbox 配置，转向服务环境变量或 Codex Windows 运行时问题排查。

**Step 3: Commit**

```bash
git add runtime/symphony/WORKFLOW.freshquant.md
git commit -m "chore: 收口 codex sandbox 对照实验结果"
```
