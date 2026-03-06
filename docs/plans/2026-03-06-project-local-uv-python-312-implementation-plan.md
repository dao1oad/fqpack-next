# 项目内 uv 管理的 Python 3.12 统一环境与部署收敛 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将仓库运行、构建、Docker 和宿主机部署统一到项目内 `uv` 管理的 Python 3.12 环境，并让现有扩展由该环境统一驱动构建。

**Architecture:** 先收敛内部包元数据与根项目 `uv` 依赖来源，再收口宿主机 `.venv` 启动脚本和扩展构建链，随后切换 FreshQuant/TradingAgents Docker 运行面，最后更新 Supervisor 与部署文档。所有 Python 入口统一到 `.venv` 或容器内 `/app/.venv`，避免继续依赖 `Miniconda fqkit` 与未锁定的 `pip install`。

**Tech Stack:** Python 3.12、uv、setuptools、xmake、pybind11、Docker、Supervisor、pytest

---

### Task 1: 收敛内部包元数据并让 `uv` 可解析本地依赖

**Files:**
- Modify: `pyproject.toml`
- Modify: `morningglory/fqchan01/python/setup.py`
- Modify: `morningglory/fqchan04/python/setup.py`
- Modify: `morningglory/fqchan06/python/setup.py`
- Modify: `morningglory/fqcopilot/python/setup.py`
- Test: `freshquant/tests/test_project_python_policy.py`

**Step 1: 写失败测试，锁定 Python 3.12 与本地路径依赖策略**

```python
from pathlib import Path
import tomllib


def test_project_python_is_312_only():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["requires-python"] == ">=3.12,<3.13"


def test_tool_uv_sources_contains_local_packages():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    sources = data["tool"]["uv"]["sources"]
    assert "fqxtrade" in sources
    assert "fqdagster" in sources
```

**Step 2: 跑测试确认失败**

Run: `py -3 -m pytest freshquant/tests/test_project_python_policy.py -q`
Expected: FAIL，提示 `requires-python` 仍是 `>=3.12`，且 `tool.uv.sources` 缺失。

**Step 3: 修正本地包元数据与根项目依赖**

```python
setup(name="fqchan01", version="2026.3.6", ...)
setup(name="fqchan04", version="2026.3.6", ...)
setup(name="fqchan06", version="2026.3.6", ...)
setup(name="fqcopilot", version="2026.3.6", ...)
```

- 将 `pyproject.toml` 的 `requires-python` 收紧为 `>=3.12,<3.13`
- 为本仓库实际运行所需的本地包补齐 `tool.uv.sources`
- 让 `uv lock` / `uv sync` 能直接解析 `fqxtrade`、`fqdagster`、`xtquant`、`backtrader`、`quantaxis`、`fqchan*`、`fqcopilot`

**Step 4: 生成锁文件**

Run: `uv lock`
Expected: 生成 `uv.lock`

**Step 5: 回跑测试**

Run: `py -3 -m pytest freshquant/tests/test_project_python_policy.py -q`
Expected: PASS

**Step 6: Commit**

```bash
git add pyproject.toml uv.lock morningglory/fqchan01/python/setup.py morningglory/fqchan04/python/setup.py morningglory/fqchan06/python/setup.py morningglory/fqcopilot/python/setup.py freshquant/tests/test_project_python_policy.py
git commit -m "build: normalize uv sources and python312 policy"
```

### Task 2: 收口宿主机 `.venv` 初始化与安装脚本

**Files:**
- Modify: `create_venv.bat`
- Modify: `activate.bat`
- Modify: `install.bat`
- Modify: `install.py`
- Modify: `build_all.bat`
- Modify: `build_rear.bat`
- Create: `freshquant/runtime/python_env.py`
- Test: `freshquant/tests/test_python_env_runtime.py`

**Step 1: 写失败测试，锁定项目环境路径与构建环境变量**

```python
from freshquant.runtime.python_env import project_python, xmake_python_env


def test_project_python_points_to_repo_venv():
    path = project_python("D:/fqpack/freshquant-2026.2.23")
    assert str(path).endswith(".venv/Scripts/python.exe")


def test_xmake_python_env_contains_include_and_lib():
    env = xmake_python_env("D:/fqpack/freshquant-2026.2.23/.venv")
    assert "FQ_PY_BASE" in env
    assert "FQ_PY_INC" in env
```

**Step 2: 跑测试确认失败**

Run: `py -3 -m pytest freshquant/tests/test_python_env_runtime.py -q`
Expected: FAIL，模块或函数不存在。

**Step 3: 写最小实现并收口脚本职责**

```python
def project_python(repo_root: str) -> Path:
    return Path(repo_root) / ".venv" / "Scripts" / "python.exe"
```

- `create_venv.bat`：改为 `uv python install 3.12` + `uv venv --python 3.12 .venv`
- `install.bat`：改为 `uv sync` + 调用 `install.py` 执行扩展构建/系统步骤
- `install.py`：删除逐条 `uv pip install ...` 逻辑，只保留 TA-Lib、扩展构建、web 复制等编排
- `build_rear.bat` / `build_all.bat`：默认通过项目 `.venv` 触发后续动作

**Step 4: 回跑测试**

Run: `py -3 -m pytest freshquant/tests/test_python_env_runtime.py -q`
Expected: PASS

**Step 5: 手工验证宿主机 bootstrap**

Run:
- `create_venv.bat`
- `install.bat --skip-web`

Expected:
- `.venv` 创建成功
- `.\.venv\Scripts\python.exe --version` 返回 `Python 3.12.x`

**Step 6: Commit**

```bash
git add create_venv.bat activate.bat install.bat install.py build_all.bat build_rear.bat freshquant/runtime/python_env.py freshquant/tests/test_python_env_runtime.py
git commit -m "build: standardize project local venv bootstrap"
```

### Task 3: 让扩展构建链显式绑定项目内 Python 3.12

**Files:**
- Modify: `morningglory/fqcopilot/xmake.lua`
- Modify: `morningglory/fqchan01/xmake.lua`
- Modify: `morningglory/fqchan04/xmake.lua`
- Modify: `morningglory/fqchan06/xmake.lua`
- Create: `script/build_extensions.py`
- Test: `freshquant/tests/test_extension_build_env.py`
- Test: `freshquant/tests/test_fullcalc_smoke.py`

**Step 1: 写失败测试，锁定扩展构建环境必须来自 `.venv`**

```python
from freshquant.runtime.python_env import xmake_python_env


def test_xmake_env_uses_repo_python312():
    env = xmake_python_env("D:/fqpack/freshquant-2026.2.23/.venv")
    assert env["FQ_PY_BASE"].endswith(".venv")
    assert "python312" in env["FQ_PY_LIB"].lower()
```

**Step 2: 跑测试确认失败**

Run: `py -3 -m pytest freshquant/tests/test_extension_build_env.py -q`
Expected: FAIL

**Step 3: 写最小实现**

```python
subprocess.run(["xmake", "f", "-m", "release"], env=env, check=True)
subprocess.run(["xmake", "build", "fullcalc_py"], env=env, check=True)
```

- 统一由 `script/build_extensions.py` 计算并注入 `FQ_PY_BASE/FQ_PY_INC/FQ_PY_LIBDIR/FQ_PY_LIB/FQ_PYBIND_INC`
- 若 `fqchan01/04/06` 的 `xmake.lua` 不直接生成 Python 扩展，则至少保证其 Python 相关构建目标可复用同一套环境变量
- `install.py` 调用该脚本，而不是内联拼接命令

**Step 4: 回跑测试**

Run:
- `py -3 -m pytest freshquant/tests/test_extension_build_env.py freshquant/tests/test_fullcalc_smoke.py -q`

Expected: PASS

**Step 5: 手工 smoke build**

Run:
- `uv run python script/build_extensions.py --target fullcalc`
- `uv run python -c "from freshquant.analysis.fullcalc_wrapper import run_fullcalc; print('ok')"`

Expected:
- `morningglory/fqcopilot/python/fullcalc.pyd` 生成
- `run_fullcalc` 可导入

**Step 6: Commit**

```bash
git add morningglory/fqcopilot/xmake.lua morningglory/fqchan01/xmake.lua morningglory/fqchan04/xmake.lua morningglory/fqchan06/xmake.lua script/build_extensions.py freshquant/tests/test_extension_build_env.py
git commit -m "build: bind extension compilation to project python"
```

### Task 4: 切换 FreshQuant Docker 镜像与 Compose 到 uv/Python 3.12

**Files:**
- Modify: `docker/Dockerfile.rear`
- Modify: `docker/compose.parallel.yaml`
- Modify: `deploy.bat`
- Modify: `deploy_rear.bat`
- Modify: `.github/workflows/ci.yml`

**Step 1: 写失败测试或检查脚本，锁定 Docker/CI 不再使用自由 `pip install`**

```python
from pathlib import Path


def test_dockerfile_rear_uses_uv_sync():
    text = Path("docker/Dockerfile.rear").read_text(encoding="utf-8")
    assert "uv sync --frozen" in text
```

**Step 2: 跑测试确认失败**

Run: `py -3 -m pytest freshquant/tests/test_project_python_policy.py -q`
Expected: FAIL，Dockerfile 仍是 `pip install`

**Step 3: 写最小实现**

```dockerfile
RUN pip install uv
RUN uv sync --frozen
CMD ["/freshquant/.venv/bin/python", "-m", "freshquant.rear.api_server"]
```

- `docker/Dockerfile.rear` 改为复制 `pyproject.toml`、`uv.lock` 后执行 `uv sync --frozen`
- Compose 中 Python 服务命令改为使用容器内 `.venv`
- `.github/workflows/ci.yml` 改为至少在 `pre-commit`/`pytest` 作业里使用 `uv sync`，避免与本地依赖漂移

**Step 4: 回跑测试**

Run: `py -3 -m pytest freshquant/tests/test_project_python_policy.py -q`
Expected: PASS

**Step 5: 构建与启动验证**

Run:
- `docker build -t fqnext_rear:test -f docker/Dockerfile.rear .`
- `docker compose -f docker/compose.parallel.yaml up -d --build fq_apiserver fq_tdxhq`

Expected:
- 镜像构建成功
- 容器内 `python --version` 为 `3.12.x`

**Step 6: Commit**

```bash
git add docker/Dockerfile.rear docker/compose.parallel.yaml deploy.bat deploy_rear.bat .github/workflows/ci.yml
git commit -m "build: move freshquant docker runtime to uv python312"
```

### Task 5: 切换 `ta_backend` 到 Python 3.12 + uv

**Files:**
- Modify: `third_party/tradingagents-cn/Dockerfile.backend`
- Modify: `third_party/tradingagents-cn/pyproject.toml`
- Modify: `docker/compose.parallel.yaml`

**Step 1: 写失败检查，锁定 `ta_backend` 必须是 Python 3.12**

```python
from pathlib import Path


def test_ta_backend_uses_python312():
    text = Path("third_party/tradingagents-cn/Dockerfile.backend").read_text(encoding="utf-8")
    assert "python:3.12" in text
```

**Step 2: 跑测试确认失败**

Run: `py -3 -m pytest freshquant/tests/test_project_python_policy.py -q`
Expected: FAIL，当前基础镜像仍是 `python:3.10-slim-bookworm`

**Step 3: 写最小实现**

```dockerfile
FROM python:3.12-slim-bookworm
RUN pip install uv
RUN uv sync --frozen
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- `third_party/tradingagents-cn/pyproject.toml` 的 `requires-python` 收敛到 3.12 语义
- 该镜像与主项目一样改为由 `uv` 驱动安装

**Step 4: 构建验证**

Run:
- `docker build -t fqnext_ta_backend:test -f third_party/tradingagents-cn/Dockerfile.backend third_party/tradingagents-cn`
- `docker run --rm fqnext_ta_backend:test /app/.venv/bin/python --version`

Expected:
- 构建成功
- 输出 `Python 3.12.x`

**Step 5: Commit**

```bash
git add third_party/tradingagents-cn/Dockerfile.backend third_party/tradingagents-cn/pyproject.toml docker/compose.parallel.yaml
git commit -m "build: upgrade ta backend to uv python312"
```

### Task 6: 切换宿主机 Supervisor 与部署文档

**Files:**
- Modify: `README.md`
- Modify: `docs/agent/Docker并行部署指南.md`
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`
- Modify: `D:\fqpack\config\supervisord.fqnext.conf`

**Step 1: 写文档/配置变更清单**

```text
- supervisor command -> .venv\Scripts\python.exe
- README startup commands -> uv sync / uv run
- Docker guide -> uv-based build/runtime
```

**Step 2: 修改宿主机部署入口**

- 将 `supervisord.fqnext.conf` 中 `PATH` 与 `command=` 全部切到项目根目录 `.venv`
- README 增加标准安装/运行/验证命令
- Docker 并行部署文档增加容器内 `.venv` 与 `uv sync --frozen` 说明
- 同提交更新 `docs/migration/breaking-changes.md`

**Step 3: 宿主机验证**

Run:
- `supervisorctl -c D:/fqpack/config/supervisord.fqnext.conf reread`
- `supervisorctl -c D:/fqpack/config/supervisord.fqnext.conf update`
- `supervisorctl -c D:/fqpack/config/supervisord.fqnext.conf status`

Expected:
- `fqnext_realtime_xtdata_producer`
- `fqnext_realtime_xtdata_consumer`
- `fqnext_xtquant_broker`

均可由项目 `.venv` 启动

**Step 4: Commit**

```bash
git add README.md docs/agent/Docker并行部署指南.md docs/migration/progress.md docs/migration/breaking-changes.md
git commit -m "docs: switch deployment guidance to project local uv python"
```

### Task 7: 全链路回归与合并前验收

**Files:**
- Verify only: `pyproject.toml`
- Verify only: `uv.lock`
- Verify only: `docker/Dockerfile.rear`
- Verify only: `third_party/tradingagents-cn/Dockerfile.backend`
- Verify only: `D:\fqpack\config\supervisord.fqnext.conf`

**Step 1: 单元测试回归**

Run:
- `uv run pytest freshquant/tests/test_project_python_policy.py freshquant/tests/test_python_env_runtime.py freshquant/tests/test_extension_build_env.py freshquant/tests/test_fullcalc_smoke.py -q`

Expected: PASS

**Step 2: 全量测试回归**

Run: `uv run pytest freshquant/tests -q`
Expected: PASS（允许已有 skip）

**Step 3: 语法与入口 smoke**

Run:
- `uv run python -m py_compile install.py freshquant/runtime/python_env.py script/build_extensions.py`
- `uv run fqctl --help`

Expected: PASS

**Step 4: Docker smoke**

Run:
- `docker compose -f docker/compose.parallel.yaml up -d --build`
- `docker compose -f docker/compose.parallel.yaml ps`

Expected: Python 服务 healthy / started

**Step 5: Commit**

```bash
git add .
git commit -m "test: verify uv python312 deployment migration"
```
