# 正式 Deploy Mirror Worktree 设计

## 背景

`Deploy Production` 在 `PR #220` 合并后立即失败，失败点发生在 `Sync local deploy mirror`。

实测证据表明当前 workflow 把正式 mirror 固定为 `D:\fqpack\freshquant-2026.2.23`，但这个目录并不是“干净的 main mirror”：

- 当前目录实际处于 `codex/direct-codex-memory-bootstrap` 分支
- 存在未提交改动与临时文件
- 不包含正式 deploy 需要的最新脚本
- production runner 以 `NT AUTHORITY\NETWORK SERVICE` 身份运行，对该目录触发了 `git safe.directory` 拒绝

这意味着即使修掉 `safe.directory`，后续也会因为 dirty worktree 或错误分支继续失败。

## 目标

- 把正式 deploy mirror 从开发根目录切换为独立本机 worktree
- 让 production runner 可以在该独立 mirror 上稳定执行 `fetch -> fast-forward -> uv sync -> deploy`
- 不再要求开发根目录必须是干净的 `main`
- 保留“正式 deploy 只基于本机构建”的当前 CD 口径

## 非目标

- 不恢复 zipball 下载或 registry-first 正式 deploy
- 不引入第二台机器或外部产物分发
- 不修改 `docker-images.yml` 的 CI/镜像发布职责

## 方案对比

### 方案 A：继续使用仓库根目录作为 mirror

- 优点：路径不变
- 缺点：根目录已经被日常开发占用，且当前事实证明会脏、会切到 feature branch、会缺少正式脚本

结论：放弃。它与“单机开发 + 正式自动部署”并存时天然冲突。

### 方案 B：复用现有 `main-runtime` worktree

- 优点：已经是独立 worktree
- 缺点：当前该目录落后 `origin/main`，也存在未跟踪文件；而且它承担运行态观察用途，不适合作为正式 deploy 真值

结论：不采用。职责不够单一。

### 方案 C：新增独立 production mirror worktree

- 固定路径：`D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production`
- 固定本地分支：`deploy-production-main`
- 固定远端对齐目标：`origin/main`

优点：

- 与开发根目录彻底隔离
- 不受本地 feature branch、未提交改动、临时文件影响
- 可以由 workflow 自己 bootstrap 与自修复
- 与“单机本地构建”目标一致

结论：采用。

## 详细设计

## 1. 正式 mirror 路径与分支

- workflow 中新增两个正式变量：
  - `FQ_DEPLOY_CANONICAL_REPO_ROOT=D:\fqpack\freshquant-2026.2.23`
  - `FQ_DEPLOY_MIRROR_ROOT=D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production`
- mirror 不再要求 checkout 本地 `main`
- mirror 固定 checkout 本地分支 `deploy-production-main`
- 该分支只作为正式 mirror 分支，始终 fast-forward 到 `origin/main`

这样可以避免 Git worktree 的“同一分支不能在多个 worktree 同时 checkout”限制，也避免和现有 `main-runtime` 发生 branch 冲突。

## 2. Mirror bootstrap 与同步

workflow 在 `Sync local deploy mirror` 阶段改成两段：

1. bootstrap：
   - 如果 mirror 路径不存在，则从 canonical repo 执行 `git worktree add`
   - 基于 `origin/main` 创建/重置 `deploy-production-main`
2. sync：
   - 在 mirror 目录执行 `fetch origin main`
   - 校验 `origin/main == github.sha`
   - `checkout deploy-production-main`
   - `merge --ff-only refs/remotes/origin/main`

mirror 同步脚本 `script/ci/sync_local_deploy_mirror.py` 需要支持：

- 独立的 `remote_branch`
- 独立的 `checkout_branch`
- 在第一次 git 命令前设置 `safe.directory`

## 3. safe.directory

由于 production runner service 账号和仓库目录 owner 不同，workflow 必须显式信任：

- canonical repo root
- mirror root

实现口径：

- Python 脚本里加 `ensure_safe_directory(repo_root)`
- workflow bootstrap fallback 里也在 PowerShell 侧加同等处理

这样即使 mirror 由 `Administrator` 预创建，`NETWORK SERVICE` 仍可执行 git 命令。

## 4. 文档与运行真值

`docs/current/deployment.md` 与 `docs/current/runtime.md` 需要同步更新为：

- 正式 deploy mirror 不再是仓库根目录
- 正式 deploy 依赖独立 mirror worktree
- canonical repo 仅用于管理/创建 mirror，不作为正式构建工作区

## 5. 测试

需要覆盖三类回归：

- workflow 契约：
  - 固定 mirror 路径改为 `.worktrees\main-deploy-production`
  - 出现 canonical repo root
  - 出现 safe.directory 处理
  - 不再假设 mirror 本地分支名是 `main`
- mirror 同步脚本：
  - 支持 `checkout_branch != remote_branch`
  - 调用 safe.directory 配置
  - fast-forward 语义保持不变
- 文档守卫：
  - 当前部署文档改为独立 mirror worktree 口径

## 错误处理

- canonical repo 不存在：deploy 直接失败，给出固定路径提示
- mirror worktree 创建失败：deploy 直接失败，不退回开发根目录
- mirror dirty：deploy 直接失败，不自动覆盖
- `origin/main != github.sha`：deploy 直接失败，避免陈旧 push 误部署
- `uv`/Python 缺失：维持现有 fail-fast

## 验收标准

- `Deploy Production` 在 production runner 上使用 `D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production`
- runner 不再因为 `safe.directory` 拒绝访问仓库
- workflow 不再依赖开发根目录处于干净 `main`
- 本地测试、CI、文档守卫通过

