# 项目内 uv 管理的 Python 3.12 统一环境设计

## 目标

- 本仓库统一使用项目内 `uv` 管理的 Python 3.12.x。
- 宿主机唯一运行环境固定为根目录 `.venv/`。
- Docker 容器以同一份 `uv.lock` 驱动，在容器内创建各自 `/app/.venv`。
- `fullcalc`、`fqchan01/04/06` 等扩展统一由项目内 Python 3.12 驱动构建。

## 关键约定

- 宿主机：
  - `uv python install 3.12`
  - `uv sync`
  - `uv run ...`
  - `.\.venv\Scripts\python.exe ...`
- Docker：
  - Python 基线统一到 `3.12.x`
  - 统一使用 `uv sync --frozen`
- Supervisor：
  - 统一从 `D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe` 启动

## 关键影响面

- `install.bat`、`create_venv.bat`、`install.py`
- `build_rear.bat`、扩展构建链
- `docker/Dockerfile.rear`
- `docker/compose.parallel.yaml`
- `third_party/tradingagents-cn/Dockerfile.backend`
- `D:\fqpack\config\supervisord.fqnext.conf`

## 设计结论

- 采用“同一套 `uv` 配置与锁文件，宿主机/容器分别创建各自 `.venv`”的模型。
- 不再将 `Miniconda fqkit` 作为正式运行面。
- 不改写 C/C++ 扩展为纯 Python，只要求在项目内 Python 3.12 下重建。
- `TradingAgents-CN` 的当前 Docker 后端运行面也纳入本次 Python 3.12 收敛，但不在本次迁移中清理其全部历史安装文档和便携版脚本。

## 关联 RFC

- `docs/rfcs/0009-project-local-uv-python-312.md`
