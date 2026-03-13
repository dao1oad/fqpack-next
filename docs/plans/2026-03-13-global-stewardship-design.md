# Global Stewardship Design

## 背景

当前 `Symphony` 正式工作流把 `merge + deploy + health check + cleanup` 串在单个 issue 的 `Merging` 阶段内完成。这样在单任务视角下比较直接，但 merge 之后的运行交付、cleanup 收口和跨 PR 依赖判断都被塞进单个任务会话，导致以下问题：

- 多个已 merge PR 无法按当前 `main` 统一评估部署批次。
- cleanup 容易被单个会话生命周期、宿主机临时故障或长尾重试拖住。
- merge 后发现的新问题只能在原 issue 内部打转，不利于形成清晰的 follow-up 修复链路。
- `Symphony` 同时承担“单任务开发执行器”和“全局系统收口器”两种职责，边界不清。

本设计把 merge 后职责从单任务 `Symphony` 中拆出，交给单个 Codex app 全局自动化统一巡检与治理。

## 目标

- 保留现有 GitHub-first 与 `Design Review` 唯一人工门。
- 让 `Symphony` 只负责单个 issue 的开发闭环，直到 PR merge 到 remote `main`。
- 引入单个全局 Codex 自动化，统一处理 merge 后的 deploy、health check、cleanup 和异常分派。
- 当全局自动化发现需要代码修复的问题时，只创建 follow-up issue，由下一轮 `Symphony` 接手，不直接写代码或建 PR。

## 非目标

- 不把 merge 视为 `Done`。
- 不绕过 `Design Review` 规则。
- 不让全局自动化直接修改仓库代码。
- 不把 `Blocked` 扩展成通用“等待状态”。

## 已确认评审结论

### 1. 正式引入 `Global Stewardship`

确认。merge 后的原 issue 进入 `Global Stewardship`，由单个全局 Codex 自动化接管运行交付与收口。

### 2. 原 issue 在 follow-up 修复期间保持 open

确认。原 issue 只有在 `deploy + health check + cleanup` 全部完成后才允许 `Done`。如果 merge 后发现新问题，需要 follow-up 修复，则原 issue 保持 open，继续停留在 `Global Stewardship`。

### 3. follow-up 只开 issue，不直接开 PR

确认。全局自动化发现需要代码修复的问题时，只创建新的 GitHub issue，默认标签仍为 `symphony + todo`，交给下一轮 `Symphony` 处理。

### 4. 全局 Codex 自动化允许批量 deploy 多个 merged PR

确认。全局自动化按当前 `main` 和受影响部署面统一判断是否合并多个已 merge issue 一起部署，不按单个 PR 机械逐一部署。

## 治理规则变更

### 正式工作流

高风险任务：

`Issue -> Draft PR -> Design Review -> In Progress -> Merging -> Global Stewardship -> Done`

低风险任务：

`Issue -> In Progress -> Merging -> Global Stewardship -> Done`

### 唯一人工门

不变：

- 唯一人工评审点仍然是 `Design Review`
- 唯一人工评审面仍然是 GitHub Draft PR
- merge 后的 deploy、cleanup、follow-up issue 判定都不新增人工门

### 真值分层

- GitHub Issue：任务入口真值
- GitHub Draft PR：Design Review 真值
- GitHub PR merged to remote `main`：代码交付真值
- 全局 Codex 自动化完成的 `deploy + health check + cleanup`：运行交付真值

## 新状态契约

### `Todo`

只负责上下文梳理、风险判定、是否需要 `Design Review`。

### `Design Review`

只负责 Draft PR 评审与 `APPROVED`。

### `In Progress`

只负责实现、测试、文档同步、CI 修复。

### `Merging`

职责收缩为：

- 确认 PR 可以合并
- merge 到 remote `main`
- 写 merge 交接评论
- 将 issue 转入 `Global Stewardship`

`Merging` 不再负责 deploy、health check 或 cleanup。

### `Global Stewardship`

只由单个全局 Codex 自动化负责：

- 巡检所有已 merge 未 Done 的 issue
- 基于当前 `main` 统一判断批量 deploy
- 运行 health check
- 执行 cleanup
- 发现需要代码修复的问题时创建 follow-up issue
- 当运行交付完成后关闭原 issue

### `Rework`

仅用于原 issue 在 merge 前需要继续修改时使用。已 merge 的原 issue 不再回退到 `Rework`。

### `Blocked`

仍只用于真实外部阻塞，例如：

- GitHub / token / 权限异常
- 宿主机资源故障
- 券商终端或 XTData 外部依赖不可用

## 角色边界

### `Symphony`

`Symphony` 是单任务开发执行器，只负责：

- issue 领取与 branch / Draft PR 准备
- 设计评审流程
- 编码、测试、CI
- merge 到 remote `main`
- merge 后交接给 `Global Stewardship`

### 全局 Codex 自动化

全局 Codex 自动化是跨任务治理者，只负责：

- 周期性巡检 `Global Stewardship` issue
- 分析多个已 merge issue 之间的部署关系
- 决定本轮是否 deploy、延后或拆批
- 执行 deploy、health check、cleanup
- 创建 follow-up issue
- 更新原 issue 评论与最终关闭 issue

明确禁止：

- 不直接修改仓库代码
- 不直接创建修复 PR
- 不绕过 `Design Review`

## merge 后交接契约

`Symphony` 在 merge 完成后，必须在原 issue 写一条标准化交接评论，至少包含：

- `Source PR`
- `Merge Commit`
- `Merged At`
- `Changed Paths Summary`
- `Recommended Deployment Surfaces`
- `Current State: Global Stewardship`
- `Done` 仍需满足 `deploy + health check + cleanup`

这条评论是全局自动化后续巡检的最小上下文之一。

## 全局巡检闭环

单个全局 Codex 自动化按固定周期执行，每轮做以下动作：

1. 枚举所有处于 `Global Stewardship` 的 open issue
2. 读取其关联 merged PR、merge commit、上轮评论和是否已有 open follow-up issue
3. 读取当前 `origin/main` HEAD 与运行面健康状态
4. 判断本轮是否要批量 deploy、拆批 deploy 或延后到下一轮
5. 对本轮成功覆盖的 issue 执行 cleanup
6. 对需要代码修复的问题创建 follow-up issue
7. 更新原 issue 评论；满足条件则关闭原 issue

## 批量 deploy 规则

### 基本原则

- deploy 面向当前 `main`，不是面向单个 feature branch
- 以部署面并集为基本单位，而不是以 PR 为基本单位
- 可以批量收口多个已 merge issue

### 推荐初始策略

先用保守规则：

- 将所有候选 issue 的 changed paths 映射为部署面并集
- 优先把纯 API / Web / 文档同步类改动合并为一批
- 对高风险运行面单独拆批，例如 `runtime/symphony/**`、`freshquant/market_data/**`、交易 worker 链路

### issue 何时算被一次 deploy 覆盖

只有同时满足以下条件时，原 issue 才算被本轮 deploy 覆盖：

- 其 merge commit 已包含在本轮 deploy 使用的 `main` HEAD 中
- 相关运行面 health check 通过
- 没有仍阻塞 `Done` 的 open follow-up issue

## 发现问题后的处理规则

### 仅收口问题

例如 deploy 漏跑、cleanup 漏跑、健康检查未触发。

处理方式：

- 不开新 issue
- 由全局自动化直接在本轮或后续轮次补做收口

### 需要代码修复

例如部署脚本缺陷、运行时回归、健康检查逻辑错误。

处理方式：

- 创建新的 follow-up GitHub issue
- 原 issue 保持 `Global Stewardship`
- 在原 issue 评论中记录“等待 GH-xxx 修复后继续收口”

### 真实外部阻塞

处理方式：

- 可将原 issue 或相关 follow-up issue 标记为 `Blocked`
- 必须记录 blocker、clear condition、evidence 和 target recovery state

## follow-up issue 契约

全局自动化创建 follow-up issue 时，正文必须包含以下字段：

- `Source Issue: GH-xxx`
- `Source PR: #xxx`
- `Source Commit: <sha>`
- `Blocks Done Of: GH-xxx`
- `Symptom Class: cleanup-failure | deploy-regression | health-check-regression | runtime-bug | governance-gap`
- `是否疑似命中 Design Review 条件`
- 证据摘要
- 影响面
- 下一轮 `Symphony` 接手建议

默认标签：

- `symphony`
- `todo`

不预贴 `design-review`。只有下一轮 `Symphony` 在 `Todo` 首轮确认命中高风险条件后，才补贴 `design-review`。

## 去重规则

全局自动化创建 follow-up issue 前必须先查重。

如果已经存在同源 issue、同类症状、且仍 open 的 follow-up issue：

- 不重复创建
- 只在原 issue 中补充一条进展评论

## 评论契约

### 原 issue 评论

允许三类：

- merge 交接评论
- 巡检进展评论
- 最终 done 评论

### 巡检进展评论必须回答

- 本轮是否纳入部署批次
- 如果没有，为什么延后
- 是否已创建或复用 follow-up issue
- 下一步由谁处理

## `Done` 判定

`Done` 定义不变：

`Done = merge + ci + docs sync + deploy + health check + cleanup`

变化点只在于：

- merge 前半段由 `Symphony` 负责
- merge 后半段由全局 Codex 自动化负责

## 风险与缓解

### 风险 1：原 issue 长时间停在 `Global Stewardship`

缓解：

- 自动化每轮必须更新评论或明确“本轮无动作”的原因
- follow-up issue 采用去重规则，避免原 issue 被多个重复修复任务拖住

### 风险 2：批量 deploy 把问题范围放大

缓解：

- 初期采用保守拆批
- 高风险路径单独部署
- 逐步积累哪些部署面可以安全合批

### 风险 3：全局自动化重复开 issue

缓解：

- 引入固定字段和查重规则
- 用 `Source Issue + Symptom Class` 作为最小去重键

## 实施建议

建议分三步落地：

1. 先改治理文档、workflow contract、prompt contract，把 `Global Stewardship` 语义固定下来
2. 再引入单个 Codex app 自动化巡检器，只做评论、分派和批量 deploy / cleanup
3. 最后补 follow-up issue 模板、查重规则和运行手册

## 当前结论

无待评审点，按推荐方案执行。
