# CLX pre-HOLDOUT preview handoff

更新时间：2026-07-24 20:17 +08:00。

## 当前目标

在不读取、不揭示、不重跑 HOLDOUT 的前提下，将已完成的 S0002/e4 semantic-recovery child run 投影到 `freshquant_clx_backtest`，通过临时只读网关展示 `/clx-backtest` 的 TRAIN / VALIDATION 结果。

这不是 formal deploy，也不是完整 CLX 项目的 Done。完整 goal 仍包括 HOLDOUT、portfolio、PR/CI/review/merge、formal deploy、health check 和 cleanup；本 preview 阶段不自动执行这些工作。

## 不可越过的边界

- 不调用 API 的 `start`、`freeze`、`reveal`，不读取或揭示 HOLDOUT。
- 只写 child `run_id=01KBYC7REC0V3RY99634853AAB` 的派生 Mongo 文档；绝不写 source run。
- 不停止、删除或清理 source facts 容器/目录。其旧 facts 容器可能为 `unhealthy`，不是本任务的清理对象。
- 不在 `D:\fqpack\freshquant-2026.2.23` 的 `main` 上编辑或提交。工作树固定为 `D:\fqpack\worktrees\clx-backtest-platform-465`，分支为 `codex/clx-backtest-platform-465`。
- 临时网页必须经只读网关：允许 `GET`、`HEAD`、`OPTIONS`，仅额外允许精确的 `POST /api/clx-backtest/compare`；不得将现有可写 `/api` 直接暴露给用户。

## 已完成的回测证据

以下来自上一轮已完成的 runtime artifact 链。VM 连接恢复后，应以 sealed manifest 和 run contract 重新核验，而不是重新跑 64 个 bucket。

| 项目 | 事实 |
| --- | --- |
| Child run | `01KBYC7REC0V3RY99634853AAB` |
| Child artifact root | `/opt/fqpack/runtime/clx-backtest/events/clx-preview-99634853b` |
| Source artifact root | `/opt/fqpack/runtime/clx-backtest/events/full-6165d5a52437` |
| facts | `64/64` 完成；本 child run `native_prefix_calls_this_run=0` |
| event | `5,867,120` outcomes；manifest SHA 前缀 `89676bcc` |
| ranking | 27 个冻结组合、54 条 split metrics；manifest SHA 前缀 `40554a30` |
| HOLDOUT gate | `HOLDOUT=LOCKED`、`successful_holdout_reads=0`、`holdout_rows_read=0` |
| wrapper 结论 | `CLX semantic recovery pre-HOLDOUT chain completed` |

preview 可以展示 ranking、热力图、组合定义和信号质量。投影使用 `portfolio_dirs={}`，因此资金曲线、成交和 portfolio 指标为空；这些要在后续单独运行 TRAIN/VALIDATION portfolio，仍不读取 HOLDOUT。

## 代码、测试与工作树

- 当前 HEAD：`989cdd57`，已跟踪 `origin/codex/clx-backtest-platform-465`。
- Draft PR：#466。当前机器未安装 `gh`，本轮未复验 GitHub 实时 CI/review 状态。
- semantic recovery：`873968a1`；sealed contract 路径：`99634853`；runtime identity：`58ff444c`；runner command：`9d82690c`。
- projector 将 `NaN -> null`，并将非 TRAIN split 的 `discovery_score=-inf -> null`：`5d0a4e3d`。仅 `+inf` 是 artifact 损坏并 fail-closed，不能泛化为 `null`。
- 指标语义已写入 `989cdd57` 的 `docs/current/modules/clx-backtest.md`。
- 已实测：`& .\.venv\Scripts\python.exe -m pytest freshquant/tests/clx_backtest/test_worker_projector.py -k json_value_projects_undefined_metrics_as_null -q`，结果为 `1 passed, 27 deselected`。
- 未跟踪的 `morningglory/fqwebui/.env.clxpreview` 不属于本 handoff，必须保留且不得纳入提交。

## 已知投影故障

第一次投影在 `ClxArtifactProjector._project_ranking()` 失败：immutable JSON content hash 拒绝非有限数。实际 artifact 的 27 条 VALIDATION `discovery_score` 为 `-inf`，这是仅在 TRAIN 计算 score 时留下的“不适用” sentinel，不是回测计算失败。

上次远端审计观察到，child run 在 Mongo 中仅遗留 `combo_definitions=27`；`combo_metrics`、`manifests`、`portfolio_*`、`combo_signals`、`model_heatmap`、`audit_findings`、`jobs`、`runs`、`progress_events` 都为 0。由于当前 SSH 不可达，这一状态必须在接手时先复查。

若复查仍一致，清理范围只能是：

```javascript
db.combo_definitions.deleteMany({ run_id: "01KBYC7REC0V3RY99634853AAB" })
```

执行前后必须按 `run_id` 做 collection count 与 `_id` 审计。不得使用空条件，不得触及 source run、ledger 或 HOLDOUT 相关集合。

## 当前机器实测状态

| 检查 | 当前事实 | 影响 |
| --- | --- | --- |
| `ssh fqcompare@192.168.77.10` | `Permission denied (publickey)`；本机 `.ssh` 没有私钥 | 不能重投影、检查远端 Mongo 或启动网关 |
| 本地 `127.0.0.1:18098` | 无 listener，HTTP connection refused | 当前没有可打开的网页链接 |
| 本地 `127.0.0.1:27027` | connection refused | memory bootstrap 无法写入 `fq_memory`，不影响已有 artifact |
| `gh` | 未安装/不在 PATH | 本轮不能读取 PR #466 的实时 CI/review |

因此“回测完成”已有 sealed artifact 证据；“Mongo 投影和网页可访问”仍未完成，且未在本轮重新验证。两者不可混淆。

## 接手顺序

### 1. 恢复 VM 访问并做只读审计

VM 为 `fqcompare@192.168.77.10`。恢复已有凭据后先验证：

```powershell
ssh -o BatchMode=yes -o ConnectTimeout=8 fqcompare@192.168.77.10 "true"
```

然后读取 child `run-contract.json`、signal/event/ranking manifest 和 sealed proof，并按 `run_id` 查询所有 run-scoped Mongo collections。上述操作不触及 HOLDOUT。

### 2. 用新 image 重投影

旧 image `sha256:fe27d7...` 不含 `5d0a4e3d`，不得复用。以当前 branch HEAD 构建隔离 projector image，只读挂载 CLX artifact root，并使用 `mongodb://fq_mongodb:27017`。不要替换现有 `fq_apiserver`、`fq_webui` 或 worker，也不要触发 formal deploy。

共享工作树中有两个 ignored helper 文件，cleanup 前必须保留；新 worktree 需要先从这里复制：

- `.artifacts/project_clx_preholdout_preview.py`
- `.artifacts/clx_readonly_preview_nginx.conf`

投影 harness 在写入前校验 child contract、`HOLDOUT=LOCKED`、zero HOLDOUT reads、sealed event preverification、manifest/contract/image/source identity。关键环境变量：

```bash
export CLX_TARGET_RUN_ROOT=/opt/fqpack/runtime/clx-backtest/events/clx-preview-99634853b
export MONGO_URL=mongodb://fq_mongodb:27017
python /path/to/project_clx_preholdout_preview.py
```

成功输出必须是 `status=projected-preholdout`，并包含同一 `run_id` 与三份 manifest SHA。再次出现 `-inf`/non-finite JSON 错误意味着实际运行的仍是旧 image；不要清空 Mongo，也不要重跑 facts。

### 3. 启动临时只读网页

已有 `fq_webui` 与 `fq_apiserver` 可复用。将 nginx config 放到 VM 的 `/home/fqcompare/clx-readonly-preview/nginx.conf`，把临时 nginx 加入 `freshquant-2026718_default` network，并仅绑定 VM loopback `127.0.0.1:18098:80`。通过 SSH tunnel 转发同端口。

最终用户入口：

```text
http://127.0.0.1:18098/clx-backtest?run_id=01KBYC7REC0V3RY99634853AAB&tab=results
```

验收：页面 `200`；child run 结果可加载；`GET /api/clx-backtest/health` 正常；写操作返回 `405`；仅 compare 的精确 `POST` 可用；页面没有 HOLDOUT 数据。

### 4. 收尾记录

投影成功后更新本文件：实际 projector image SHA、Mongo counts、投影时点、gateway container 名、tunnel PID、页面验收结果和残留限制。用户确认后才停止临时 gateway/tunnel；该入口不能被记作 formal deploy。

## 失败处理

- SSH 仍失败：停在“访问凭据阻塞”，保留全部 artifact，不执行猜测性的 Docker、Mongo 或 deploy 命令。
- Mongo 出现超过预期的 child 文档：先导出 collection/`_id`/content hash 审计，不能 delete/reproject。
- projector 报 immutable conflict：与 sealed artifact 比较，不 force overwrite。
- 页面 API 为 502：检查临时 nginx 与 `fq_apiserver` 是否同一 Docker network；不得为了预览重启正式服务。

## 完整目标的后续分界

本 preview 只解决“尽快查看 pre-HOLDOUT 结果”。后续只有在用户明确授权后才进入 HOLDOUT 单次 reveal、portfolio、真实研究结论、PR #466 CI/review/merge、latest remote `main` formal deploy、health/runtime 验收和 cleanup。


## 2026-07-24 20:5x +08:00 接手复核与网关启动记录

- SSH 已恢复：私钥位于 `D:/fqpack/runtime/compare-vm/20260722/autoinstall/fqcompare_ed25519`；Windows OpenSSH 客户端在本机自动化环境下无输出退出（code 255），实际使用 paramiko（`.codex/remote_win.py` / `.codex/tunnel_win.py`）。
- 只读审计（未触及 HOLDOUT）：
  - `run-contract.json` 与 handoff 一致：`holdout_state=LOCKED`、run_id `01KBYC7REC0V3RY99634853AAB`。
  - manifest SHA 实测：event `89676bcc…`、ranking `40554a30…`、facts/signal `1d85bc3b…`，与 runs 文档一致。
  - `semantic-recovery-preholdout/` 存在 `event-study.passed` 等 sealed proof；`.runner/` 有 `complete`、`finalized`。
- Mongo 复查结果与 handoff 记录不同：投影已完成（runs 文档 `status=COMPLETE`，created_at 2026-07-24T10:33:32Z）。counts（按 run_id）：runs=1、manifests=1、combo_definitions=27、combo_metrics=54（TRAIN 27 + VALIDATION 27）、model_heatmap=24（VALIDATION）、其余 0。VALIDATION 的 27 条 `discovery_score` 均为 null（即 `5d0a4e3d` 修复语义已生效），HOLDOUT 相关文档为 0。因此未执行任何 delete，也未重投影。
- 临时只读网关已启动：VM 容器 `clx-readonly-preview-gw`（nginx:alpine，network `freshquant-2026718_default`，仅绑定 `127.0.0.1:18098:80`，config `/home/fqcompare/clx-readonly-preview/nginx.conf`）。
- 本机 tunnel：paramiko 端口转发脚本 `.codex/tunnel_win.py`（后台 PID 28964），本机 `127.0.0.1:18098` -> VM `127.0.0.1:18098`。注意：初版脚本 EOF 时直接 close 导致部分响应 10054 reset，已改为半关闭（shutdown write）。
- 页面验收（经本机 tunnel 实测）：`/clx-backtest?run_id=…&tab=results` 200；`/api/clx-backtest/health` 200；rankings TRAIN/VALIDATION 200；rankings HOLDOUT 423 HOLDOUT_LOCKED；manifest/quality/model-heatmap 200；`POST /runs`、`DELETE` 等写操作 405；仅 `POST /api/clx-backtest/compare` 放行（空参数返回 400 属预期校验）。
- 残留限制：portfolio_* 为空（portfolio_dirs={}），资金曲线/成交为空属预期；该入口仍是 preview，非 formal deploy。用户确认后再停止 gateway/tunnel。


## 2026-07-24 CLX 回测完成记录（用户已授权 HOLDOUT）

- TRAIN/VALIDATION portfolio 已用不可变 engine image `fq_clx_preview:99634853`（sha256:c54011fdf3f7）按官方链参数构建并 verify（`portfolios/clx-preview-99634853b/{TRAIN,VALIDATION}`）。
- HOLDOUT 单次 reveal 已执行：ledger `holdout-ledger/d4e3b38c...`，`logical_reveals=1`，`ledger_complete_records=1`，reveal_id `sha256:4723f7a9...`；HOLDOUT portfolio 使用 reveal artifact 构建并 verify。
- V2 portfolio gate（v2_portfolio_real.sh）在真实 artifact 上 `status=verified`。
- Mongo 最终投影完成：manifests 含 portfolios + holdout attachment，combo_metrics 81（27x3 split），portfolio_summaries 24，freeze_records 1（state=REVEALED, reveal_count=1，api_freeze_id `sha256:70511fd3...`）。
- 发现并修复真实缺陷：`portfolio_summary_unique` 索引未含 split_id，导致同一组合跨 split 投影冲突；已提交 `fix: scope portfolio summary uniqueness by split`（075b8981），并在派生库执行了索引迁移（drop 旧索引后由 ensure_indexes 重建）。
- preview 网关/tunnel 仍在运行，正式 deploy 后清理。
