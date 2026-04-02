# Host Supervisor Deploy Mirror Design

## 背景

- 2026-04-02 的融资买入链路故障已确认不是 `order_submit` 或 Guardian 信号逻辑错误，而是宿主机 `fqnext-supervisord` 实际运行的 `fqxtrade` 代码来源错误。
- formal deploy 真值已经切到 `D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production`，但线上 `D:\fqpack\config\supervisord.fqnext.conf` 仍指向已经废弃的 `main-runtime`。
- 由于宿主机配置脱离 formal deploy，`python -m fqxtrade.xtquant.broker` 在错误 `PYTHONPATH` 下回退到了 `.venv\Lib\site-packages\fqxtrade` 的旧实现，导致 `finance_buy` 仍按 `insufficient_cash` 失败。

## 目标

- 宿主机 Supervisor 运行真值强制收敛到 `main-deploy-production`。
- formal deploy 命中宿主机面时，必须先确保 supervisor 配置文件与 deploy mirror 一致，再执行 surface restart。
- runtime verify 必须能显式识别“配置还指向旧目录”或“import 实际落到 site-packages 旧包”的异常，不再允许静默通过。

## 非目标

- 不重写 supervisor 进程模型，不替换 `fqnext-supervisord` / NSSM / 管理员桥接任务。
- 不在本轮改变 Docker 并行环境或 API deploy 机制。
- 不在本轮改写 `fqxtrade` 交易逻辑本身；本轮修复聚焦宿主机 deploy/runtime 收敛。

## 根因

1. formal deploy 只同步了 deploy mirror 与 mirror `.venv`，但没有把 `D:\fqpack\config\supervisord.fqnext.conf` 纳入正式 deploy contract。
2. `fqnext-supervisord` 启动后使用的是内存中的旧配置；即使后续有人手工改过磁盘文件，未重启 service 时也不会生效。
3. deploy 后 runtime verify 只检查 service/process 是否 Running，没有核验 supervisor 配置真值或关键模块的 import source。

## 方案

### 1. 新增 supervisor 配置真值脚本

新增 `script/fqnext_supervisor_config.py`，职责固定为：

- 以给定 `repo_root` 渲染宿主机正式 `supervisord.fqnext.conf`
- 输出固定指向 `main-deploy-production` 的：
  - `directory`
  - `.venv\Scripts\python.exe`
  - `PATH`
  - `PYTHONPATH`
- 解析现有配置并检查：
  - program directory / command / environment 是否与期望一致
  - `repo_root` 是否存在且为 git worktree
  - `freshquant`、`fqxtrade.xtquant.broker`、`fqxtrade.xtquant.puppet`、`QUANTAXIS` 的 import source 是否落在 deploy mirror，而不是 `.venv\Lib\site-packages`

### 2. formal deploy 命中宿主机面时自动收敛并必要时重载 supervisor

- `run_formal_deploy.py` 在执行 host deploy command 前，为宿主机控制脚本追加 `-SupervisorConfigRepoRoot <repo_root>`。
- `fqnext_host_runtime_ctl.ps1` 在收到该参数后：
  - 先调用 `fqnext_supervisor_config.py write`
  - 判断配置文件是否发生变更
  - 判断配置文件 mtime 是否晚于 `fqnext-supervisord` 当前进程启动时间
  - 如需重载，使用现有管理员桥接任务重启 `fqnext-supervisord`
  - 等待 service 与 XML-RPC 恢复，再继续 `restart-surfaces`

这样即使磁盘配置早已手工修正，只要 service 仍吃着旧内存配置，也会被这轮 formal deploy 主动纠正。

### 3. runtime post-deploy verify 增加 supervisor truth 校验

`check_freshquant_runtime_post_deploy.ps1` 增加 supervisor config snapshot/check：

- CaptureBaseline 时记录当前 supervisor config 检查结果
- Verify 时对命中宿主机面的部署强制检查：
  - 配置 repo root 等于 `main-deploy-production`
  - config / import source 不得落到 `main-runtime` 或 `.venv\Lib\site-packages\fqxtrade`
  - 关键模块 import source 必须在 deploy mirror 下

这使“程序 Running 但跑的是旧代码”变成显式失败。

## 风险与缓解

- 首次迁移到 `main-deploy-production` 时，host surface deploy 会额外触发一次 `fqnext-supervisord` service restart。
  - 缓解：只在配置内容变化或 config mtime 晚于 service start time 时触发，不对每次 deploy 无条件重启。
- 配置模板从“主仓 `.venv`”切到“deploy mirror `.venv`”后，正式运行依赖必须来自 mirror `uv sync`。
  - 缓解：formal deploy 已先在 mirror 执行 `uv sync --frozen`，再进入 host deploy。

## 验收标准

- formal deploy 命中 `order_management` / 其他宿主机面时，`D:\fqpack\config\supervisord.fqnext.conf` 会被自动写成 `main-deploy-production` 版本。
- 若 supervisor service 仍吃着旧配置，formal deploy 会先重载 service，再做 surface restart。
- `check_freshquant_runtime_post_deploy.ps1 -Mode Verify` 能对错误 repo root / `site-packages` import source 给出 failure。
- 相关测试覆盖渲染、配置校验、runtime verify failure/pass 场景。
