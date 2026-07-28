# CLX18 日线目标收益触达率报告

## 当前实现

仓库提供独立的目标收益触达率事件引擎与本地聚合报告面：

- 事件引擎：`freshquant/backtest/clx_target_hit/engine.py`
- S0000 合同切片：`script/clx_target_hit/build_fixture_report.py`
- 本地报告服务：`script/clx_target_hit/serve_report.py`
- 运行状态：`outputs/clx18_target_hit/run_state.json`

固定研究合同为日线前复权、T 日收盘揭示、T+1 开盘买入、双向各
`0.02%`；`H=5..90` 每 5 日一档，`R=2%..30%` 每 1 个百分点一档。
触达成功按持有窗口内最高价扣除双向手续费后的净收益判断，未触达事件
按第 H 日收盘计算真实净收益。

## 本地启动

```powershell
.venv\Scripts\python.exe script/clx_target_hit/build_fixture_report.py
.venv\Scripts\python.exe script/clx_target_hit/serve_report.py --host 127.0.0.1 --port 18765
```

固定页面为 `http://127.0.0.1:18765`，健康检查为
`http://127.0.0.1:18765/health`。停止方式是在服务终端按 `Ctrl+C`。

## 数据状态边界

页面直接显示聚合产物的数据状态。`S0000_PHASE0_FIXTURE` 仅证明 522 格、
手续费、首次触达、单调性、F7 子集和页面纵向链路；它不代表 18 模型全量
实证结果。全量阶段只接受冻结事件 artifact，并在 `TRAIN+VALIDATION`
完成候选锁定后连接 `AUDIT`。
