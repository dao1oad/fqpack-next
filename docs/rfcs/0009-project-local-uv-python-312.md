# RFC 0009: 项目内 uv 管理的 Python 3.12 统一运行环境与构建/部署收敛

- **状态**：Approved
- **负责人**：Codex
- **评审人**：TBD
- **创建日期**：2026-03-06
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

当前仓库已经在 `pyproject.toml` 中声明 `requires-python = ">=3.12"`，但实际运行环境并不统一：

- 宿主机部署仍依赖 `D:/fqpack/miniconda3/envs/fqkit`，`D:\fqpack\config\supervisord.fqnext.conf` 中所有 `fqnext` 进程都直接指向该解释器。
- 仓库已部分引入 `uv`，但 `install.py` 仍通过多次 `uv pip install` 充当依赖管理器，未形成锁文件驱动的标准安装流程。
- `docker/Dockerfile.rear` 仍采用 `python:3.12-bookworm + pip install ...`，与宿主机环境并不一致。
- `third_party/tradingagents-cn/Dockerfile.backend` 仍使用 `python:3.10-slim-bookworm` 和 `pip install`，与主项目的 Python 3.12 基线冲突。
- `fullcalc`、`fqchan01/04/06` 等扩展虽然目标是 Python 3.12，但构建链没有被“项目内解释器”严格约束，容易发生 include/lib/site-packages 绑定漂移。

结果是：同一仓库存在 `conda env`、项目 `.venv`、Docker `pip` 三套运行面，依赖与解释器来源不可控，排障和部署成本都偏高。

## 2. 目标（Goals）

- 将本仓库统一到 **项目内 `uv` 管理的 Python 3.12.x 环境**。
- 宿主机唯一运行环境固定为仓库根目录 `.venv/`。
- Docker 容器统一使用同一套 `uv` 配置与 `uv.lock`，在容器内创建 `/app/.venv`。
- 宿主机与 Docker 的依赖安装统一改为 `uv sync` / `uv sync --frozen`。
- `fullcalc`、`fqchan01/04/06` 等现有扩展在项目内 Python 3.12 环境下重建，并由该环境统一驱动构建。
- 将 `Supervisor`、安装脚本、构建脚本、部署文档、Dockerfile/Compose 的默认 Python 入口全部切到项目内环境。
- `docker/compose.parallel.yaml` 下所有 Python 服务镜像统一到 Python 3.12；其中包括 `fqnext_rear` 系列服务以及 `ta_backend`。

## 3. 非目标（Non-Goals）

- 不将现有 C/C++ 扩展改写为纯 Python 实现。
- 不改变 XTQuant / MiniQMT 必须运行在 Windows 宿主机的事实约束。
- 不在本 RFC 中重做前端 Node/Nginx 构建链。
- 不对 `third_party/tradingagents-cn/` 的全部历史脚本、文档、便携版发布链做全量迁移；仅收敛当前仓库实际部署/运行所需入口。

## 4. 范围（Scope）

**In Scope**

- `pyproject.toml`、`uv.lock` 与项目 `.venv` 约定。
- 宿主机安装/激活/构建脚本：
  - `create_venv.bat`
  - `activate.bat`
  - `install.bat`
  - `install.py`
  - `build_rear.bat`
  - `build_all.bat`
- 扩展构建链：
  - `morningglory/fqcopilot/xmake.lua`
  - `morningglory/fqchan01/xmake.lua`
  - `morningglory/fqchan04/xmake.lua`
  - `morningglory/fqchan06/xmake.lua`
  - 相关 Python wrapper / build glue
- 宿主机 Supervisor 运行方式：
  - `D:\fqpack\config\supervisord.fqnext.conf`
- FreshQuant Docker 运行方式：
  - `docker/Dockerfile.rear`
  - `docker/compose.parallel.yaml`
  - `deploy.bat` / `deploy_rear.bat`
- `docker/compose.parallel.yaml` 中由本仓库托管的 Python 容器，包括：
  - `fq_apiserver`
  - `fq_tdxhq`
  - `fq_dagster_webserver`
  - `fq_dagster_daemon`
  - `fq_qawebserver`
  - `ta_backend`
- 相关部署/安装文档更新。

**Out of Scope**

- `docker/Dockerfile.web`、纯前端镜像与 Node 版本治理。
- `third_party/tradingagents-cn/` 的 Streamlit/便携版/嵌入式 Python 等非当前部署主链。
- 与 Python 版本无关的业务功能重构。

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- 以 `uv` 作为本仓库唯一的 Python 环境管理器。
- 以根目录 `.venv/` 作为宿主机唯一运行环境。
- 以 `uv.lock` 作为宿主机与 Docker 的统一依赖锁定结果。
- 将所有一线运行命令统一到：
  - `uv sync`
  - `uv run ...`
  - `.\.venv\Scripts\python.exe ...`
  - 容器内 `/app/.venv/bin/python ...`
- 让扩展构建链显式绑定项目内 Python 3.12，而不是隐式依赖系统/conda Python。
- 将 `ta_backend` 从 Python 3.10 迁移到 Python 3.12，并纳入同一套 `uv` 安装约定。

**不负责（Must Not）**

- 不保证旧的 `Miniconda fqkit` 运行方式继续作为正式支持路径。
- 不继续支持 Dockerfile 中自由追加未锁定的 `pip install` 作为常态。
- 不在本 RFC 中兼容“任意系统 Python 直接运行项目脚本”的用法。

**依赖（Depends On）**

- `uv`
- Python 3.12.x 发行版
- `xmake`
- `pybind11`
- TA-Lib 系统库/安装包
- 现有 `pyproject.toml` 依赖定义
- Docker / Docker Compose

**禁止依赖（Must Not Depend On）**

- `D:/fqpack/miniconda3/envs/fqkit`
- 未受锁文件约束的 `pip install`
- 未声明的系统级 Python 解释器路径

## 6. 对外接口（Public API）

本 RFC 涉及的“对外接口”主要是运行入口与部署入口，而非业务 HTTP API。

### 6.1 宿主机标准入口

- 初始化 Python 版本：
  - `uv python install 3.12`
- 创建/同步项目环境：
  - `uv sync`
- 运行项目命令：
  - `uv run fqctl ...`
  - `uv run pytest ...`
  - `.\.venv\Scripts\python.exe -m <module>`

### 6.2 脚本入口约定

- `create_venv.bat`
  - 负责创建 `.venv`
  - 失败时必须明确提示 `uv` 或 Python 3.12 缺失
- `install.bat`
  - 负责标准化执行 `uv python install 3.12`、`uv sync`、扩展构建与必要系统步骤
  - 不再逐条充当依赖安装器
- `install.py`
  - 只保留系统安装/构建编排能力
  - 不再作为“未锁定 Python 依赖”的安装入口
- `activate.bat`
  - 仅激活根目录 `.venv`

### 6.3 Docker 入口约定

- FreshQuant Python 镜像与 `ta_backend` 镜像统一以 Python 3.12 为基线。
- 镜像构建统一以 `uv sync --frozen` 为主路径。
- `docker compose -f docker/compose.parallel.yaml up -d --build` 保持为外部可见的标准启动方式。

### 6.4 错误语义

- 缺少 `uv`：安装脚本与文档必须 fail-fast，返回非零退出码。
- 缺少 Python 3.12：安装脚本必须明确提示并引导执行 `uv python install 3.12`。
- `uv.lock` 与 `pyproject.toml` 不一致：构建/CI 必须失败，不允许静默漂移。
- 扩展未按项目 Python 3.12 构建成功：相关运行入口必须在导入阶段明确报错，而不是回退到系统 Python。

## 7. 数据与配置（Data / Config）

### 7.1 环境目录约定

- 宿主机项目环境：`D:\fqpack\freshquant-2026.2.23\.venv`
- Docker 容器环境：`/app/.venv`
- 依赖锁文件：`uv.lock`

### 7.2 配置与路径收敛

- `pyproject.toml`
  - 继续作为依赖事实源
  - Python 基线固定为 3.12.x 语义
- `D:\fqpack\config\supervisord.fqnext.conf`
  - 所有 `fqnext` Python 进程改为指向项目内 `.venv`
- `docker/Dockerfile.rear`
  - 从 `pip install` 链切换为 `uv` 驱动安装
- `third_party/tradingagents-cn/Dockerfile.backend`
  - 从 `python:3.10-slim-bookworm + pip install` 切换到 Python 3.12 + `uv` 驱动安装

### 7.3 扩展构建配置

- `fullcalc`、`fqchan01/04/06` 的构建脚本必须显式接收或推导项目内 Python 解释器路径。
- 构建链必须确保：
  - Python include 路径来自项目 3.12
  - Python lib 路径来自项目 3.12
  - `pybind11` 与构建期依赖来自项目 `.venv`

## 8. 破坏性变更（Breaking Changes）

- 宿主机正式运行面从 `Miniconda fqkit` 切换为项目根目录 `.venv`。
- Docker Python 镜像从自由 `pip install` 切换为 `uv sync --frozen`。
- `ta_backend` 运行时从 Python 3.10 升级到 Python 3.12。
- 扩展构建链不再允许隐式绑定外部 Python。

### 影响面

- 宿主机 Supervisor 托管的所有 `fqnext` Python 进程
- 本仓库所有基于 `docker/Dockerfile.rear` 的 Python 容器
- `docker/compose.parallel.yaml` 中的 `ta_backend`
- 开发者日常命令与安装方式

### 迁移步骤

1. 落地 `uv.lock` 与标准 `.venv` 约定。
2. 收口安装脚本与扩展构建脚本。
3. 切换宿主机 Supervisor 到项目内 `.venv`。
4. 切换 FreshQuant Dockerfile 与 `ta_backend` Dockerfile 到 Python 3.12 + `uv`。
5. 更新 README、部署文档、排障文档。

### 回滚方案

- 宿主机：
  - 恢复 `D:\fqpack\config\supervisord.fqnext.conf` 到原 `fqkit` Python 路径
- Docker：
  - 恢复 `docker/Dockerfile.rear` 到原 `pip install` 方案
  - 恢复 `third_party/tradingagents-cn/Dockerfile.backend` 到原 Python 3.10 方案
- 安装链：
  - 恢复旧 `install.py` / `install.bat` 行为

> 具体破坏性变更在实现落地时，必须同步登记到 `docs/migration/breaking-changes.md`。

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- 旧宿主机运行模型：
  - `D:\fqpack\freshquant` + `Miniconda env`
  - 映射到本仓库：`D:\fqpack\freshquant-2026.2.23\.venv` + `uv`
- 旧的外部解释器路径约定：
  - `D:/fqpack/miniconda3/envs/fqkit/python`
  - 映射到本仓库：`.\.venv\Scripts\python.exe`
- 旧的扩展构建隐式 Python 绑定：
  - 映射到本仓库：显式绑定项目内 Python 3.12 构建
- 旧的 Docker `pip install` 链：
  - 映射到本仓库：`uv sync --frozen`

## 10. 测试与验收（Acceptance Criteria）

- [ ] 宿主机根目录可成功创建 `.venv`，且 `.\.venv\Scripts\python.exe --version` 返回 `Python 3.12.x`
- [ ] `uv sync` 可在宿主机完整安装本仓库依赖
- [ ] `uv sync --frozen` 可在 Docker 镜像构建中成功执行
- [ ] `fullcalc`、`fqchan01/04/06` 可在项目内 Python 3.12 下成功构建并导入
- [ ] `D:\fqpack\config\supervisord.fqnext.conf` 中的 `fqnext` Python 进程全部改用项目内 `.venv`
- [ ] `fq_apiserver`、`fq_tdxhq`、`fq_dagster_webserver`、`fq_dagster_daemon`、`fq_qawebserver` 容器内 Python 版本均为 `3.12.x`
- [ ] `ta_backend` 容器内 Python 版本为 `3.12.x`
- [ ] 日常命令口径统一为 `uv run ...` 或项目内 `.venv` Python
- [ ] README、部署文档、Docker 并行部署文档、安装说明全部完成更新

## 11. 风险与回滚（Risks / Rollback）

- 风险：`xmake` / `pybind11` / Python include/lib 路径不一致，导致扩展编译失败
  - 缓解：构建脚本显式传入项目 Python 3.12 路径，并增加 smoke import 验证
- 风险：`uv.lock` 首次收敛后与现有运行面存在版本差异，触发运行期兼容问题
  - 缓解：宿主机与 Docker 分别做最小启动验收，先验证核心服务
- 风险：`ta_backend` 从 Python 3.10 升级到 3.12 后出现第三方兼容性问题
  - 缓解：将 `ta_backend` 作为单独验收项，必要时分阶段切换
- 风险：Supervisor 切换时 `.venv` 未准备好导致服务无法启动
  - 缓解：切换前强制执行 `.venv` 健康检查与关键模块导入检查

## 12. 里程碑与拆分（Milestones）

- M1：RFC 0009 评审通过
- M2：`uv.lock`、`.venv` 与安装脚本收敛
- M3：扩展构建链改为项目内 Python 3.12
- M4：宿主机 Supervisor 切换完成
- M5：FreshQuant Docker + `ta_backend` Docker 切换完成
- M6：文档更新与验收完成
