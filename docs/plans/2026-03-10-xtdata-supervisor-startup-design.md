# XTData Supervisor 启动修复设计

- **日期**：2026-03-10
- **状态**：Approved
- **范围**：最小恢复宿主机 `fqnext_realtime_xtdata_producer`、`fqnext_realtime_xtdata_consumer`、`fqnext_xtdata_adj_refresh_worker` 的稳定启动，不扩展到其它运行面收敛。

## 目标

- 修复 `market_producer` 与 `strategy_consumer` 在 `python -m ...` 启动路径下的入口级 `NameError`。
- 让 `adj_refresh_worker` 在宿主机存在全局代理变量时仍可稳定查询交易日历。
- 将宿主机 `D:\fqpack\config\supervisord.fqnext.conf` 从旧的 `Miniconda fqkit` 切回项目内 `.venv`，对齐 RFC 0009 的运行面。

## 非目标

- 不重构 XTData producer/consumer 的业务逻辑。
- 不改动 `monitor.xtdata.mode`、订阅池、前复权语义或参考数据调度时刻。
- 不顺手清理全部宿主机环境变量、Docker 配置或其它 supervisor 进程。

## 方案

### 1. Producer / Consumer 入口回归

- 根因是模块顺序执行时，`if __name__ == "__main__": main()` 出现在 `_emit_runtime()` / `_get_runtime_logger()` 定义之前。
- 修复方式是将 helper 定义移动到入口调用之前，不改变外部接口和运行语义。
- 回归测试覆盖真实模块入口路径，而不是只覆盖导入后直接调函数。

### 2. Adj Refresh 代理屏蔽

- `adj_refresh_worker` 在启动时立即跑 `run_once()`，交易日查询走 `ak.tool_trade_date_hist_sina()`。
- 宿主机存在 `ALL_PROXY=socks5://...` 时，若当前解释器未安装 `PySocks`，`requests` 会直接抛 `InvalidSchema` 并导致进程退出。
- 修复方式是在 `freshquant.trading.dt` 中对交易日拉取做最小范围的代理环境屏蔽，并确保调用结束后恢复原环境。

### 3. Supervisor 运行面修复

- 将 `D:\fqpack\config\supervisord.fqnext.conf` 中 `PATH` 和 `command=` 的 Python 路径统一切到项目 `.venv`。
- 当前开发在隔离 worktree 中进行，因此本地验证阶段先让 supervisor 指向当前 worktree 目录下的 `.venv` 与代码树，保证“配置切换”和“代码修复”同时可验证。
- 合并回主工作树后，需把同一配置中的目录路径切回正式仓库路径。

## 验收标准

- 入口回归测试先失败后通过。
- `freshquant.trading.dt` 的代理屏蔽测试先失败后通过。
- worktree 下 `.venv\Scripts\python.exe --version` 返回 `Python 3.12.x`。
- 重载 supervisor 后，这 3 个进程不再持续重启，状态稳定为 `Running`。
