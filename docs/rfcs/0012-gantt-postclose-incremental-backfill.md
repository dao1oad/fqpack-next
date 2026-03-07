# RFC 0012: Gantt 盘后任务改为缺口增量回填

- **状态**：Done
- **负责人**：Codex
- **评审人**：TBD
- **创建日期**：2026-03-07
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

RFC 0006 已经在目标仓库落地 Gantt 盘后数据链路，包括：

- XGB / JYGS 原始同步
- `plate_reason_daily`
- `gantt_plate_daily`
- `gantt_stock_daily`
- `shouban30_*`
- `job_gantt_postclose` 与 `gantt_postclose_schedule`

当前问题是 [ops/gantt.py](/D:/fqpack/freshquant-2026.2.23/morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py) 的默认行为仍然是“只处理上一交易日”：

- 正常情况下每天只补 1 天没有问题
- 但如果 Dagster 连续多天失败、服务停机或源站异常，下一次恢复后只会继续处理最新 1 天
- 这会留下中间交易日缺口，必须依赖人工手动逐日回填

本 RFC 的目标是把 `job_gantt_postclose` 从“单日 ETL”改成“按尾部缺口自动补到最新已完成交易日”的增量回填任务，避免多天异常后长期残留历史缺口。

## 2. 目标（Goals）

- 保持 `job_gantt_postclose` 和 `gantt_postclose_schedule` 的入口不变
- 将默认执行语义改为：
  - 从 `gantt_plate_daily` 最新已完成交易日的下一天开始
  - 连续回补到按交易日历与盘后截止时间解析出的最新已完成交易日
- 首次无历史进度时仅处理最新已完成交易日 1 天
- 已追平最新已完成交易日时返回 no-op
- 某一天失败时，已成功日期保留，下一次运行从失败日期继续补
- 不新增新的 Mongo 库、schedule 或独立 backfill job

## 3. 非目标（Non-Goals）

- 不改造 `stock_data_job`、`etf_data_job`、`future_data_job` 等 market data assets
- 不改造 `job_backfill_order` 或 `job_clean_db`
- 不把通用“按交易日缺口回填框架”扩展到其他 Dagster job
- 不改变 Gantt 读模型 schema 或 HTTP API 契约
- 不增加并行回填、分片回填或按 provider 分离执行

## 4. 范围（Scope）

**In Scope**

- `job_gantt_postclose` 的默认执行语义
- Gantt Dagster ops / job / schedule 相关测试
- 缺口判定逻辑
- 逐交易日串行执行逻辑
- 进度与 breaking changes 文档

**Out of Scope**

- 其他 Dagster job
- 其他业务模块的补历史策略
- UI、API 或数据库表结构调整

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- 以 `gantt_plate_daily.trade_date` 作为“该交易日是否已完成 Gantt 构建”的判定依据
- 基于交易日历与盘后截止时间计算“目标最新交易日”
- 找出从最新已完成交易日的下一天到目标最新交易日之间的连续待补列表
- 对待补交易日逐日执行现有完整链路：
  - `sync_xgb_history_for_date`
  - `sync_jygs_action_for_date`
  - `persist_plate_reason_daily_for_date`
  - `persist_gantt_daily_for_date`
  - `persist_shouban30_for_date`

**不负责（Must Not）**

- 不推断“部分成功”的更细粒度状态，例如只同步了 XGB 但未构建读模型
- 不对失败日期做自动跳过
- 不在失败时自动回滚前面已成功日期
- 不引入“只补原始表，不补读模型”的分阶段模式

**依赖（Depends On）**

- `freshquant.data.trade_date_hist.tool_trade_date_hist_sina`
- `freshquant.data.trade_date_hist.get_trade_dates_between`
- `freshquant.db.DBGantt`
- RFC 0006 已落地的 Gantt 原始表与读模型表

**禁止依赖（Must Not Depend On）**

- 新的 schedule
- 新的数据库/缓存
- 旧仓库手工补数脚本

## 6. 对外接口（Public API）

这里的“对外接口”仅指 Dagster job 的运行语义，不新增新的 HTTP/CLI 接口。

### 6.1 Dagster Job

- Job 名称保持：`job_gantt_postclose`
- Schedule 名称保持：`gantt_postclose_schedule`
- 默认执行语义从：
  - “只处理上一交易日”
- 改为：
  - “从最新已完成交易日的下一天开始，补到按交易日历和盘后截止时间解析出的最新已完成交易日”

### 6.2 错误语义

- 若交易日历无法解析出最新已完成交易日，任务失败并报错
- 若不存在缺口，任务直接 no-op
- 若某个交易日执行失败：
  - 当前 run 失败
  - 已成功日期保留
  - 后续日期不继续执行

### 6.3 兼容策略

- 保持 Dagster job 名称、schedule 名称和入口模块不变
- 不要求现有运维改 cron 或切换到新 job

## 7. 数据与配置（Data / Config）

- 不新增新的 Mongo collection
- 缺口判定来源：
  - `freshquant_gantt.gantt_plate_daily.trade_date`
- 最新目标日来源：
  - 交易日历 + 运行时当前时间
  - 若当天是交易日且当前时间 `>= 15:05`，目标日取当天
  - 否则目标日取最近一个更早的交易日
- 交易日列表来源：
  - `get_trade_dates_between(start_date, end_date)`
- 不新增新的运行时配置项

## 8. 破坏性变更（Breaking Changes）

这是一次行为语义变更。

- **变更**：`job_gantt_postclose` 不再只处理单日，而是从最新已完成交易日的下一天开始自动补齐尾部缺口到最新已完成交易日
- **影响面**：
  - Dagster 单次 run 耗时可能显著增加
  - 连续失败恢复后的第一次 run 可能执行多天数据同步
  - 运维监控不能再按“每日固定只跑 1 天”假设估算耗时
  - 盘后 `15:05` 之后触发的 run 会将当天视为可处理目标日，不再等到下一交易日
- **迁移步骤**：
  1. 部署包含本 RFC 的新代码
  2. 保持原有 `gantt_postclose_schedule` 不变
  3. 如存在尾部历史缺口，允许首次 run 自动补齐
- **回滚方案**：
  - 回退 `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`
  - 回退 `morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py`
  - 恢复默认只处理单日的 Dagster 链式 job

## 9. 迁移映射（From `D:\fqpack\freshquant`）

本 RFC 不从旧仓库迁移功能，而是调整目标仓库现有 Dagster 运行语义。

- 现有目标仓库 `job_gantt_postclose`：单日盘后同步
- 调整后目标仓库 `job_gantt_postclose`：尾部缺口增量回填到最新已完成交易日

## 10. 测试与验收（Acceptance Criteria）

- [x] 当 `gantt_plate_daily` 已覆盖到最新已完成交易日时，任务不会错误回补更早日期
- [x] 当缺失最近 1 个交易日时，任务会补上该 1 天
- [x] 当缺失连续多个交易日时，任务会从最新已完成交易日的下一天连续补到目标最新交易日
- [x] 当中间某一天失败时，任务停止在该天，已成功日期保留
- [x] Dagster 相关测试覆盖新的缺口列表解析、逐日执行语义与 job 入口导入
- [x] 在并行 Docker 环境中，真实运行态已验证 `pending=[]` 时可正确 no-op

## 11. 风险与回滚（Risks / Rollback）

- 风险：一次 run 处理多天数据，耗时变长
  - 缓解：保持串行和幂等写入，不扩大并发面
- 风险：失败日卡住后续日期，导致 run 失败
  - 缓解：这是预期行为，便于下次从失败点继续补
- 风险：缺口判定过粗，只看 `gantt_plate_daily`
  - 缓解：按当前 RFC 0006 语义，`gantt_plate_daily` 代表整日主链路完成；不引入更复杂状态机
- 风险：盘后目标日判定若沿用 `query_prev_trade_date()`，会在交易日当天收盘后少补 1 天
  - 缓解：实现改为按交易日历与 `15:05` 截止时间计算最新已完成交易日

回滚方式：

- 回退本 RFC 相关代码改动
- 重建 Dagster 容器
- 保持已有已补数据，不需要删除历史结果

## 12. 里程碑与拆分（Milestones）

- M1：RFC 0012 评审通过
- M2：补充设计稿与实施计划
- M3：新增测试，覆盖缺口交易日解析与逐日补齐语义
- M4：实现 `job_gantt_postclose` 缺口回填
- M5：并行 Docker 环境验证与文档收尾
