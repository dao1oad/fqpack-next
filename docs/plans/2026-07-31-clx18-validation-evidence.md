# CLX18 本地迁移真实数据验证证据

- 验证日期：2026-07-31；Issue #482 production 复验日期：2026-08-01
- 代码提交：`b8c7c6ad feat: sync fqchan04 and fqcopilot CLX18 sources`
- 本地 main 合并提交：`1122979d merge: sync fqchan04 and fqcopilot CLX18 sources locally`
- 数据来源：`D:\new_tdx` 通达信日线文件，每个标的最多取最近 1560 根
- 构建来源：当前工作树源码隔离构建的 CPython 3.12 wheel；未复用旧 `.venv` 二进制

## 结果

- S0000-S0017 生产模型 `10000..10017`：20 个日线文件 × 18 个模型，共 360 次调用。
- all length/finite checks PASS：每次返回长度与输入一致，所有值均为有限整数信号。
- 当时的 `fq_clxs_all` 与 `model_opt=0..17`（legacy_sall_v0/switch_opt=0）逐项一致：18/18；该记录不证明 production_v1/switch_opt=1 batch parity。Issue #482 必须新增当前 checkout 的 production batch 与 `10000..10017` 逐 bar 证据。
- `fullcalc.full_calc(..., model_ids=10000..10017, trend_opt=0)`：`ok=True`，缠论结构长度正确。
- `fqchan04.fq_recognise_bi` 新 close ABI：真实日线长度和有限值检查通过。

`trend_opt=0` 的非零信号计数为：

```text
[3178, 20, 166, 35, 254, 315, 139, 162, 167,
 122, 254, 40, 18, 10, 7, 179, 75, 857]
```

S0015 把 `trend_opt` 作为 `ext_opt` 解析。`trend_opt=1` 等价于 MA1，样本信号为 0；`trend_opt=0` 或 `250` 使用 MA250，并产生非零信号。这是参数语义，不是执行异常。

完整机器记录曾写入：

```text
D:\fqpack\runtime\tmp\issue480-validation-summary.txt
```

本文件只保存验收事实；临时构建目录在任务收尾时清理。

## 2026-08-01 Issue #482 production_v1 当前工作树复验

- 构建来源：从当前 `codex/issue-482-clx-daily-selection` task-only 候选源码，CPython 3.12 强制原地构建 `fqchan04`、`fqcopilot` 与 `fullcalc` 三个扩展，构建命令退出码均为 0；验证进程打印的模块路径均指向隔离候选，未复用 canonical root 的旧二进制。新五参数 `recognise_bi(..., close, options)` 保留旧四参数重载，候选 `fqchan04` 的旧 Python 调用实际执行通过。
- 四参数 legacy 等值回归：分别从 `origin/main` 与候选强制构建 `fqchan04`，对 5 个固定种子、每组 900 bars、`bi_mode=default/4/5/6` 的输出做逐值 SHA256；两侧均为 `bc6281423286ccad3f875854d2fde87ffe3ed0d9e30ba65690b44722e8e9ed24`，且 `11/-11/12/-12` 计数均为 0。只有带非空 close 的五参数 production 路径生成确认 marker。
- 接口口径：`fq_clxs_all(..., switch_opt=0)` 保持 `legacy_sall_v0` 默认；显式 `switch_opt=1` 为 `production_v1`，并对非法 switch 与 OHLCV/length 不对齐 fail-fast。
- 固定 fixture：4 组样本 × 18 模型逐 bar 对账全部通过；S0015 包含在统一 parity 中。S0002 entrypoint 3 的 `+1/+2/-1/-2` 四类结构证据 fixture 全覆盖。
- 原生专项测试：`12 passed`；真实数据验证前后构建产物可导入并执行 production batch、single 与 S0002 evidence 接口。下界回归同时覆盖 `fq_clxs_all(length=1, switch_opt=1)` 的 18 模型单 bar 输出，以及 `fullcalc(model_ids=[10015])` 在 10 根 flat bars 上不发生 `size_t` 下溢。
- `morningglory/fqcopilot/cpp/chanlun/czsc.cpp` 的最小依赖 A/B：保留单 bar hunk 时，history 使用的 production batch 对 18 个模型均返回 1 个值且退出 0；恢复 `origin/main` blob 后触发 `IndexError: invalid vector subscript`。该文件因此绑定 `/history/signals?barCount=1` 下界。
- `morningglory/fqchan04/cpp/chanlun/czsc.cpp` 的最小依赖 A/B：`fullcalc.full_calc` 以 10 根 flat bars 和 `model_ids=[10015]` 运行时，保留 hunk 得到 `ok=True`、`bi/duan` 长度均为 10 且退出 0；恢复 `origin/main` blob 后触发同一 `IndexError`。`setup.py` 的 fullcalc source list 固定编译 `fqchan04/cpp/chanlun`，该文件因此绑定 S0015 flat-window 下界。
- 真实数据：从 `D:\new_tdx\vipdoc` 取确定性 20 个日线文件，共 28,847 bars；对 S0000-S0017 执行 360 次 production 单模型调用。
- production batch 18 行与 `fq_clxs(..., 10000 + model_id)` 逐 bar 对账，18 个模型的 mismatch count 全部为 `0`：

```text
[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
```

- S0002 真实结构 evidence 计数为 `{-2: 21, -1: 2, 0: 28809, 1: 1, 2: 14}`；四类非零 evidence 均与同 bar 的 S0002 raw signal 在方向和 `entrypoint=3` 上对齐。

以下 legacy 与 production 差异向量来自本次最终复验之前的 24,701-bar 历史运行，保留用于说明 profile 隔离来源，不作为当前 #482 的 28,847-bar parity 统计：

```text
[0, 82, 443, 0, 0, 184, 0, 0, 0, 164, 221, 47, 39, 0, 0, 0, 0, 0]
```

该历史差异只覆盖 S0001、S0002、S0005、S0009、S0010、S0011、S0012，与 profile 隔离合同一致；其旧 S0002 evidence 计数不替代上面的当前 #482 真机证据。

## 2026-08-01 服务层运行适配结论

上述原生源码 parity 证明 production batch 的目标语义；服务层还必须适配实际部署运行时。当前本机 `fqcopilot` 没有可用 `fq_clxs_all` production batch 入口，因此 `FqCopilotProductionEngine` 使用 18 次 `fq_clxs(...,10000+m)` 作为严格生产 fallback，并在 partition/history 结果记录：

- `calculation_mode=single_model_fallback`；
- batch 完全缺失：`fallback_reason=fq_clxs_all_unavailable`；
- batch 仍是缺少 `switch_opt` 的旧签名：`fallback_reason=fq_clxs_all_missing_switch_opt`。

该适配保持 `production_v1/switch_opt=1` 与逐 bar production parity，不读取或调用 `legacy_sall_v0/switch_opt=0`。当部署运行时提供受测的 `fq_clxs_all(..., switch_opt=1)` 后，adapter 可使用 `batch_production_v1`；两条计算路径都受同一 parity 合同约束。

## 2026-08-01 Dagster catch-up 与 publication 增量验收合同

这一增量不改变上面的 native parity 事实。当前合入候选的最终组合回归还必须单独保存以下机器证据，未完成的检查不计入本文件已通过的 native 结论：

- `resolve_recent_completed_trade_dates(limit=5)` newest-first 返回最近 5 个已完成交易日；项目时区当天 `15:05` 前不纳入，周末、节假日和未收盘日期不产生未来交易日。
- stock、ETF、finalizer 每个 sensor 每 tick 最多一条 `RunRequest`；marker 缺失或 `reuse/wait` 继续旧日，`active` 停止，`run` 立即返回。
- D+1 延迟 marker 能启动旧日对应 partition；同一 selection 的失败侧生成 `attempt_no=2`，成功侧仍为 `reuse`；旧日 failed/expired publication 能独立重试而不重算两个 completed partition。
- publication 的 `generation_order` 固定为规范 UTC 微秒键 `YYYY-MM-DDTHH:mm:ss.ffffffZ|batch_id`；同一 `publication_id` 重试幂等成功。
- 新 generation 先发布、旧 publisher 后恢复时，ready marker 保持新 generation；旧 batch 的 publication 明确为 `failed`，`last_error.code=stale_publication`，不得被推进为 `published`。
- fork-join 主合同继续固定：单侧 marker success 独立启动本侧 `production_v1/switch_opt=1` CLX18 partition；双侧 completed 只门控 finalizer、正式发布和跨资产统计，partial 不冒充 final。
