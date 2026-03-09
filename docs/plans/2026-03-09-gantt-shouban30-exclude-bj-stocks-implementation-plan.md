# Gantt Shouban30 排除北交所标的 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 `/gantt/shouban30` 的盘后快照构建期彻底排除北交所标的，并让板块与统计值基于过滤后的候选集重新计算。

**Architecture:** 在 `gantt_readmodel.py` 的 `persist_shouban30_for_date()` 中新增纯函数判断北交所代码，并在构建 `shouban30_stocks` 前过滤。随后用过滤后的 stock rows 生成 plate rows，不保留空板块。

**Tech Stack:** Python 3.12, pytest, Dagster, MongoDB

---

### Task 1: 补失败测试覆盖北交所排除语义

**Files:**
- Modify: `freshquant/tests/test_gantt_readmodel.py`

**Step 1: Write the failing test**

- 为读模型新增一个最小用例：
  - 某板块只包含 `920001`
  - 另一个板块同时包含 `000001` 与 `920001`
  - 期望 `920001` 不出现在 `shouban30_stocks`
  - 仅含 `920001` 的板块不进入 `shouban30_plates`

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_readmodel.py -q`

Expected: FAIL，显示北交所代码仍然被写入快照。

**Step 3: Commit**

- 暂不提交，继续 Task 2。

### Task 2: 在读模型构建层过滤北交所标的

**Files:**
- Modify: `freshquant/data/gantt_readmodel.py`

**Step 1: Write minimal implementation**

- 新增纯函数，例如 `_is_shouban30_excluded_stock_code(code6)`。
- 对 `43/83/87/92` 开头的 6 位代码返回 `True`。
- 在 `persist_shouban30_for_date()` 构建 stock rows 前过滤。
- 保证 plate rows 基于过滤后的 stock rows 重新聚合。

**Step 2: Run targeted test**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_readmodel.py -q`

Expected: PASS。

### Task 3: 运行相邻回归

**Files:**
- Test: `freshquant/tests/test_gantt_routes.py`
- Test: `freshquant/tests/test_gantt_dagster_ops.py`

**Step 1: Run tests**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py freshquant/tests/test_gantt_dagster_ops.py -q`

Expected: PASS。

### Task 4: 更新治理文档

**Files:**
- Create: `docs/rfcs/0025-gantt-shouban30-exclude-bj-stocks.md`
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`

**Step 1: Update docs**

- 新增 RFC 0025。
- 在 `progress.md` 追加 0025 行，状态写 `Implementing`。
- 在落地提交中追加 breaking change 记录。

### Task 5: 重建运行态快照并人工验证

**Files:**
- Runtime only

**Step 1: Rebuild services**

Run: `docker compose -f docker/compose.parallel.yaml up -d --build fq_apiserver fq_tdxhq fq_dagster_webserver fq_dagster_daemon fq_qawebserver`

**Step 2: Rebuild latest shouban30 snapshots**

Run container-side `_build_shouban30_snapshots_for_date(..., '2026-03-09')`

**Step 3: Verify Mongo and API**

- `shouban30_stocks` 中不再出现 `920xxx`
- `shouban30_plates` 中不再出现过滤后为空的板块
- `/api/gantt/shouban30/plates|stocks` 不返回北交所标的

### Task 6: Commit

**Step 1: Commit**

```bash
git add docs/rfcs/0025-gantt-shouban30-exclude-bj-stocks.md docs/plans/2026-03-09-gantt-shouban30-exclude-bj-stocks-design.md docs/plans/2026-03-09-gantt-shouban30-exclude-bj-stocks-implementation-plan.md docs/migration/progress.md docs/migration/breaking-changes.md freshquant/data/gantt_readmodel.py freshquant/tests/test_gantt_readmodel.py
git commit -m "fix: 排除 shouban30 北交所标的"
```
