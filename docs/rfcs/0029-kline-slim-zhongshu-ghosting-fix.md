# RFC 0029: KlineSlim 中枢/段中枢残影收敛修复

- **状态**：Approved
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-11
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

`FRE-6` 在第一次实现后被重新打开。新的用户补充信息不是“单纯切标的就残影”，而是：

- 先切到别的 `symbol`
- 再进行鼠标缩放 / 平移
- 然后继续切换 `symbol`
- 此时残影会留在后续标的上

这把问题从“普通切标的残影”收敛成了更具体的组合路径问题：`zoom/pan` 交互会把某种图表内部状态带进下一次结构性切换，而残影仍然只集中在 `中枢 / 段中枢 / 高级段中枢` 相关图层。

本轮重新进入 `Todo` 后，已经补做了三组调查证据：

1. 现有自动化存在盲区：`tests/kline-slim-ghosting.browser.spec.mjs` 只覆盖“切标的 + legend”，`tests/kline-slim-zoom-pan.browser.spec.mjs` 只覆盖“缩放后同标的刷新”，没有把“缩放后再切标的”串起来。
2. 在 deterministic stub `/api/stock_data` 下，按 `sz002262 -> sh510050(缩放/平移) -> sz000001 -> sz002262` 的一次性 Playwright 探针可以稳定复现：回到 `sz002262` 时 `dataZoom.start/end` 已恢复默认 `70/100`，但截图哈希仍然改变。
3. 用同一条探针在浏览器里临时 monkeypatch “切 `symbol` 前先 `chart.clear()`” 后，基线哈希与回放哈希恢复一致。

因此，本 RFC 的修复方向重新收敛为：

- 在结构性切换前显式清空 chart 实例；
- 把“缩放/平移后再切标的”的组合路径固化为浏览器自动化回归；
- 不扩大到 `draw-slim.js` 绘图模型重写，除非新回归仍然失败。

## 2. 目标（Goals）

- 修复 `KlineSlim` 在“切标的 -> 缩放/平移 -> 再切标的”路径上的 `中枢 / 段中枢 / 高级段中枢` 残影。
- 把浏览器自动化主验收路径改成覆盖组合交互，而不是只覆盖普通切标的。
- 保持同 identity 的实时刷新仍然不做全量清图。
- 保持 `FRE-5` 已修好的缩放、平移和刷新后视口保持语义不回退。
- 不改变现有 `/api/stock_data` 契约和 legend 语义。

## 3. 非目标（Non-Goals）

- 不重写 `draw-slim.js`，不把 `markArea` 改成自绘矩形或自定义 series。
- 不修改后端接口、Redis payload 或 fullcalc 字段。
- 不把本票扩展为“所有 period / legend 组合的全面重构”。
- 不新增 WebSocket/SSE 或其它刷新链路。
- 不做布局改版或 `KlineSlim` 页面功能扩展。

## 4. 范围（Scope）

**In Scope**

- `morningglory/fqwebui/src/views/js/kline-slim.js` 的结构性切换生命周期。
- `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs` 的文件级 controller 断言。
- `morningglory/fqwebui/tests/kline-slim-ghosting.browser.spec.mjs` 的组合路径浏览器回归。
- `morningglory/fqwebui/tests/kline-slim-zoom-pan.browser.spec.mjs` 的回归保护。

**Out of Scope**

- `draw-slim.js` 的绘图模型重写。
- 后端 `/api/stock_data` 与 `/api/stock_data_chanlun_structure` 改造。
- 宿主机部署、PR、生产或交易运行操作。

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- 修复结构性切换前 chart 未彻底清空导致的前端残影。
- 保留当前 steady-state 的 `setOption + dataZoom` 语义，不在普通刷新路径清图。
- 提供可重复执行的浏览器自动化验收，覆盖“缩放后再切标的”。

**不负责（Must Not）**

- 不把本票升级成 renderer 层重构。
- 不新增测试专用生产分支逻辑或后端接口。
- 不用人工截图观察替代自动化回归。

**依赖（Depends On）**

- `KlineSlim` 现有路由参数：`symbol / period / endDate`
- 现有 `drawSlim()` renderer
- Playwright 浏览器测试基础设施

**禁止依赖（Must Not Depend On）**

- 新增后端接口
- 人工肉眼对比作为唯一验收
- 旧仓整页代码直接复制

## 6. 对外接口（Public API）

无新增对外 API。

现有接口保持不变：

- `GET /api/stock_data?symbol=<symbol>&period=<period>&endDate=<optional>&realtimeCache=<optional>`

前端行为变化限定为：

- 当 `symbol / period / endDate` 触发结构性切换时，图表实例先显式清空，再等待新数据首帧；
- 同标的轮询刷新、legend 切换、缩放和平移仍保持现有协议。

## 7. 数据与配置（Data / Config）

- 不新增 Mongo/Redis collection。
- 不新增环境变量。
- 不新增 Dynaconf 配置项。
- 浏览器回归继续使用 stub `/api/stock_data`，按 `symbol` 生成稳定、可区分的 deterministic payload。

## 8. 破坏性变更（Breaking Changes）

无接口级破坏性变更。

行为级变化只有一条：

- 切 `symbol / period / endDate` 时会显式清图，因此结构性切换后的视口会回到默认窗口，而不是继承上一个标的的缩放状态。

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- `D:\fqpack\freshquant\morningglory\fqwebui\src\views\js\kline-slim.js`
  -> `morningglory/fqwebui/src/views/js/kline-slim.js`
- `D:\fqpack\freshquant\morningglory\fqwebui\tests\*`
  -> `morningglory/fqwebui/tests/*`

迁移策略：

- 不整页回迁旧仓；
- 只迁移“结构性切换前显式清图”的生命周期语义；
- 继续沿用目标仓现有 `FRE-5` 之后收敛出的缩放/平移实现。

## 10. 测试与验收（Acceptance Criteria）

- [ ] `node --test tests/kline-slim-multi-period-chanlun.test.mjs` 能锁定 controller 语义：结构性切换前存在显式 `chart.clear()` 路径，普通 `fetchMainData()` 刷新路径不清图。
- [ ] Playwright 新增组合路径回归：`sz002262 -> sh510050(缩放/平移) -> sz000001 -> sz002262` 后，回到 `sz002262` 的截图或哈希与初始基线一致。
- [ ] 同一轮组合路径里，关闭 `中枢 / 段中枢` legend 后页面不会留下旧残影。
- [ ] 现有 `tests/kline-slim-zoom-pan.browser.spec.mjs` 继续通过，证明 `FRE-5` 修复未被回退。
- [ ] `pnpm build` 通过。

## 11. 风险与回滚（Risks / Rollback）

- 风险：结构性切换时视口会被重置，用户可能感觉与缩放后的当前窗口不一致。
  - 缓解：把这一点作为 Human Review 的明确审批点；同 identity 刷新仍保持视口。
- 风险：如果真正问题不止于结构性切换清图，浏览器回归仍可能失败。
  - 缓解：本票先把 controller 生命周期修正为最小闭环；若回归仍红，再单开 renderer follow-up。
- 风险：浏览器回归对 stub 数据稳定性敏感。
  - 缓解：测试中按 `symbol` 固定生成 deterministic payload，并把缩放/切标的顺序写死。

回滚：

- 回退 `morningglory/fqwebui/src/views/js/kline-slim.js` 和新增测试断言即可；
- 不涉及后端、部署和数据库变更，回滚成本低。

## 12. 里程碑与拆分（Milestones）

- M1：更新 RFC / 设计稿 / implementation plan，并重新进入 Human Review
- M2：在自动化里补上“缩放后再切标的”的 RED 证据
- M3：controller 增加结构性切换显式清图
- M4：ghosting + zoom/pan 回归同时通过
- M5：整理 RED/GREEN 证据并重新进入 `In Progress`
