# 仓库换行规则与混合行尾防回归设计

## 背景

当前仓库在 Windows 环境下使用 `core.autocrlf=true` 时，部分文本文件会出现 mixed line endings 带来的“假脏工作树”现象。正式部署目录 `D:/fqpack/freshquant-2026.2.23` 必须长期保持干净 `main`，因此需要把换行规则固化到仓库，并在 CI / 本地提交阶段阻止新的 mixed line endings 进入仓库。

## 目标

- 让仓库内需要稳定为 Unix 风格的文本文件显式声明为 `LF`
- 让 Windows 启动脚本显式声明为 `CRLF`
- 在 `pre-commit` / CI 中自动拦截新的 mixed line endings
- 降低 Windows 下因换行不一致导致的假脏工作树概率

## 方案选型

### 方案 A：只修当前问题文件

- 仅规范当前发现的问题文件
- 不增加自动检查

缺点：

- 只能处理当前症状
- 后续仍可能再次回归

### 方案 B：只加自动检查

- 增加 `pre-commit` mixed-line-ending hook
- 不补充 `.gitattributes`

缺点：

- 仓库缺少明确换行真值
- 仍依赖各人本机 Git / 编辑器行为

### 方案 C：仓库规则 + 自动检查

推荐方案：

- 在 `.gitattributes` 中显式声明主流文本类型的行尾规则
- 在 `.pre-commit-config.yaml` 增加 `mixed-line-ending` hook
- 在 `docs/current/**` 记录当前仓库事实
- 用一个小型 pytest 回归测试验证策略存在

推荐理由：

- 规则随仓库走，不依赖个人环境
- CI 已运行 `pre-commit`，可以直接作为统一门禁
- 改动面小，不需要大规模内容重写

## 设计

### 1. `.gitattributes` 作为换行真值

新增明确规则：

- `*.py`, `*.js`, `*.html`, `*.md`, `*.yml`, `*.yaml`, `*.ps1`, `*.sh`, `Dockerfile*` 使用 `LF`
- `*.bat`, `*.cmd` 使用 `CRLF`

### 2. `pre-commit` 增加 mixed-line-ending 检查

新增 `pre-commit-hooks` 的 `mixed-line-ending` hook，使用 `--fix=no`。

原因：

- 当前 Windows 环境使用 `core.autocrlf=true`
- 这里应该只做阻止回归，不在提交阶段隐式重写文件

### 3. 文档同步

在 `docs/current/configuration.md` 中补充当前事实：

- `.gitattributes` 约束文本文件换行
- `pre-commit` / CI 会阻止 mixed line endings 进入仓库

### 4. 回归测试

新增一个 pytest：

- 断言 `.gitattributes` 包含关键行尾规则
- 断言 `.pre-commit-config.yaml` 已声明 `mixed-line-ending` 且参数为 `--fix=no`

## 影响面

- `.gitattributes`
- `.pre-commit-config.yaml`
- `docs/current/configuration.md`
- `freshquant/tests/test_line_ending_policy.py`

## 风险

- 行尾规则新增后，未来首次触碰不合规文件时可能出现一次性换行 diff
- 若把 Windows 启动脚本错误设为 `LF`，会影响部分本机使用体验

缓解：

- 仅把 `*.bat` / `*.cmd` 显式固定为 `CRLF`
- 本轮不做全仓批量规范化

## 验证

- `pytest -q freshquant/tests/test_line_ending_policy.py`
- `python -m pre_commit run mixed-line-ending --files ...`
- `python -m pre_commit run end-of-file-fixer --files ...`
- `python -m pre_commit run trailing-whitespace --files ...`
