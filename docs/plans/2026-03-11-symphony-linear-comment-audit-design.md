# Symphony Linear 留痕与决策审计设计

## 背景

FreshQuant 已将正式治理切换为 `Linear-first + Symphony-first + design-approval-first`。现有规则已经要求：

- `Human Review -> In Progress` 是唯一人工门
- `Merging -> Done` 必须包含部署成功
- 关键阶段需要在 Linear 留评论

但当前规则仍有三个空洞：

1. `Human Review` 评论没有强制一次性列出全部待决策项、推荐方案和理由。
2. PR 完成后的关键交付信息没有强制沉淀到 Linear。
3. 部署完成后的动作、结果和健康检查没有被定义为 `Done` 前的显式 Linear 留痕。

这导致 Linear 虽然是唯一任务入口，但还不是完整的审计面。

## 目标

- 将 `Human Review` 明确为“清空待决策项”的唯一阶段。
- 要求 PR 阶段的交付结果完整写回 Linear。
- 要求部署阶段的动作与结果完整写回 Linear。
- 将上述要求同时固化到：
  - 仓库治理文档
  - Symphony 评论模板
  - Symphony workflow prompt

## 非目标

- 本次不修改 Elixir orchestrator 代码来强制检查 Linear 评论内容。
- 本次不新增新的 Linear 状态。
- 本次不引入第二个人工门。

## 设计

### 1. Human Review 决策审计

进入 `Human Review` 前，结构化 Linear 评论必须包含：

- `Decision items`
- 每个决策项的：
  - 决策问题
  - 推荐方案
  - 推荐理由
  - 需要人类给出的最终结论

如果没有待决策项，必须明确写：

- `No open decision items`

治理语义调整为：

- `Human Review` 的职责不仅是“审设计”，也是“消化并关闭所有待决策项”
- 只要仍有待决策项未明确，不允许进入 `In Progress`

### 2. PR 结果审计

在 `In Progress` 或 `Rework` 推进到 `Merging` 前，必须在 Linear 留一条结构化 PR 结果评论，至少包含：

- 解决的问题
- 采用的解决方案
- 选择该方案的理由
- 修改的文件
- 测试与验证结果
- 经验积累 / 后续注意事项
- PR 链接

这条评论是“代码交付审计包”，不替代 PR 本身，但作为 Linear 的正式归档。

### 3. 部署结果审计

在 `Merging -> Done` 前，必须在 Linear 留一条结构化部署评论，至少包含：

- 部署范围
- 执行的部署动作
- 健康检查结果
- 重试 / 失败记录
- 最终部署结果

治理语义调整为：

- `Done` 不仅要求 merge + deploy 成功
- 还要求部署留痕已完整写回 Linear

## 文件改动范围

- 治理文档：
  - `AGENTS.md`
  - `docs/rfcs/0028-symphony-first-governance.md`
  - `docs/agent/Symphony正式接入治理说明.md`
- 运行模板：
  - `runtime/symphony/templates/human_review_comment.md`
  - `runtime/symphony/templates/pr_completion_comment.md`
  - `runtime/symphony/templates/deployment_comment.md`
- workflow prompt：
  - `runtime/symphony/prompts/todo.md`
  - `runtime/symphony/prompts/in_progress.md`
  - `runtime/symphony/prompts/merging.md`
  - `runtime/symphony/README.md`
  - `runtime/symphony/scripts/sync_freshquant_symphony_service.ps1`
- 进度记录：
  - `docs/migration/progress.md`

## 验收标准

- 治理文档明确写出三类 Linear 留痕要求。
- `Human Review` 被明确定义为待决策项关闭前不得进入实现阶段。
- `runtime/symphony` 下存在 PR 结果评论模板和部署评论模板。
- `todo.md`、`in_progress.md`、`merging.md` 明确写出对应门禁。
- 同步脚本会把新增模板复制到宿主机服务目录。
