# Gantt / Shouban30 Post-Close Read Model Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在目标仓库落地 XGB / JYGS / Gantt / Shouban30 的盘后同步与标准化读模型，全部数据写入独立 MongoDB 分库 `freshquant_gantt`，并提供最小查询 API。

**Architecture:** 采用“两层数据模型”方案：Dagster 先同步 XGB / JYGS 原始数据到 `freshquant_gantt`，再构建 `plate_reason_daily`、`gantt_*`、`shouban30_*` 读模型。HTTP API 只查询读模型，不再直接扫原始表。板块理由是严格主数据，缺失即构建失败，不做 fallback。

**Tech Stack:** Dynaconf、PyMongo、Flask、Dagster、pytest。

---

### Task 1: 配置与分库接入

**Files:**
- Modify: `freshquant/db.py`
- Modify: `freshquant/freshquant.yaml`
- Modify: `docs/agent/配置管理指南.md`
- Test: `freshquant/tests/test_gantt_db_config.py`

**Step 1: Write the failing test**

写一个配置测试，断言在设置 `mongodb.gantt_db` 后，代码能返回 `freshquant_gantt` 对应数据库句柄。

```python
def test_get_gantt_db_uses_mongodb_gantt_db_setting(monkeypatch):
    ...
```

**Step 2: Run test to verify it fails**

Run: `pytest freshquant/tests/test_gantt_db_config.py -q`

Expected: FAIL because `DBGantt` or equivalent helper does not exist yet.

**Step 3: Write minimal implementation**

- 在 `freshquant/db.py` 中新增 `DBGantt`
- 默认从 `settings.get("mongodb", {}).get("gantt_db", "freshquant_gantt")` 读取库名
- 在 `freshquant/freshquant.yaml` 增加 `mongodb.gantt_db`
- 在配置文档补充该配置项

**Step 4: Run test to verify it passes**

Run: `pytest freshquant/tests/test_gantt_db_config.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/db.py freshquant/freshquant.yaml docs/agent/配置管理指南.md freshquant/tests/test_gantt_db_config.py
git commit -m "feat: add gantt mongodb database config"
```

### Task 2: 原始同步层抽取与纯函数测试

**Files:**
- Create: `freshquant/data/gantt_source_xgb.py`
- Create: `freshquant/data/gantt_source_jygs.py`
- Test: `freshquant/tests/test_gantt_source_xgb.py`
- Test: `freshquant/tests/test_gantt_source_jygs.py`

**Step 1: Write the failing tests**

先覆盖不依赖网络的纯函数：

```python
def test_xgb_history_row_keeps_plate_description_as_reason_source(): ...
def test_jygs_board_key_is_derived_from_board_name_not_action_field_id(): ...
def test_jygs_action_reason_is_required_when_board_is_present(): ...
```

**Step 2: Run tests to verify they fail**

Run: `pytest freshquant/tests/test_gantt_source_xgb.py freshquant/tests/test_gantt_source_jygs.py -q`

Expected: FAIL because source normalization helpers do not exist yet.

**Step 3: Write minimal implementation**

- 从旧分支迁移并裁剪 XGB 历史同步逻辑，只保留 `xgb_top_gainer_history`
- 从旧分支迁移并裁剪 JYGS action 同步逻辑，只保留 `jygs_yidong` 与 `jygs_action_fields`
- 输出集合全部写入 `DBGantt`
- 保证 JYGS 使用归一化后的 `board_key`

**Step 4: Run tests to verify they pass**

Run: `pytest freshquant/tests/test_gantt_source_xgb.py freshquant/tests/test_gantt_source_jygs.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/data/gantt_source_xgb.py freshquant/data/gantt_source_jygs.py freshquant/tests/test_gantt_source_xgb.py freshquant/tests/test_gantt_source_jygs.py
git commit -m "feat: add gantt raw source sync helpers"
```

### Task 3: 读模型构建器与“无 fallback”约束

**Files:**
- Create: `freshquant/data/gantt_readmodel.py`
- Test: `freshquant/tests/test_gantt_readmodel.py`

**Step 1: Write the failing tests**

覆盖 4 个关键语义：

```python
def test_build_plate_reason_daily_uses_xgb_description(): ...
def test_build_plate_reason_daily_uses_jygs_action_reason(): ...
def test_build_plate_reason_daily_fails_when_reason_missing(): ...
def test_build_shouban30_joins_reason_from_plate_reason_daily_only(): ...
```

**Step 2: Run tests to verify they fail**

Run: `pytest freshquant/tests/test_gantt_readmodel.py -q`

Expected: FAIL because read model builder does not exist yet.

**Step 3: Write minimal implementation**

- 产出 `plate_reason_daily`
- 产出 `gantt_plate_daily`
- 产出 `gantt_stock_daily`
- 产出 `shouban30_plates`
- 产出 `shouban30_stocks`
- 为所有集合建立唯一索引
- 缺失板块理由时直接抛错，不生成下游结果

**Step 4: Run tests to verify they pass**

Run: `pytest freshquant/tests/test_gantt_readmodel.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/data/gantt_readmodel.py freshquant/tests/test_gantt_readmodel.py
git commit -m "feat: add gantt post-close read models"
```

### Task 4: Dagster 盘后任务链路

**Files:**
- Create: `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`
- Create: `morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py`
- Create: `morningglory/fqdagster/src/fqdagster/defs/schedules/gantt.py`
- Modify: `docs/migration/progress.md`

**Step 1: Write a smoke test or import test**

如果当前仓库没有 Dagster 测试基线，至少写导入级测试：

```python
def test_gantt_job_imports(): ...
```

文件建议：`freshquant/tests/test_gantt_dagster_import.py`

**Step 2: Run test to verify it fails**

Run: `pytest freshquant/tests/test_gantt_dagster_import.py -q`

Expected: FAIL because gantt Dagster modules do not exist yet.

**Step 3: Write minimal implementation**

- `op_sync_xgb_history_daily`
- `op_sync_jygs_action_daily`
- `op_build_plate_reason_daily`
- `op_build_gantt_daily`
- `op_build_shouban30_daily`
- 组合成一个盘后 job
- 增加 schedule，时间放在现有收盘任务之后

**Step 4: Run test to verify it passes**

Run: `pytest freshquant/tests/test_gantt_dagster_import.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py morningglory/fqdagster/src/fqdagster/defs/schedules/gantt.py freshquant/tests/test_gantt_dagster_import.py docs/migration/progress.md
git commit -m "feat: add gantt post-close dagster pipeline"
```

### Task 5: 最小查询 API

**Files:**
- Create: `freshquant/rear/gantt/routes.py`
- Create: `freshquant/rear/gantt/__init__.py`
- Modify: `freshquant/rear/api_server.py`
- Test: `freshquant/tests/test_gantt_routes.py`

**Step 1: Write the failing tests**

```python
def test_get_gantt_plates_reads_readmodel_collection(...): ...
def test_get_gantt_stocks_requires_plate_key(...): ...
def test_get_shouban30_plates_reads_as_of_date(...): ...
def test_get_shouban30_stocks_returns_404_or_empty_when_missing(...): ...
```

**Step 2: Run tests to verify they fail**

Run: `pytest freshquant/tests/test_gantt_routes.py -q`

Expected: FAIL because routes are not registered yet.

**Step 3: Write minimal implementation**

- 新增 `/api/gantt/plates`
- 新增 `/api/gantt/stocks`
- 新增 `/api/gantt/shouban30/plates`
- 新增 `/api/gantt/shouban30/stocks`
- 在 `api_server.py` 注册 `gantt_bp`

**Step 4: Run tests to verify they pass**

Run: `pytest freshquant/tests/test_gantt_routes.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/rear/gantt/routes.py freshquant/rear/gantt/__init__.py freshquant/rear/api_server.py freshquant/tests/test_gantt_routes.py
git commit -m "feat: add gantt readmodel api routes"
```

### Task 6: 全链路验证与治理收尾

**Files:**
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`

**Step 1: Run targeted tests**

Run: `pytest freshquant/tests/test_gantt_db_config.py freshquant/tests/test_gantt_source_xgb.py freshquant/tests/test_gantt_source_jygs.py freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_dagster_import.py freshquant/tests/test_gantt_routes.py -q`

Expected: PASS

**Step 2: Run broader unit suite**

Run: `pytest freshquant/tests -q`

Expected: PASS or only pre-existing unrelated failures.

**Step 3: Update governance docs**

- `progress.md`：将 `0006` 从 `Draft` 逐步更新到 `Approved / Implementing / Done`
- `breaking-changes.md`：记录新接口面与新分库的影响

**Step 4: Commit**

```bash
git add docs/migration/progress.md docs/migration/breaking-changes.md
git commit -m "docs: finalize gantt post-close migration records"
```
