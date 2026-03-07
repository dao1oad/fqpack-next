# Gantt 盘后任务缺口增量回填设计

**目标**：把 `job_gantt_postclose` 从“默认只处理上一交易日”改成“从最新已完成交易日的下一天开始，连续回补到按交易日历和盘后截止时间解析出的最新已完成交易日”，在多天异常后自动补齐尾部缺口。

## 1. 当前现状

### 1.1 现有 Dagster 结构

- [jobs/gantt.py](/D:/fqpack/freshquant-2026.2.23/morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py)
  - `job_gantt_postclose`
- [ops/gantt.py](/D:/fqpack/freshquant-2026.2.23/morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py)
  - `op_sync_xgb_history_daily`
  - `op_sync_jygs_action_daily`
  - `op_build_plate_reason_daily`
  - `op_build_gantt_daily`
  - `op_build_shouban30_daily`
- [schedules/gantt.py](/D:/fqpack/freshquant-2026.2.23/morningglory/fqdagster/src/fqdagster/defs/schedules/gantt.py)
  - `gantt_postclose_schedule`

### 1.2 当前行为问题

- 当前目标日解析依赖“上一交易日”语义，不适合交易日盘后补到当天
- 每个 op 都只处理单个 `trade_date`
- 连续多天失败后，下一次运行仍只补最新 1 天
- 中间交易日缺口需要人工逐天回填

## 2. 设计目标

- 保持 job 与 schedule 名称不变
- 不新增新的 backfill job
- 仍使用现有每日链路函数，不重写数据同步主体
- 增量语义定义为：
  - 查到最新已完成交易日
  - 读取现有已完成 `gantt_plate_daily.trade_date`
  - 找到最新已完成交易日
  - 从该日期的下一交易日开始补到最新已完成交易日
  - 若已追平最新已完成交易日，则直接 no-op

## 3. 缺口判定策略

### 3.1 为什么以 `gantt_plate_daily` 为准

- 它是 Gantt 主链路最终结果的一部分
- `plate_reason_daily`、`gantt_stock_daily`、`shouban30_*` 都是围绕同一日度链路生成
- 如果某天 `gantt_plate_daily` 不存在，就可以视为该日主链路未完成

### 3.2 目标窗口

- 最新目标日：
  - 若当天是交易日且当前时间 `>= 15:05`，取当天
  - 否则取最近一个更早的交易日
- 已完成集合：`gantt_plate_daily.distinct("trade_date")`
- 最新已完成日：已完成集合中的最大值
- 待补集合：交易日历中 `(latest_completed_trade_date, latest_trade_date]` 的连续交易日

### 3.3 执行起点

- 不从“所有历史第一天”开始全量重扫
- 只从“最新已完成交易日的下一天”开始到最新已完成交易日
- 如果当前没有任何已完成日，则退化为只处理最新已完成交易日 1 天
- 这样可以：
  - 正常情况下只补 1 天
  - 多天失败时自动补连续缺口
  - 避免空库时误扫多年历史
  - 不把“任意历史空洞修复”混入日常增量任务

## 4. 执行流程

### 4.1 新增辅助函数

建议在 [ops/gantt.py](/D:/fqpack/freshquant-2026.2.23/morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py) 新增：

- `resolve_gantt_backfill_trade_dates()`
  - 输出待补交易日列表
- `run_gantt_pipeline_for_date(trade_date)`
  - 串行执行当日完整链路

### 4.2 Job 调整方式

不建议继续让 5 个 Dagster `@op` 逐个拼成“只传一个字符串”的图。

推荐改法：

- 保留 `job_gantt_postclose` 名称
- 在一个顶层 op 里完成：
  - 解析待补日期列表
  - 逐日执行完整链路
  - 打日志汇总

原因：

- Dagster graph 对“动态长度的交易日列表”表达不自然
- 当前链路本身就是顺序依赖，不值得为了回填做复杂 dynamic mapping
- 用 1 个顶层 op 更容易表达“失败停在某天”

## 5. 失败语义

- 每个交易日内仍保持现有顺序：
  - XGB
  - JYGS
  - plate_reason
  - gantt
  - shouban30
- 某天任一步失败：
  - 当前 run 失败
  - 当天后续步骤停止
  - 后续日期不执行
  - 之前已成功日期保留

这是故意设计，不做自动跳过。

## 6. 日志与可观测性

建议日志至少包含：

- 最新已完成目标交易日
- 最新已完成 Gantt 交易日
- 待补日期数量
- 待补起止日期
- 每个交易日的开始和完成
- 最终成功天数

这样运维在 Dagster UI 中能直接看出：

- 是正常单日增量
- 还是一次多日补齐
- 失败停在了哪一天

## 7. 测试策略

### 7.1 单元测试

新增或补充测试覆盖：

- 无缺口时返回空列表或 no-op
- 缺失 1 天时返回该 1 天
- 缺失多天时返回从最新已完成交易日的下一天到最新目标交易日的连续列表
- 某天失败时停止执行后续日期

### 7.2 导入测试

保持 [test_gantt_dagster_import.py](/D:/fqpack/freshquant-2026.2.23/freshquant/tests/test_gantt_dagster_import.py) 可导入。

### 7.3 真实环境验证

在并行 Docker 环境中验证：

- 正常运行态能解析 `latest_trade_date`
- 已追平时 `pending=[]`
- `run_gantt_backfill()` 可正确 no-op

## 8. 风险与折中

- 折中 1：增量起点只看“最新已完成交易日”
  - 优点：符合“增量同步”语义，避免误扫多年历史
  - 缺点：不能自动修复更早的内部历史空洞
- 折中 2：一次 run 内顺序补齐所有缺口
  - 优点：恢复后自动自愈
  - 缺点：耗时会比单日 run 更长
- 折中 3：失败停在首个异常日
  - 优点：错误暴露清晰
  - 缺点：后续日期要等下次 run

这个折中符合当前项目阶段，不引入新的状态机和复杂调度。
