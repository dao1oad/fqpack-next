# Gantt Postclose Incremental Backfill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 `job_gantt_postclose` 从单日处理改成缺口增量回填，自动从最新已完成交易日的下一天补到按交易日历和盘后截止时间解析出的最新已完成交易日。

**Architecture:** 保持现有 Dagster job/schedule 名称不变，在 `ops/gantt.py` 中新增增量交易日列表解析与逐日执行辅助函数，再让 `job_gantt_postclose` 通过单一顶层 op 串行驱动完整每日链路。增量起点以 `gantt_plate_daily.trade_date` 的最新已完成日为准，目标终点按交易日历和 `15:05` 截止时间解析，不新增新的 job 或数据库表。

**Tech Stack:** Dagster, PyMongo, pytest, akshare trading calendar

---

### Task 1: 补治理文档

**Files:**
- Create: `docs/rfcs/0012-gantt-postclose-incremental-backfill.md`
- Create: `docs/plans/2026-03-07-gantt-postclose-incremental-backfill-design.md`
- Create: `docs/plans/2026-03-07-gantt-postclose-incremental-backfill-implementation-plan.md`
- Modify: `docs/migration/progress.md`

**Step 1: 写 RFC、设计稿和实施计划**

- 明确只改 `job_gantt_postclose`
- 明确增量起点以 `gantt_plate_daily` 的最新已完成日为准
- 明确失败停在首个异常日

**Step 2: 更新 progress**

- 新增 RFC 0012 行，状态先标 `Implementing`

**Step 3: 检查文档差异**

Run: `git diff -- docs/rfcs/0012-gantt-postclose-incremental-backfill.md docs/plans/2026-03-07-gantt-postclose-incremental-backfill-design.md docs/plans/2026-03-07-gantt-postclose-incremental-backfill-implementation-plan.md docs/migration/progress.md`

Expected: 只出现本 RFC 相关文档变更

### Task 2: 先写缺口解析失败测试

**Files:**
- Modify: `freshquant/tests/test_gantt_dagster_import.py`
- Create or Modify: `freshquant/tests/test_gantt_dagster_ops.py`

**Step 1: 写缺口交易日列表测试**

```python
def test_resolve_gantt_backfill_trade_dates_returns_missing_window(monkeypatch):
    from fqdagster.defs.ops import gantt as ops

    monkeypatch.setattr(ops, "_query_latest_trade_date", lambda: "2026-03-06")
    monkeypatch.setattr(ops, "_query_latest_completed_gantt_trade_date", lambda: "2026-03-03")
    monkeypatch.setattr(
        ops,
        "_query_trade_dates_between",
        lambda end_date: ["2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06"],
    )

    assert ops.resolve_gantt_backfill_trade_dates() == ["2026-03-04", "2026-03-05", "2026-03-06"]
```

**Step 2: 写“无缺口”测试**

```python
def test_resolve_gantt_backfill_trade_dates_returns_empty_when_no_gap(monkeypatch):
    ...
    assert ops.resolve_gantt_backfill_trade_dates() == []
```

**Step 3: 运行测试确认失败**

Run: `py -m pytest freshquant/tests/test_gantt_dagster_ops.py -q`

Expected: FAIL，提示函数不存在或行为不符合预期

### Task 3: 写逐日执行失败测试

**Files:**
- Modify: `freshquant/tests/test_gantt_dagster_ops.py`

**Step 1: 写逐日执行顺序测试**

```python
def test_run_gantt_backfill_executes_each_trade_date_in_order(monkeypatch):
    calls = []
    ...
    assert calls == [
        ("xgb", "2026-03-04"),
        ("jygs", "2026-03-04"),
        ("plate_reason", "2026-03-04"),
        ("gantt", "2026-03-04"),
        ("shouban30", "2026-03-04"),
        ("xgb", "2026-03-05"),
        ...
    ]
```

**Step 2: 写“中途失败即停止”测试**

```python
def test_run_gantt_backfill_stops_on_first_failed_trade_date(monkeypatch):
    ...
    with pytest.raises(RuntimeError, match="boom"):
        ops.run_gantt_backfill(context)
    assert calls == [...]
```

**Step 3: 运行测试确认失败**

Run: `py -m pytest freshquant/tests/test_gantt_dagster_ops.py -q`

Expected: FAIL，提示辅助函数不存在

### Task 4: 实现缺口交易日解析

**Files:**
- Modify: `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`

**Step 1: 实现最小辅助函数**

- `_query_latest_trade_date()`
- `_query_trade_dates_between(start_date, end_date)`
- `_query_latest_completed_gantt_trade_date()`
- `resolve_gantt_backfill_trade_dates()`

**Step 2: 仅实现让 Task 2 测试通过的最小逻辑**

- 从最新已完成交易日的下一交易日开始构造增量列表
- 无缺口返回空列表

**Step 3: 运行测试**

Run: `py -m pytest freshquant/tests/test_gantt_dagster_ops.py -k resolve -q`

Expected: PASS

### Task 5: 实现逐日回填执行器与顶层 Dagster op

**Files:**
- Modify: `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`
- Modify: `morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py`

**Step 1: 实现逐日执行器**

- `run_gantt_pipeline_for_date(trade_date)`
- `run_gantt_backfill(context)`

**Step 2: 新增顶层 op**

- `op_run_gantt_postclose_incremental(context)`

**Step 3: 修改 job**

- `job_gantt_postclose` 只调用顶层 op
- 保持 job 名称不变

**Step 4: 运行测试**

Run: `py -m pytest freshquant/tests/test_gantt_dagster_ops.py -q`

Expected: PASS

### Task 6: 保持导入测试与旧 schedule 不坏

**Files:**
- Modify: `freshquant/tests/test_gantt_dagster_import.py`

**Step 1: 更新导入断言**

- 断言新的顶层 op 存在
- 断言 `job_gantt_postclose`、`gantt_postclose_schedule` 仍存在

**Step 2: 运行测试**

Run: `py -m pytest freshquant/tests/test_gantt_dagster_import.py -q`

Expected: PASS

### Task 7: 真实环境验证

**Files:**
- None

**Step 1: 运行相关测试**

Run: `py -m pytest freshquant/tests/test_gantt_source_xgb.py freshquant/tests/test_gantt_dagster_ops.py freshquant/tests/test_gantt_dagster_import.py freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py -q`

Expected: PASS

**Step 2: 重建 Dagster 服务**

Run: `docker compose -f docker/compose.parallel.yaml up -d --build fq_dagster_daemon fq_dagster_webserver`

Expected: 容器成功启动

**Step 3: 在容器内抽样验证运行态**

Run: `docker exec fqnext_20260223-fq_dagster_daemon-1 python -c "..."`

Expected: 能解析 `latest_trade_date`、`latest_completed_trade_date`、`pending`，并在无缺口时成功 no-op

### Task 8: 收尾文档

**Files:**
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`
- Modify: `docs/rfcs/0012-gantt-postclose-incremental-backfill.md`

**Step 1: 更新 RFC 状态**

- `Approved -> Done` 或按实际进展更新

**Step 2: 更新 progress 备注**

- 写清“已从单日语义改为缺口回填”

**Step 3: 记录 breaking change**

- 写清 `job_gantt_postclose` 行为语义变化

**Step 4: 检查最终差异**

Run: `git diff -- docs/migration/progress.md docs/migration/breaking-changes.md docs/rfcs/0012-gantt-postclose-incremental-backfill.md`

Expected: 文档与实现一致
