# Subject Management Unified Page Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 新增一个标的管理统一页，用高密度表格展示标的配置摘要，并在右栏集中编辑 `must_pool`、Guardian 阶梯价、止盈三层和 buy lot 止损。

**Architecture:** 后端新增 `subject_management` 聚合读模型与轻量写入口，统一收口 `must_pool / guardian_buy_grid / takeprofit / stoploss / 运行态摘要`。前端新增 `/subject-management` 工作台页面，左侧复用 `/gantt/shouban30` 的高密度表格语言展示配置摘要，右侧分区编辑单标的真值，账户级仓位门禁只读联动展示。

**Tech Stack:** Flask Blueprint、Python service layer、Mongo read model assembly、Vue 3、Element Plus、Node test runner、Vite

---

### Task 1: 补后端聚合读模型测试

**Files:**
- Create: `freshquant/tests/test_subject_management_service.py`
- Modify: `freshquant/tests/conftest.py`（仅当需要共享 fake repository helper）
- Test: `freshquant/tests/test_subject_management_service.py`

**Step 1: Write the failing test**

在 `freshquant/tests/test_subject_management_service.py` 新增测试，锁定 `overview` 和 `detail` 的聚合结构：

```python
def test_subject_management_overview_aggregates_must_pool_guardian_takeprofit_stoploss():
    service = SubjectManagementDashboardService(
        must_pool_repo=FakeMustPoolRepo([...]),
        guardian_repo=FakeGuardianRepo(...),
        tpsl_repo=FakeTpslRepo(...),
        order_repo=FakeOrderRepo(...),
        position_loader=lambda: [...],
        pm_summary_loader=lambda: {"effective_state": "HOLDING_ONLY"},
    )

    rows = service.get_overview()

    assert rows[0]["symbol"] == "600000"
    assert rows[0]["must_pool"]["lot_amount"] == 50000
    assert rows[0]["guardian"]["buy_1"] == 10.2
    assert rows[0]["takeprofit"]["tiers"][0]["level"] == 1
    assert rows[0]["stoploss"]["active_count"] == 2
```

再补 `get_detail()` 测试，断言返回：

- `must_pool`
- `guardian_buy_grid_config`
- `guardian_buy_grid_state`
- `takeprofit`
- `buy_lots`
- `runtime_summary`
- `position_management_summary`

**Step 2: Run test to verify it fails**

Run: `pytest freshquant/tests/test_subject_management_service.py -q`
Expected: FAIL，提示 `SubjectManagementDashboardService` 或相关聚合结构尚不存在。

**Step 3: Write minimal implementation**

先创建最小服务文件：

- `freshquant/subject_management/dashboard_service.py`

最小实现只做：

- 归一 `symbol`
- 聚合 `must_pool`
- 读取 Guardian 配置与状态
- 读取止盈三层和 stoploss 摘要
- 拼装 `overview` / `detail`

先不做写能力。

**Step 4: Run test to verify it passes**

Run: `pytest freshquant/tests/test_subject_management_service.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/subject_management/dashboard_service.py freshquant/tests/test_subject_management_service.py
git commit -m "test: lock subject management dashboard aggregation"
```

### Task 2: 补后端路由与写接口

**Files:**
- Create: `freshquant/rear/subject_management/routes.py`
- Create: `freshquant/subject_management/write_service.py`
- Modify: `freshquant/rear/api_server.py`
- Create: `freshquant/tests/test_subject_management_routes.py`
- Test: `freshquant/tests/test_subject_management_routes.py`

**Step 1: Write the failing test**

在 `freshquant/tests/test_subject_management_routes.py` 新增 route 测试：

```python
def test_subject_management_overview_route_returns_rows(monkeypatch):
    class FakeDashboardService:
        def get_overview(self):
            return [{"symbol": "600000", "name": "浦发银行"}]

    monkeypatch.setattr(
        "freshquant.rear.subject_management.routes._get_dashboard_service",
        lambda: FakeDashboardService(),
    )

    client = _make_client()
    response = client.get("/api/subject-management/overview")

    assert response.status_code == 200
    assert response.get_json()["rows"][0]["symbol"] == "600000"
```

再补：

- `GET /api/subject-management/<symbol>`
- `POST /api/subject-management/<symbol>/must-pool`
- `POST /api/subject-management/<symbol>/guardian-buy-grid`

并覆盖校验错误返回 `400`。

**Step 2: Run test to verify it fails**

Run: `pytest freshquant/tests/test_subject_management_routes.py -q`
Expected: FAIL，因为 blueprint 和接口尚不存在。

**Step 3: Write minimal implementation**

最小实现：

- 新建 `subject_management_bp`
- 注册到 `freshquant/rear/api_server.py`
- 写两个读接口：
  - `/api/subject-management/overview`
  - `/api/subject-management/<symbol>`
- 写两个轻量写接口：
  - `/api/subject-management/<symbol>/must-pool`
  - `/api/subject-management/<symbol>/guardian-buy-grid`

`write_service.py` 只负责：

- 校验基础字段
- 调用现有 `must_pool` 更新逻辑
- 调用现有 Guardian config upsert

先不新增批量接口。

**Step 4: Run test to verify it passes**

Run: `pytest freshquant/tests/test_subject_management_routes.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/rear/api_server.py freshquant/rear/subject_management/routes.py freshquant/subject_management/write_service.py freshquant/tests/test_subject_management_routes.py
git commit -m "feat: add subject management api routes"
```

### Task 3: 先锁定前端 view model 和页面控制器

**Files:**
- Create: `morningglory/fqwebui/src/api/subjectManagementApi.js`
- Create: `morningglory/fqwebui/src/views/subjectManagement.mjs`
- Create: `morningglory/fqwebui/src/views/subjectManagementPage.mjs`
- Create: `morningglory/fqwebui/src/views/subjectManagement.test.mjs`
- Create: `morningglory/fqwebui/src/views/subjectManagementPage.test.mjs`
- Test: `morningglory/fqwebui/src/views/subjectManagement.test.mjs`
- Test: `morningglory/fqwebui/src/views/subjectManagementPage.test.mjs`

**Step 1: Write the failing test**

在 `subjectManagement.test.mjs` 锁定左表摘要转换：

```javascript
test('buildOverviewRows keeps dense summary columns and default three takeprofit tiers', () => {
  const rows = buildOverviewRows([
    {
      symbol: '600000',
      name: '浦发银行',
      must_pool: { stop_loss_price: 9.2, initial_lot_amount: 80000, lot_amount: 50000, forever: true },
      guardian: { enabled: true, buy_1: 10.2, buy_2: 9.9, buy_3: 9.5 },
      takeprofit: { tiers: [] },
      stoploss: { active_count: 2, open_buy_lot_count: 5 },
    },
  ])

  assert.equal(rows[0].takeprofitSummary.length, 3)
  assert.equal(rows[0].guardianSummaryLabel.includes('B1'), true)
})
```

在 `subjectManagementPage.test.mjs` 锁定控制器行为：

- 页面初始化先拉 overview 再拉 detail
- 切换行只刷新 detail
- 保存基础设置后刷新当前行
- 默认三层止盈草稿直接出现

**Step 2: Run test to verify it fails**

Run: `node --test src/views/subjectManagement.test.mjs src/views/subjectManagementPage.test.mjs`
Expected: FAIL，因为相关模块尚不存在。

**Step 3: Write minimal implementation**

最小实现：

- `subjectManagementApi.js` 包装新后端接口和复用接口
- `subjectManagement.mjs` 负责：
  - 归一 overview rows
  - 归一 detail view model
  - 生成默认三层止盈草稿
- `subjectManagementPage.mjs` 负责：
  - 加载 overview/detail
  - 选中行切换
  - 分区保存后刷新

先不写 `.vue`，先把可测试状态逻辑锁定。

**Step 4: Run test to verify it passes**

Run: `node --test src/views/subjectManagement.test.mjs src/views/subjectManagementPage.test.mjs`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/api/subjectManagementApi.js morningglory/fqwebui/src/views/subjectManagement.mjs morningglory/fqwebui/src/views/subjectManagementPage.mjs morningglory/fqwebui/src/views/subjectManagement.test.mjs morningglory/fqwebui/src/views/subjectManagementPage.test.mjs
git commit -m "test: lock subject management page state model"
```

### Task 4: 实现前端统一页和导航入口

**Files:**
- Create: `morningglory/fqwebui/src/views/SubjectManagement.vue`
- Modify: `morningglory/fqwebui/src/router/index.js`
- Modify: `morningglory/fqwebui/src/views/MyHeader.vue`
- Modify: `morningglory/fqwebui/src/style/workbench-density.css`（仅当现有密度样式不够）
- Test: `morningglory/fqwebui/src/views/subjectManagement.test.mjs`
- Test: `morningglory/fqwebui/src/views/subjectManagementPage.test.mjs`

**Step 1: Write the failing test**

如果 Task 3 还没有覆盖页面结构约束，追加最小测试，锁定：

- overview rows 必须包含左表各摘要字段
- detail view model 必须包含四个 panel 所需字段
- 默认三层止盈必须始终可见

**Step 2: Run test to verify it fails**

Run: `node --test src/views/subjectManagement.test.mjs src/views/subjectManagementPage.test.mjs`
Expected: FAIL，说明页面实现前的数据结构仍有缺口。

**Step 3: Write minimal implementation**

在 `SubjectManagement.vue` 实现：

- 顶部紧凑 toolbar
- 左侧高密度 `el-table`
- 右侧四个 panel
- 左表展示：
  - 基础摘要
  - Guardian 摘要
  - 止盈三层摘要
  - 止损摘要
  - 运行态摘要
- 右栏实现：
  - `must_pool` 编辑
  - Guardian 编辑
  - 止盈三层固定表
  - buy lot 止损表
  - 只读运行态

同时：

- 在 `router/index.js` 注册 `/subject-management`
- 在 `MyHeader.vue` 增加页面入口按钮

**Step 4: Run test to verify it passes**

Run: `node --test src/views/subjectManagement.test.mjs src/views/subjectManagementPage.test.mjs`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/SubjectManagement.vue morningglory/fqwebui/src/router/index.js morningglory/fqwebui/src/views/MyHeader.vue morningglory/fqwebui/src/api/subjectManagementApi.js morningglory/fqwebui/src/views/subjectManagement.mjs morningglory/fqwebui/src/views/subjectManagementPage.mjs morningglory/fqwebui/src/views/subjectManagement.test.mjs morningglory/fqwebui/src/views/subjectManagementPage.test.mjs
git commit -m "feat: add subject management workbench page"
```

### Task 5: 同步当前文档并做完整验证

**Files:**
- Modify: `docs/current/interfaces.md`
- Modify: `docs/current/modules/kline-webui.md`
- Modify: `docs/current/overview.md`（仅当页面入口需要补充）
- Test: `freshquant/tests/test_subject_management_service.py`
- Test: `freshquant/tests/test_subject_management_routes.py`
- Test: `morningglory/fqwebui/src/views/subjectManagement.test.mjs`
- Test: `morningglory/fqwebui/src/views/subjectManagementPage.test.mjs`

**Step 1: Write the failing test**

本任务不新增代码测试，直接做全量验证与文档同步。

**Step 2: Run test to verify it fails**

Run: `pytest freshquant/tests/test_subject_management_service.py freshquant/tests/test_subject_management_routes.py -q`
Expected: 如果失败，先记录真实失败点，再回到前序任务修复。

Run: `node --test src/views/subjectManagement.test.mjs src/views/subjectManagementPage.test.mjs`
Expected: 如果失败，先修 view model 或 controller。

**Step 3: Write minimal implementation**

同步当前系统事实到正式文档：

- `docs/current/interfaces.md`
  - 新增 `/api/subject-management/*`
- `docs/current/modules/kline-webui.md`
  - 新增“标的管理统一页”路由与作用说明
- 必要时更新 `docs/current/overview.md`
  - 说明新页面已落地

**Step 4: Run test to verify it passes**

Run: `pytest freshquant/tests/test_subject_management_service.py freshquant/tests/test_subject_management_routes.py -q`
Expected: PASS

Run: `node --test src/views/subjectManagement.test.mjs src/views/subjectManagementPage.test.mjs`
Expected: PASS

Run: `npm run build`
Expected: exit 0

**Step 5: Commit**

```bash
git add docs/current/interfaces.md docs/current/modules/kline-webui.md docs/current/overview.md freshquant/rear/api_server.py freshquant/rear/subject_management/routes.py freshquant/subject_management/dashboard_service.py freshquant/subject_management/write_service.py freshquant/tests/test_subject_management_service.py freshquant/tests/test_subject_management_routes.py morningglory/fqwebui/src/router/index.js morningglory/fqwebui/src/views/MyHeader.vue morningglory/fqwebui/src/api/subjectManagementApi.js morningglory/fqwebui/src/views/SubjectManagement.vue morningglory/fqwebui/src/views/subjectManagement.mjs morningglory/fqwebui/src/views/subjectManagementPage.mjs morningglory/fqwebui/src/views/subjectManagement.test.mjs morningglory/fqwebui/src/views/subjectManagementPage.test.mjs
git commit -m "docs: sync subject management unified page"
```
