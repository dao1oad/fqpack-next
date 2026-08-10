# 标的设置面板「默认值覆盖人工设置」修复方案（2026-08-10）

> 状态：Devin 评审完成（部分同意）；P0 复议后按用户设计定稿：保存=展示值
> （含默认值），不做字段省略 / 待建 Issue
> 关联：GitHub dao1oad/fqpack-next（Issue 待创建）
> 类型：前端 bug 修复（数据加载门禁缺失导致兜底默认值覆盖人工配置）

## 1. 问题背景（生产实证）

116 生产机 `guardian_buy_grid_configs` 中：

- 9 个标的（002475/002594/159622/512000/512070/512800/600271/600570/603919）的
  `max_position_amounts` 自 2026-04-08 起为 `null`；
- `audit_log` 实证 002262 于 08-07 10:49:10 的 web 保存把用户设置的
  `[600000,700000,800000]` 覆盖为前端默认 `[200000,350000,500000]`；
- 多标的首笔 web 保存会把 `null` 直接写成 `[200000,350000,500000]`。

根因：KlineSlim「标的设置」面板部分写操作缺少「数据已从后端加载完成」门禁，
数据未加载/加载失败时页面草稿为本地默认值，整包保存把默认值写回后端并覆盖
人工配置（后端 `upsert_config` 收到非空字段即覆盖）。

## 2. 设计定稿（避免过度设计）

单一规则：

> 面板内一切写操作（保存按钮、开关切换、全部开启/关闭、拖线落盘）只有在
> 「对应数据已从后端加载完成」时才可用；加载中、加载失败、无数据 → 一律禁用并
> 给出提示。加载完成后，页面显示什么，保存就是什么（所见即所得）。

推论（不需要额外状态）：

- 加载的一定是后端数据；后端明确为空时才显示默认值（可加「默认」灰显标记）。
- 不做 dirty 字段判断：加载完成后整包提交当前显示数据；用户没改的字段保持
  后端原值（因为显示的就是后端原值或合法默认值）。
- 不做 `set_by`/来源状态机、不加数据库字段。

## 3. 改动清单（全部前端，后端零改动）

### 3.1 `morningglory/fqwebui/src/views/KlineSlim.vue`

- `priceGuideEditLocked` 补 `!subjectPriceDetail`：
  一次性覆盖「保存买入设置」「全部开启」「全部关闭」「单档开关」「拖线保存」
  （与「保存价格设置」按钮现有条件对齐）。
- 「保存总上限」「待买池保存」等 subject panel 写按钮补
  `!subjectPanelState.subjectPanelDetail`。

### 3.2 `morningglory/fqwebui/src/views/js/kline-slim-price-panel.mjs`

- `buildGuardianPriceSaveDraft` / `buildGuardianEnabledSaveDraft`：
  detail 缺失时直接拒绝提交（不拿空草稿兜底），与按钮禁用构成双保险。
- **P0 复议定稿（用户设计，否决 Devin 选项 a）**：保存链路**不做字段省略**——
  保存 payload = 当前展示的值（后端值，或加载完成后后端为空时的默认值），
  所见即所得，默认值同样按展示值保存；`cloneGuardianDraft` 的默认值兜底
  保持不变（展示即真值）。
- 展示层：加载完成后后端为空时，输入框显示默认值并带「默认」灰显标记
  （UX 提示，让「未设置」可见）；标记不影响保存语义。

### 3.3 `morningglory/fqwebui/src/views/js/kline-slim-subject-panel.mjs`

- `positionLimitAvailable` 语义修正：detail 未加载 → `false`（禁用保存总上限）；
  加载成功但标的不在跟踪范围 → 显示原因并禁用。

### 3.4 后端

- 零改动（`upsert_config` 已具备「字段缺失=保留现值」与非法值拒绝语义）。

## 4. 明确不做（防过度设计）

- 不做 dirty/脏字段追踪；
- 不加 `max_position_amounts_set_by` 等来源字段；
- 不改后端接口契约；
- 不主动批量迁移既有 9 个 `null` 标的；这些标的在面板上展示默认值，
  用户保存时默认值按所见即所得落库（预期行为，非 bug）。

## 5. 测试与验证

- 前端单测：`kline-slim-price-panel.test.mjs`（未加载时保存被拒/按钮禁用）、
  `kline-slim-subject-panel` 相关用例、`subjectManagementPage.test.mjs` 零回归。
- P1 断言（Devin 评审补充）：detail 缺失时拖线保存（`handlePriceGuideDragEnd`）
  不发请求。
- 断言（按用户设计）：`null` 标的加载完成后显示默认值 + 「默认」标记，
  保存后默认值落库且刷新后仍显示同一默认值（所见即所得）。
- 本地预检：`npm run lint` / `npm run test:unit` / `npm run test:browser-smoke` /
  `npm run build`（命中 `morningglory/fqwebui/**` 时仓库预检强制）。
- 仓库预检：`script/fq_local_preflight.ps1 -Mode Ensure`。

## 6. 部署与验收

- 部署面：重建并部署 Web UI（`fqnext_webui:2026.2.23`）；API 无改动。
- 验收：模拟「detail 未加载点保存」按钮不可点；对 `null` 标的打开面板显示
  「默认」标记；保存后刷新仍是保存的值；已设置标的任意保存后值不变。

## 7. Done 定义

`Done = PR 合并 + CI 三绿（docs-current-guard / pre-commit / pytest）+ docs/current
同步（如涉及）+ Web UI 部署 + 健康检查 + cleanup`（AGENTS.md 第 8 节）。
