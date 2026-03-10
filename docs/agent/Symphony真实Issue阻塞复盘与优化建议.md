---
name: symphony-fre-5-postmortem
description: 复盘 FRE-5 在 Symphony 正式接入中的多次阻塞、最终成功条件，以及建议固化的配置与流程优化。
---

# Symphony 真实 Issue 阻塞复盘与优化建议

## 适用范围

本文档复盘 `FRE-5`（`KlineSlim页面鼠标放大缩小时会有残影`）在 FreshQuant 正式接入 Symphony 过程中的真实运行情况。重点不是业务修复细节，而是：

- 为什么一条真实 issue 会多次阻塞
- 哪些问题属于 Symphony 运行面，而不是仓库代码
- 最后为什么仍然成功完成
- 后续应固化哪些配置与流程

## 最终结果

`FRE-5` 最终并没有失败，而是产出了已合并的 `PR #65`：`fix: 修复 KlineSlim 缩放平移卡顿并补浏览器回归`。Linear 最终评论中也记录了收口证据：

- GitHub PR 已合并
- `governance / pre-commit / pytest` 全部成功
- 本地复核包括 `node --test`、`npm run build` 与 Playwright 浏览器回归

因此，这次复盘的重点不是“为什么没做完”，而是“为什么中途会多次卡住，以及为什么后来又能恢复”。

## 发生的问题

### 1. 早期阻塞：agent 进程直接 `:epipe`

最早的一批失败根本没有进入稳定会话，服务日志中可以看到 `FRE-5` 多次启动后立即以 `:epipe` 退出，并进入 backoff retry。

这类失败的特征是：

- 还没开始有效代码读取或修改
- session id 常为空或刚创建即断开
- 问题在 orchestrator / app-server 之间，而不是业务仓库

### 2. 中期阻塞：`shell_command` 对最小命令也失败

进入 `In Progress` 后，Linear 评论反复记录了统一错误码 `-1073741502`（Windows `0xC0000142`）。这说明：

- 失败与具体命令内容无关
- `cmd.exe`、`python`、PowerShell 等最小命令都失败
- 问题不在 `KlineSlim` 业务代码，而在当前 agent 会话的本地命令执行器初始化

这一步之所以关键，是因为它把问题从“代码逻辑”准确缩小到“运行环境”。

### 3. 传输层不稳定：WebSocket 多次超时

`app-server.trace.log` 中还能看到多次：

- `failed to connect to websocket`
- `wss://chatgpt.com/backend-api/codex/responses`
- 之后 `Falling back from WebSockets to HTTPS transport`

这说明在当时的服务环境中，Codex 传输层并不稳定。即使 turn 已经开始，也会因为 WebSocket 断流而重复重连，进一步放大实现阶段的不稳定性。

### 4. 默认沙箱配置与 Windows 服务环境叠加

早期 trace 中的 thread / turn sandbox 明确是：

- `workspace-write`
- `workspaceWrite`

而在 Windows 服务场景下，这与命令执行器初始化问题叠加后，表现得尤为脆弱。后续我们把正式 workflow 明确写成：

- `thread_sandbox: danger-full-access`
- `turn_sandbox_policy.type: dangerFullAccess`

这不是唯一修复因素，但它至少去掉了一个明显的高风险变量。

## 为什么最终还是成功了

### 1. 设计上下文没有丢

`Todo -> Human Review -> In Progress` 这条链路虽然中途反复受阻，但设计阶段已经在 Linear 留下了高质量上下文：

- 4 类根因假设
- 修复边界
- 不允许破坏的“不卡顿”经验
- 恢复后的下一步操作

这使得后续 agent 恢复时不需要重新理解需求。

### 2. 阻塞被准确记录成“运行面问题”

多次评论没有把阻塞归咎于业务代码，而是准确指出：

- 最小命令统一失败
- 错误码稳定一致
- 当前无法读代码、改代码、跑浏览器自动化

这避免了在错误方向上浪费更多 token 和时间。

### 3. 运行面被逐步修正

后续正式服务运行面逐步补齐了这些要素：

- 固定 Git Bash / npm shim / Erlang / Elixir 路径
- 固定代理环境
- 修正服务启动脚本
- 把正式 workflow 写成显式 sandbox 配置

这些改动叠加后，issue 终于重新进入了可执行状态。

### 4. 收口证据是“交付链”而不是口头完成

最终关单不是靠一条“已修复”评论，而是靠完整交付链：

- issue 分支
- GitHub PR
- CI 成功
- 本地 `node --test`
- `npm run build`
- Playwright 回归验证

这也是为什么最终可以接受 `Done` 状态。

## 本次最有价值的成功经验

### 1. `Human Review` 之前先把设计写完整

即使实现阶段崩了，设计阶段写清楚的“根因猜测 + 修复约束 + 验收口径”依然能指导恢复。真实运行证明，这一步没有浪费。

### 2. 先跑最小探针，再决定是否继续烧 token

像 `cmd.exe /d /c echo ok` 这种最小命令探针非常有价值。它能快速判断：

- 是业务代码问题
- 还是命令执行器/运行环境问题

后续所有正式 issue 都应把这种探针前置。

### 3. 保留缩放不卡顿的经验是正确的修复约束

这条 issue 的设计总结里，关于 `KlineSlim` 成功经验的判断是对的：

- wheel 事件只收集意图，不在事件里做重计算
- 多次输入合帧到单一 `rAF`
- 尽量复用缓存，只失效受 viewport 影响的 layer
- 异步绘制必须有过期保护，避免旧帧回写

这部分最终也和交付结果一致。

### 4. Linear 评论是有效的恢复载体

真实运行证明，Linear 不只是任务源，也可以是：

- 设计包容器
- 阻塞记录容器
- 恢复指引容器

这比把上下文只留在某个临时 session 或 workspace 里可靠得多。

## 建议固化的配置优化

### 1. 正式 workflow 保持显式 sandbox

不要依赖上游默认值。正式配置应继续显式写在 `runtime/symphony/WORKFLOW.freshquant.md` 中，并同步到服务运行目录。

### 2. 服务启动前增加 preflight

正式 dispatch 前至少检查：

- `cmd /d /c echo ok`
- `bash -lc "echo ok"`
- `codex --version`
- Linear API 可达
- 代理环境变量存在

任何一项失败，都不应继续领取真实 issue。

### 3. 对运行时错误做分类

以下问题应明确归类为运行面问题，而不是业务失败：

- `:epipe`
- `-1073741502`
- `0xC0000142`
- WebSocket `10060`

只有分类清楚，UI、日志和操作人才能快速判断应修服务还是修代码。

### 4. `Done` 前增加交付证据门禁

建议自动关单前至少要求有以下任一组合：

- PR URL + CI 结果
- commit + 测试命令结果
- 明确的验证命令与输出摘要

避免未来出现“状态已 Done，但缺少交付物”的假阳性。

## 建议固化的流程优化

### 1. 用 canary issue 验证运行面

每次修改 Symphony 服务配置、启动脚本、代理或 sandbox 时，先跑 canary issue，再放真实业务票。

### 2. 连续相同阻塞不要无限重试

如果同一 issue 连续多次出现同类运行时错误，建议：

- 自动写一次阻塞评论
- 暂停继续消耗 token
- 等待服务恢复后再继续

### 3. 在 UI 中展示 `Blocked(Runtime)`

这可以作为 Symphony 的运行时状态，而不必进入 Linear 状态机。这样既能提醒操作人，又不会污染业务流程语义。

### 4. 保留恢复说明模板

本次阻塞评论之所以有效，是因为它们都包含了：

- 当前阻塞现象
- 已验证的最小探针
- 当前不能做什么
- 环境恢复后下一步做什么

建议把这种写法模板化。

## 一句话结论

`FRE-5` 多次阻塞，根因是 **Windows 正式服务模式下的 Symphony 运行面尚未完全稳定**，不是这条业务需求本身异常复杂；而它最终能成功，靠的是 **设计上下文保留完整、运行面问题被准确识别、以及最终用 PR/CI/浏览器回归形成可信交付证据**。
