# Daily Screening 筛选工作台优化 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `daily-screening` 的缠论涨幅改成 `1d` 口径，完成 `CLS` 中文分组、分组级提示、自动查询和宽度重分配，并同步更新 `/gantt/shouban30` 的提示语义。

**Architecture:** 后端只调整共享 `Shouban30` 缠论涨幅的真实周期与相关测试，继续保留现有 membership 结构。前端在 `dailyScreeningPage.mjs` 中新增 `CLS` 分组映射、中文名映射和“日线缠论涨幅”总按钮语义，在 `DailyScreening.vue` 中重组筛选区、去掉显式查询按钮、改成自动查询并调整三栏布局；`/gantt/shouban30` 只补 `1d` 语义提示，不重做其筛选架构。

**Tech Stack:** Python 3.12、Vue 3、Element Plus、Node 内置测试、Playwright、Mongo 读模型、Dagster 预计算结果。

---

### Task 1: 锁定 `1d` 缠论涨幅后端口径

**Files:**
- Modify: `freshquant/tests/test_gantt_readmodel.py`
- Modify: `freshquant/data/gantt_readmodel.py`

**Step 1: 写失败测试，锁定共享周期和版本文案**

在 `freshquant/tests/test_gantt_readmodel.py` 增加断言，至少覆盖：

```python
from freshquant.data.gantt_readmodel import SHOUBAN30_CHANLUN_PERIOD

def test_shouban30_chanlun_period_defaults_to_daily():
    assert SHOUBAN30_CHANLUN_PERIOD == "1d"
```

并补一条围绕 `_resolve_shouban30_chanlun_result()` 的测试，断言 `get_chanlun_structure()` 被调用时使用 `1d`。

**Step 2: 运行失败测试，确认现状仍是旧口径**

Run:

```bash
py -3.12 -m pytest freshquant/tests/test_gantt_readmodel.py -q
```

Expected: 至少 1 条新测试失败，体现当前仍是 `30m` / `30m_v1`。

**Step 3: 修改共享常量和共享口径实现**

在 `freshquant/data/gantt_readmodel.py` 中最小改动：

```python
SHOUBAN30_CHANLUN_PERIOD = "1d"
SHOUBAN30_CHANLUN_FILTER_VERSION = "1d_v1"
```

保持 `higher_multiple / segment_multiple / bi_gain_percent` 字段名不变。

**Step 4: 运行后端测试，确认口径切换**

Run:

```bash
py -3.12 -m pytest freshquant/tests/test_gantt_readmodel.py -q
```

Expected: 相关 `gantt_readmodel` 测试 PASS。

**Step 5: Commit**

```bash
git add freshquant/data/gantt_readmodel.py freshquant/tests/test_gantt_readmodel.py
git commit -m "refactor: switch shouban30 chanlun filter to 1d"
```

### Task 2: 锁定 `daily-screening` 的 `1d` 快照与 metric 语义

**Files:**
- Modify: `freshquant/tests/test_daily_screening_service.py`
- Modify: `freshquant/daily_screening/service.py`

**Step 1: 写失败测试，锁定 daily-screening 继续复用共享 `1d` 结果**

在 `freshquant/tests/test_daily_screening_service.py` 增加测试，monkeypatch `_resolve_shouban30_chanlun_result()` 或其依赖，断言：

- `build_shouban30_chanlun_metrics()` 仍读取共享结果
- 返回字段仍为 `higher_multiple / segment_multiple / bi_gain_percent / chanlun_reason`
- 不新增独立布尔字段

示例断言：

```python
assert snapshots[0]["higher_multiple"] == 2.4
assert snapshots[0]["segment_multiple"] == 1.9
assert snapshots[0]["bi_gain_percent"] == 18.0
```

**Step 2: 运行失败测试**

Run:

```bash
py -3.12 -m pytest freshquant/tests/test_daily_screening_service.py -q
```

Expected: 新测试先失败，暴露当前 fixture 或版本字段仍旧口径。

**Step 3: 按最小范围修正服务层或测试夹具**

如果服务层已天然复用共享口径，只需把相关 fixture / 断言更新到 `1d_v1` 和新默认认知；不要扩大改动到 membership 结构。

**Step 4: 运行相关服务层测试**

Run:

```bash
py -3.12 -m pytest freshquant/tests/test_daily_screening_service.py freshquant/tests/test_daily_screening_routes.py -q
```

Expected: PASS。

**Step 5: Commit**

```bash
git add freshquant/daily_screening/service.py freshquant/tests/test_daily_screening_service.py freshquant/tests/test_daily_screening_routes.py
git commit -m "test: lock daily screening shouban30 metrics to 1d semantics"
```

### Task 3: 先写前端状态层失败测试，覆盖 CLS 分组和总按钮语义

**Files:**
- Modify: `morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs`
- Modify: `morningglory/fqwebui/src/views/dailyScreeningPage.mjs`

**Step 1: 写失败测试，覆盖 CLS 五分组和中文名**

至少新增测试覆盖：

- 五个分组名称和组内模型映射
- `01-12` 对应中文名
- 组内取并集后展开为真实 `cls:*` 条件键

示例断言：

```js
assert.deepEqual(expandClsGroup('group_ermai'), [
  'cls:S0001',
  'cls:S0002',
  'cls:S0003',
  'cls:S0005',
])
```

**Step 2: 写失败测试，覆盖“日线缠论涨幅”总按钮语义**

至少断言：

- 默认值是 `3 / 2 / 20`
- 默认不选中，不输出 `metric_filters`
- 选中后一次性输出：

```js
{
  higher_multiple_lte: 3,
  segment_multiple_lte: 2,
  bi_gain_percent_lte: 20,
}
```

**Step 3: 运行失败测试**

Run:

```bash
node --test morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs
```

Expected: 新增断言失败。

**Step 4: 在状态层实现最小映射与 payload 逻辑**

在 `morningglory/fqwebui/src/views/dailyScreeningPage.mjs` 中新增：

- `CLS` 分组常量
- `CLS` 中文模型名映射
- 分组展开函数
- “日线缠论涨幅”总按钮状态与默认阈值
- 仅在总按钮选中时生成 `metric_filters`

避免在这里掺入组件层 `watch` 或 DOM 逻辑。

**Step 5: 运行状态层测试**

Run:

```bash
node --test morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs
```

Expected: PASS。

**Step 6: Commit**

```bash
git add morningglory/fqwebui/src/views/dailyScreeningPage.mjs morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs
git commit -m "feat: add grouped cls and daily chanlun state model"
```

### Task 4: 先写组件失败测试，再改 `daily-screening` 结构与自动查询

**Files:**
- Modify: `morningglory/fqwebui/src/views/DailyScreening.vue`
- Modify: `morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs`
- Modify: `morningglory/fqwebui/tests/daily-screening.browser.spec.mjs`

**Step 1: 写失败测试，锁定组件结构变化**

在现有前端测试中补断言：

- 页面不再出现“查询结果”按钮
- `CLS` 区块显示五个中文分组
- “日线缠论涨幅”区块显示总按钮和默认 `3 / 2 / 20`
- `全部加入 pre_pools` 出现在交集列表左侧
- 中、右列平分剩余宽度

必要时读取 `.vue` 源文件做静态断言；不要先改实现。

**Step 2: 写 browser 失败测试，锁定自动查询和布局**

在 `morningglory/fqwebui/tests/daily-screening.browser.spec.mjs` 增加覆盖：

- 页面首次进入即有结果，不需要再点“查询结果”
- 点击条件后结果会刷新
- 左侧筛选仍可滚动
- 中、右列宽度接近 `1:1`

**Step 3: 运行失败测试**

Run:

```bash
node --test morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs
npx playwright test tests/daily-screening.browser.spec.mjs --reporter=line
```

Expected: 新增断言失败。

**Step 4: 改 `DailyScreening.vue`，完成筛选区和自动查询**

按最小改动实现：

- 去掉按钮级 `?` 提示，改成分组表头悬浮说明
- `CLS` 改成 5 组中文按钮
- `日线缠论涨幅` 改成总按钮 + 3 个输入框
- 移除“查询结果”按钮
- 用 `watch` 或等价逻辑在条件变化时自动调用查询
- 对输入框更新加短防抖
- 交集列表头左侧放 `全部加入 pre_pools`

**Step 5: 改三栏布局**

只改必要 CSS：

- 左侧固定宽度
- 中间列和右侧列平分剩余空间
- 保持左侧独立滚动

**Step 6: 运行前端测试**

Run:

```bash
node --test morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs morningglory/fqwebui/src/views/runtime-observability.test.mjs
npx playwright test tests/daily-screening.browser.spec.mjs --reporter=line
```

Expected: PASS。

**Step 7: Commit**

```bash
git add morningglory/fqwebui/src/views/DailyScreening.vue morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs morningglory/fqwebui/tests/daily-screening.browser.spec.mjs
git commit -m "feat: polish daily screening filters and auto query"
```

### Task 5: 同步 `/gantt/shouban30` 的 `1d` 提示语义

**Files:**
- Modify: `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`
- Modify: `morningglory/fqwebui/src/views/shouban30ChanlunFilter.mjs`
- Modify: `morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs`

**Step 1: 写失败测试，锁定文案和默认值**

补测试覆盖：

- 默认口径提示明确写出 `1d`
- `passesDefaultChanlunFilter()` 的默认阈值逻辑改为 `3 / 2 / 20`
- 页面提示不再暗示旧 `30m`

**Step 2: 运行失败测试**

Run:

```bash
node --test morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs
```

Expected: 失败，体现当前默认阈值和说明仍是旧语义。

**Step 3: 修改 helper 与页面提示**

在 `shouban30ChanlunFilter.mjs` 中把默认逻辑改为：

```js
if (segmentMultiple > 2.0) {
  result.reason = 'segment_multiple_exceed'
  return result
}
if (biGainPercent > 20) {
  result.reason = 'bi_gain_exceed'
  return result
}
```

并在 `GanttShouban30Phase1.vue` 中补充“当前缠论涨幅默认基于日线 1d 结构计算”的提示。

**Step 4: 运行相关前端测试**

Run:

```bash
node --test morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs
```

Expected: PASS。

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/GanttShouban30Phase1.vue morningglory/fqwebui/src/views/shouban30ChanlunFilter.mjs morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs
git commit -m "feat: update shouban30 chanlun hints to daily semantics"
```

### Task 6: 同步当前态文档

**Files:**
- Modify: `docs/current/modules/daily-screening.md`
- Modify: `docs/current/modules/gantt-shouban30.md` 或实际对应的 `/gantt/shouban30` 当前模块文档
- Modify: 其他被 docs guard 命中的当前态文档（如有）

**Step 1: 写文档补丁**

至少写清：

- `daily-screening` 的 `日线缠论涨幅` 真实周期为 `1d`
- 默认阈值为 `3 / 2 / 20`，但默认不选中
- `CLS` 改成五个中文分组，组内取并集
- 页面查询改为自动触发
- `全部加入 pre_pools` 在交集列表左侧
- `/gantt/shouban30` 的缠论涨幅提示也已切到 `1d`

**Step 2: 运行 docs guard**

Run:

```bash
@'
import subprocess, json
files = subprocess.check_output(['git','diff','--name-only','origin/main...HEAD'], text=True).splitlines()
cmd = ['py','-3.12','script/ci/check_current_docs.py','--changed-files-json', json.dumps(files, ensure_ascii=False)]
raise SystemExit(subprocess.call(cmd))
'@ | py -3.12 -
```

Expected: `docs-current-guard: OK`

**Step 3: Commit**

```bash
git add docs/current/modules/daily-screening.md docs/current/modules/gantt-shouban30.md
git commit -m "docs: update daily screening and shouban30 current behavior"
```

### Task 7: 收口验证

**Files:**
- No code changes expected

**Step 1: 运行后端相关测试**

Run:

```bash
py -3.12 -m pytest freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_daily_screening_service.py freshquant/tests/test_daily_screening_routes.py -q
```

Expected: PASS

**Step 2: 运行前端相关测试**

Run:

```bash
node --test morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs morningglory/fqwebui/src/views/runtime-observability.test.mjs morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs
npx playwright test tests/daily-screening.browser.spec.mjs --reporter=line
```

Expected: PASS

**Step 3: 构建前端**

Run:

```bash
pnpm --dir morningglory/fqwebui run build
```

Expected: build 成功

**Step 4: Commit（仅当验证过程中需要补丁）**

```bash
git add <fixed-files>
git commit -m "fix: address verification feedback for daily screening polish"
```

### Task 8: 准备交付

**Files:**
- No code changes expected

**Step 1: 检查工作树状态**

Run:

```bash
git status --short
```

Expected: 干净

**Step 2: 推送分支并开 PR**

Run:

```bash
git push -u origin codex/daily-screening-filter-polish-20260319
gh pr create --fill
```

Expected: 分支已推送，PR 已创建

**Step 3: 记录部署影响**

PR 描述中明确：

- 需要重建 `fq_webui`
- 若共享 `Shouban30` 读模型快照语义变化影响 UI 验证，必要时重跑相关 Dagster / 读模型任务

