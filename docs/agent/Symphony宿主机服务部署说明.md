---
name: symphony-host-service-deployment-guide
description: FreshQuant 在 Windows 宿主机上以正式服务形态运行 Symphony 的目录结构、脚本、NSSM 安装方式与运维说明。
---

# Symphony 宿主机服务部署说明

- 更新日期：2026-03-10
- 适用仓库：`D:\fqpack\freshquant-2026.2.23`
- 对应 RFC：`docs/rfcs/0028-symphony-first-governance.md`

## 1. 目标

本说明只覆盖 **宿主机正式运行面**：

- 让 `Symphony` 不再依赖手工终端启动
- 让它以 Windows 常驻服务形态运行
- 继续使用当前账号，而不是专用服务账号

## 2. 正式运行形态

- 运行时：宿主机原生 `Elixir/OTP + Phoenix`
- 服务包装：`NSSM`
- 服务名：`fq-symphony-orchestrator`
- 登录账号：当前 Windows 账号
- 调度方式：`Linear` 30 秒轮询

## 3. 目录结构

仓库内保存版本化模板：

- `runtime/symphony/WORKFLOW.freshquant.md`
- `runtime/symphony/prompts/*`
- `runtime/symphony/templates/*`
- `runtime/symphony/scripts/*`

宿主机实际运行目录：

- `D:\fqpack\runtime\symphony-service\config\`
- `D:\fqpack\runtime\symphony-service\scripts\`
- `D:\fqpack\runtime\symphony-service\logs\`
- `D:\fqpack\runtime\symphony-service\workspaces\`
- `D:\fqpack\runtime\symphony-service\artifacts\`

## 4. 关键脚本

- `runtime/symphony/scripts/sync_freshquant_symphony_service.ps1`
  - 把仓库内版本化模板同步到宿主机运行目录
- `runtime/symphony/scripts/start_freshquant_symphony.ps1`
  - 正式启动脚本
- `runtime/symphony/scripts/freshquant_runner.exs`
  - 正式 runner
- `runtime/symphony/scripts/install_freshquant_symphony_service.ps1`
  - 用 `NSSM` 安装/更新 Windows 服务
- `runtime/symphony/scripts/reinstall_freshquant_symphony_service.ps1`
  - 删除错误残留服务、重新安装并启动、最后做健康检查

## 5. 环境变量

正式运行至少需要：

- `LINEAR_API_KEY`
- 必要时：
  - `HTTP_PROXY`
  - `HTTPS_PROXY`
  - `ALL_PROXY`

建议把这些值配置成当前账号的 **用户环境变量**，而不是只在某个临时 PowerShell 会话里设置。

## 6. 同步模板到运行目录

```powershell
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/sync_freshquant_symphony_service.ps1
```

这一步会创建并更新：

- `D:\fqpack\runtime\symphony-service\config\`
- `D:\fqpack\runtime\symphony-service\scripts\`
- `D:\fqpack\runtime\symphony-service\logs\`
- `D:\fqpack\runtime\symphony-service\workspaces\`
- `D:\fqpack\runtime\symphony-service\artifacts\`

## 7. 安装 Windows 服务

前提：

- 已安装 `NSSM`
- 当前账号具备可用的 `codex` / Git / SSH / 代理上下文
- 当前账号密码可用于服务安装
- 必须在 **提升权限的 PowerShell（Run as Administrator）** 中执行安装脚本

如果当前账号本身没有密码，也可以使用空密码，但前提是：

- 本机 `LimitBlankPasswordUse = 0`
- 即已经关闭 “Accounts: Limit local account use of blank passwords to console logon only”

默认会优先尝试这些 `NSSM` 路径：

- `nssm`（已在 `PATH` 中）
- `D:\fqpack\tools\nssm\nssm.exe`
- `C:\Program Files\nssm\nssm.exe`
- `C:\Program Files (x86)\nssm\nssm.exe`

示例：

```powershell
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/install_freshquant_symphony_service.ps1 `
  -ServicePassword '<你的当前账号密码>'
```

说明：

- 本方案明确不用专用服务账号
- 但 Windows Service 仍然需要当前账号密码来把服务绑定到该账号
- 如果不是在提升权限 PowerShell 中执行，安装脚本会直接失败，不再尝试半途注册服务
- 当 `LimitBlankPasswordUse = 0` 时，安装脚本允许空密码账号继续安装服务
- 如果 `NSSM` 不在 `PATH` 中，也可以显式传入：

```powershell
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/install_freshquant_symphony_service.ps1 `
  -NssmPath 'D:\fqpack\tools\nssm\nssm.exe' `
  -ServicePassword '<你的当前账号密码>'
```

如果之前已经在非提升权限终端下留下了错误的 `LocalSystem` 服务，可以在提升权限 PowerShell 中直接重跑安装脚本，脚本会按现有服务做更新；必要时也可以先执行：

```powershell
sc.exe delete fq-symphony-orchestrator
```

然后重新运行安装脚本。

如果只是想“一键修复并启动”，推荐直接运行：

```powershell
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/reinstall_freshquant_symphony_service.ps1
```

说明：

- 仍然必须在提升权限 PowerShell 中运行
- 默认会交互式提示输入当前 Windows 账号密码，不会把密码写死到脚本文件里
- 如果账号无密码，直接回车即可
- 会自动执行：
  - 删除旧 `fq-symphony-orchestrator`
  - 调用正式安装脚本
  - 启动服务
  - 访问 `http://127.0.0.1:40123/api/v1/state`
  - 如果健康检查失败，自动输出 `stdout.log` / `stderr.log` 尾部

## 8. 启动与重启

安装完成后：

```powershell
Start-Service fq-symphony-orchestrator
Restart-Service fq-symphony-orchestrator
Get-Service fq-symphony-orchestrator
```

健康检查：

```powershell
Invoke-WebRequest http://127.0.0.1:40123/api/v1/state
```

## 9. 日志

宿主机日志目录：

- `D:\fqpack\runtime\symphony-service\logs\stdout.log`
- `D:\fqpack\runtime\symphony-service\logs\stderr.log`
- `D:\fqpack\runtime\symphony-service\logs\app-server.trace.log`

## 10. 升级流程

1. 在仓库里更新 `runtime/symphony/*`
2. 合并到 `main`
3. 重新运行 `sync_freshquant_symphony_service.ps1`
4. `Restart-Service fq-symphony-orchestrator`
5. 通过 `/api/v1/state` 与日志确认新版本生效

## 11. 回滚流程

1. 回退仓库版本到旧 commit/tag
2. 重新运行 `sync_freshquant_symphony_service.ps1`
3. `Restart-Service fq-symphony-orchestrator`

不要直接在宿主机 `symphony-service` 目录中手工热改文件，否则无法审计。
