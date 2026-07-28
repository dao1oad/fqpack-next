# CLX18 日线目标收益触达率报告

## 当前实现

仓库提供独立的目标收益触达率事件引擎与本地聚合报告面：

- 事件引擎：`freshquant/backtest/clx_target_hit/engine.py`
- S0000 合同切片：`script/clx_target_hit/build_fixture_report.py`
- 完整事件宇宙：`script/clx_target_hit/build_event_universe.py`
- 事件结果与分阶段聚合：`script/clx_target_hit/compute_event_outcomes.py`、
  `script/clx_target_hit/compute_stage1.py`
- 候选与资金双锁：`script/clx_target_hit/select_and_challenge.py`、
  `script/clx_target_hit/lock_portfolio_candidate.py`
- 最终报告：`script/clx_target_hit/build_final_report.py`
- 本地报告服务：`script/clx_target_hit/serve_report.py`
- 运行状态：`outputs/clx18_target_hit/run_state.json`
- 聚合报告：`outputs/clx18_target_hit/report.json`
- 完整筛选网格：`outputs/clx18_target_hit/final_grid.parquet`
- 产物清单：`outputs/clx18_target_hit/final_manifest.json`、
  `outputs/clx18_target_hit/artifact_inventory.json`

固定研究合同为日线前复权、T 日收盘揭示、T+1 开盘买入、双向各
`0.02%`；`H=5..90` 每 5 日一档，`R=2%..30%` 每 1 个百分点一档。
触达成功按持有窗口内最高价扣除双向手续费后的净收益判断，未触达事件
按第 H 日收盘计算真实净收益。

## 本地启动

```powershell
.venv\Scripts\python.exe script/clx_target_hit/serve_report.py --host 127.0.0.1 --port 18765
```

固定页面为 `http://127.0.0.1:18765`，健康检查为
`http://127.0.0.1:18765/healthz`。前台启动时按 `Ctrl+C` 停止；后台启动
记录了 `outputs/clx18_target_hit/server.pid` 时可执行：

```powershell
$reportPid = [int](Get-Content outputs/clx18_target_hit/server.pid)
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$reportPid"
if ($process.CommandLine -match 'serve_report\.py') {
    Stop-Process -Id $reportPid
}
```

该报告的部署边界固定为本机 `localhost/127.0.0.1`。它不发布到远程主机、
云端、Sites 或公网地址。项目通用 Done 定义中的远程 merge 后 formal deploy
对这个独立本地分析页面标记为 `NOT_APPLICABLE`；本页面的运行验收真值是本机
启动进程、`GET /health`、聚合接口和关键筛选/图表交互检查。回测计算输入仍须
来自已核验的冻结 artifact，计算资源位置不改变页面的本地交付边界。

## 本地验收

- `GET /health`、`GET /healthz` 返回 `status=ok`、`report=true`、
  `checks_passed=true` 和 `data_status=CLX18_FULL_HISTORY_AUDIT_REVEALED`
- `GET /api/report` 返回合同、生成时间、哈希、检查结果和聚合行
- `GET /api/facets` 返回模型、阶段、触发视图、触发组合、过滤条件和推荐选择
- `GET /api/grid` 对一个完整筛选切片最多返回 522 行，并从
  `final_grid.parquet` 做谓词下推
- 页面可切换模型、阶段、触发视图、触发组合与过滤条件
- 当前筛选显示完整 `18 × 29 = 522` 个 H×R 单元
- CSV、Parquet、检查 JSON、锁文件和运行状态由 `GET /api/manifest` 提供本机导出入口
- `GET /exports/<name>` 只允许报告目录中的声明后缀文件，路径穿越请求返回 400
- 进程停止后固定端口不再监听
- 最终机器验收记录为 `outputs/clx18_target_hit/checks.json`；当前记录覆盖
  37 项测试、产物哈希、HTTP、浏览器交互、停止/重启和清理检查，根字段
  `passed=true`

## 当前数据与封存边界

当前聚合产物的数据状态是 `CLX18_FULL_HISTORY_AUDIT_REVEALED`：

- TRAIN+VALIDATION 完整事件宇宙 `2,020,050` 行，AUDIT `583,652` 行；
- 旧 eligible 的事件键、并发触发掩码和 F1-F7 掩码逐项零漂移；
- 开发网格 `2,653,181` 行，AUDIT 网格 `1,230,876` 行，最终网格
  `3,884,105` 行；
- 候选锁覆盖字面冠军、实用冠军、18 个模型、29 个收益目标和 18 个期限，
  共 67 个类别、63 个唯一候选；
- `candidate_lock.json` 与 `portfolio_lock.json` 都在首次读取 AUDIT 分区前
  落盘并通过自哈希、输入 SHA 和双锁绑定检查；AUDIT 只用于锁定后稳定性报告。

尾部 purge 按个股实际第 H 根 bar 的退出日是否跨越分层边界判断；leading
embargo 按上证交易日历的 H 个交易日判断。F1-F6 保留原候选构建窗口语义，
F7 单独使用揭示日全历史、包含当日的前复权 MA250。
