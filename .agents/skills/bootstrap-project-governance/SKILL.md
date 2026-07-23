---
name: bootstrap-project-governance
description: "Set up lightweight project governance. Use for 项目初始化、项目治理、Agent 漏检、HTML 看板或 Agent 自主运行。"
---

# Bootstrap Project Governance

Install a small repository-local governance runtime shared by Codex and Devin: startup contract, declared checks, host-native Stop Hooks, project-local Cloud Skills, evidence log, and derived HTML board.

Run this skill after the project goal exists and before implementation starts. A complete solution or implementation plan is not required.

## 1. Inspect and plan

Read the repository, active `AGENTS.md`, tests, build commands, Git state, data paths, permissions, and external dependencies. Resolve facts from the environment.

```powershell
$skill = @(
  (Join-Path (Get-Location) '.agents\skills\bootstrap-project-governance'),
  (Join-Path $env:APPDATA 'Devin\skills\bootstrap-project-governance'),
  (Join-Path $HOME '.agents\skills\bootstrap-project-governance'),
  (Join-Path $HOME '.codex\skills\bootstrap-project-governance')
) | Where-Object { Test-Path (Join-Path $_ 'scripts\bootstrap_governance.py') } | Select-Object -First 1
py -3 -X utf8 "$skill\scripts\bootstrap_governance.py" plan --repo TARGET
```

On POSIX, use `python3` with the same script and arguments.

## 2. Confirm the startup contract

Apply the grilling protocol only during startup: inspect discoverable facts first, ask one decision at a time, recommend an answer, and wait for confirmation before the next decision. Stop when these are confirmed:

- outcome, non-goals, and hard boundaries;
- final acceptance and the V2 real-data chain;
- Agent authority over implementation, rolling plans, and soft Gates;
- run budgets, permissions, dependencies, and fallbacks.

Runtime user questions and runtime grilling are outside this workflow.

## 3. Install and configure

```powershell
py -3 -X utf8 "$skill\scripts\bootstrap_governance.py" apply `
  --repo TARGET --project-name NAME
```

Fill:

- `.governance/project.json`: the complete fixed startup contract;
- `.governance/work.json`: the Agent-owned rolling plan and Gate registry. Required work bindings and their Gate specifications are frozen at startup; only additional or explicitly soft work may change autonomously.

Use V0/V1 for development feedback and V2/real for final claims. Read [model.md](references/model.md) for the compact schema examples.

## 4. Start autonomy

Review and trust the installed Codex and Devin project Hooks, make the preflight flags factual, then run:

```powershell
py -3 -X utf8 TARGET\tools\governance.py ready --repo TARGET
py -3 -X utf8 TARGET\tools\governance.py start --repo TARGET
```

`start` freezes `.governance/project.json` plus all `requiredForFinal` work bindings and Gate specifications, writes `AUTONOMY_STARTED`, and creates `.governance/board.html`.

## 5. Execute and finish

Run every declared check through the governance runner:

```powershell
py -3 -X utf8 tools\governance.py record --type WORK_STARTED --item WI-001
py -3 -X utf8 tools\governance.py run --item WI-001 --gate GATE
py -3 -X utf8 tools\governance.py record --type WORK_IMPLEMENTED --item WI-001
py -3 -X utf8 tools\governance.py check --completion
```

The active host's Stop Hook supplies internal continuations for missing or stale evidence. Repeated identical failures require a route, source, Gate, or verifier change. The Agent proceeds until:

- `COMPLETED`: required work, current checks, and final claims pass;
- `EXHAUSTED`: a locked budget is reached and the final evidence report is emitted.

For Devin Cloud working on a Windows checkout through XN, load the repository `AGENTS.md`, optional `.agents/handoffs/main.md`, and `.agents/skills` at the start. Execute repository commands through XN. Before the final response, submit a Stop JSON payload to `tools/governance.py hook-stop` through XN; continue internally on `decision: block` and finish only on `decision: approve`. A governed Cloud gateway may automate this same loop.

Validate the repository layer before reporting completion:

```powershell
py -3 -X utf8 tools\governance.py validate
py -3 -X utf8 tools\governance.py derive
py -3 -X utf8 tools\governance.py validate
```

Report runtime state, contract digest, check results, board path, and remaining evidence gaps.
