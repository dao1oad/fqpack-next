# Symphony Codex Shell Sandbox Diagnostic Design

## 背景

正式接入后的 `FRE-5` 已经能被 Symphony 正常领取，并能从 `Todo` 推进到 `Human Review` 再进入 `In Progress`。当前阻塞不在 Linear 轮询，也不在 project / state 配置，而是在实现阶段的 Codex 线程里，`shell_command` 一启动就以 Windows `0xC0000142` 退出。

现有证据表明：

- Symphony 服务本身健康，`/api/v1/state` 持续返回 `200`
- `linear_graphql` 的基础 introspection 查询可以成功
- `shell_command` 在 `workspace-write` 线程沙箱里稳定失败
- 正式 workflow 没有显式配置 sandbox，实际使用的是上游默认 `thread_sandbox = workspace-write` 与 `turn_sandbox_policy.type = workspaceWrite`

## 目标

用最小变更验证当前根因假设：`workspace-write` 沙箱在 Windows Service 场景下导致 Codex 线程命令执行器初始化失败。

## 非目标

- 不修改 `FRE-5` 业务代码
- 不调整 Linear 状态机、project、prompt 结构
- 不修改服务安装方式、账号模型或代理设置
- 不在这一步引入新的持久化观测或恢复机制

## 候选方案

### 方案 A：仅切换 Codex sandbox 做对照实验（推荐）

在正式 workflow 中显式配置：

- `codex.thread_sandbox: danger-full-access`
- `codex.turn_sandbox_policy.type: dangerFullAccess`

优点：

- 变更面最小
- 直接验证当前最强假设
- 若无效可快速回退

代价：

- 临时放宽正式服务中的 Codex 执行权限

### 方案 B：继续只调服务启动环境

继续补充 `PATH`、`ComSpec`、`SystemRoot`、`TEMP` 等变量，不改 sandbox。

优点：

- 更保守

缺点：

- 当前缺少直接证据
- 容易继续陷入盲调

### 方案 C：暂停正式服务，改用前台 runner 做对照

优点：

- 能区分“Windows Service 问题”与“Codex Windows sandbox 问题”

缺点：

- 会打断当前正式链路
- 操作更重，不适合先手验证

## 选型

采用方案 A。先只改正式 workflow 的 sandbox 配置，保留其它配置不变；同步部署副本后重启服务，再观察 `FRE-5` 是否恢复正常的 `shell_command`、token 推进和 issue 实施行为。

## 变更范围

- 修改 `runtime/symphony/WORKFLOW.freshquant.md`
- 同步到 `D:\fqpack\runtime\symphony-service\config\WORKFLOW.freshquant.md`

## 验收标准

重启服务后满足以下至少一条，视为假设成立：

1. `FRE-5` 的 Codex session 不再出现 `shell_command` 的 `0xC0000142`
2. `FRE-5` 的 `recent_events` 不再长期停在 `error`
3. session jsonl 中出现成功的 `shell_command` 调用输出

若仍失败，则说明问题不在默认 sandbox，需要回退配置并转向服务环境或 Codex Windows 运行时诊断。
