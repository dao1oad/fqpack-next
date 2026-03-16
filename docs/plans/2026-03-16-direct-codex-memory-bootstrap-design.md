# 直开 Codex 会话记忆自举设计

## 背景

当前 FreshQuant 的记忆系统会在 `Symphony` / `Global Stewardship` 启动 `codex` 前，通过 `runtime/symphony/scripts/run_freshquant_codex_session.ps1` 先执行 memory refresh / compile，再把 `FQ_MEMORY_CONTEXT_PATH` 和 `FQ_MEMORY_CONTEXT_ROLE` 注入进程。

但直接在 Codex app 中打开仓库启动的自由会话，不会自动经过这条 wrapper，因此默认不会拿到已编译的 context pack，也不会自动执行 memory refresh / compile。

## 目标

- 让直接进入仓库的 Codex 会话，在未注入 `FQ_MEMORY_CONTEXT_PATH` 时也能按仓库规则自举记忆系统。
- 保持 `Symphony` / `Global Stewardship` 现有启动链路不变。
- 不引入新的正式真值源，memory 仍然只是派生上下文。

## 非目标

- 不修改 Codex app 本体或全局宿主机启动逻辑。
- 不改变 `Symphony` wrapper 的行为。
- 不把自由会话改造成必须依赖 Issue 状态机。

## 方案对比

### 方案 A：只保留手动启动脚本

新增一个手动脚本，要求用户以后通过脚本启动 Codex。

优点：
- 实现简单。

缺点：
- 不能覆盖“直接在 Codex app 中打开仓库”的场景。
- 依赖人工记忆，容易失效。

### 方案 B：仓库内 bootstrap 入口 + AGENTS 自举规则（推荐）

新增一个正式 bootstrap 脚本，在没有 `FQ_MEMORY_CONTEXT_PATH` 时执行 memory refresh / compile，返回 `context_pack_path`、`role` 和派生的 `issue_identifier`。同时在 `AGENTS.md` 中明确要求直开会话先执行该脚本并读取产物。

优点：
- 完全在仓库内落地。
- 能覆盖自由 Codex 会话。
- 不影响 `Symphony` 现有 wrapper。

缺点：
- 这是“会话首轮自举”，不是 app 级真正 pre-launch hook。

### 方案 C：修改全局 Codex 配置

从仓库外修改 Codex app 或宿主机全局配置，让所有会话都自动注入 memory。

优点：
- 自动化程度最高。

缺点：
- 超出当前仓库治理边界。
- 可移植性和可审计性差。

## 推荐方案

采用方案 B。

## 设计细节

### 1. 新增 bootstrap helper / script

新增一个仓库内正式入口，用于：

- 读取 `repo_root` / `service_root`
- 自动解析当前分支和 git status
- 推导当前会话使用的 `issue_identifier`
- 在 Mongo `fq_memory` 中执行 refresh
- 编译 `codex` 或 `global-stewardship` 的 context pack
- 输出 JSON，包含：
  - `issue_identifier`
  - `role`
  - `context_pack_path`
  - `refresh_summary`

### 2. issue_identifier 推导规则

优先级：

1. 显式传入的 `--issue-identifier`
2. 当前 workspace 目录名若匹配 `GH-166` 这类 issue id，则直接使用
3. 当前 git branch 中若能解析出 `GH-166` 这类 issue id，则使用该值
4. 否则回退为 `LOCAL-<workspace-name>` 的确定性本地标识

这样可同时覆盖：

- `Symphony` workspaces
- issue branch 的自由会话
- 直接在主工作树打开的本地会话

### 3. AGENTS 自举规则

在 `AGENTS.md` 中新增自由会话规则：

- 若 `FQ_MEMORY_CONTEXT_PATH` 未设置，或目标文件不存在
- 在做通用 repo 扫描前，先运行 bootstrap 脚本
- 读取返回的 context pack
- 若与 GitHub / `docs/current/**` / deploy evidence 冲突，正式真值优先

### 4. 文档同步

更新 `docs/current/runtime.md`、`docs/current/interfaces.md`、`docs/current/troubleshooting.md`：

- 说明直开 Codex 会话通过 bootstrap 脚本接入记忆系统
- 记录新脚本入口
- 记录排障方式

## 验证策略

- 单元测试：
  - issue id 推导规则
  - bootstrap helper 调用 refresh + compile 并产出 pack
- 文档/契约测试：
  - `AGENTS.md` 包含 bootstrap 规则
  - `docs/current/**` 反映新的直开会话入口
- smoke：
  - 在临时 `service_root` 下运行 bootstrap 脚本
  - 确认输出的 `context_pack_path` 存在且可读
