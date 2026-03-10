# RFC 0029: KlineSlim 中枢/段中枢残影收敛修复

- **状态**：Approved
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-11
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

`FRE-6` 反馈 `KlineSlim` 页面残影问题仍然存在，但已经明显收敛：

- 残影只局限在 `中枢 / 段中枢 / 高级段中枢` 相关图层；
- 随着标的切换次数增加，残影会越来越多；
- 如果关闭 `中枢` 和 `段中枢` 开关，残影会消失。

这说明本轮问题不再是主 K 线、`笔 / 段` 折线或者通用缩放交互，而是更窄的 `markArea` 类图层清理问题。

设计阶段曾给出“结构性切换前缺少 `chart.clear()`”这一主假设，但 2026-03-11 进入实现阶段后补做了两类核验：

1. 直接对当前并行环境 `http://127.0.0.1:18080/kline-slim` 做真实浏览器探测，在 `5m / 15m` 主周期、额外打开 `15m / 30m` legend 的情况下连续多轮切换 `sz002262 -> sh510050 -> sz000001 -> sz002262`，截图哈希保持一致。
2. 新增并加压的 Playwright 回归在 stub `/api/stock_data` 下同样保持稳定，说明当前目标仓代码上已无法复现“切得越多残影越多”的现象。

因此，本 RFC 在 Approved 后的实际落地范围收敛为：

- 把当前“重复切标的后图形稳定、不残留旧中枢图层”的行为固化为自动化回归；
- 修正浏览器测试基础设施，使 ghosting 与 zoom/pan 规格可合并运行；
- 暂不对 `kline-slim.js` / `draw-slim.js` 做新的生产逻辑修改，除非出现新的稳定复现样本。

## 2. 目标（Goals）

- 修复 `KlineSlim` 在重复切换标的后累积的 `中枢 / 段中枢` 残影。
- 把浏览器自动化主验收路径收敛到“重复切换 `symbol` 后回到原标的，截图保持一致”。
- 保持同标的实时轮询刷新不走全量清图。
- 保持 `FRE-5` 已修好的缩放、平移和视口保持语义不回退。
- 不改变现有 `/api/stock_data` 契约和图例语义。

## 3. 非目标（Non-Goals）

- 不重写 `draw-slim.js`，不把 `markArea` 改成自绘矩形或自定义 series。
- 不修改后端接口、Redis payload 或 fullcalc 字段。
- 不把本票扩展为“所有 period/legend 组合都要重构”。
- 不新增 WebSocket/SSE 或其它刷新链路。
- 不做布局改版或 `KlineSlim` 页面功能扩展。

## 4. 范围（Scope）

**In Scope**

- `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs` 的文件级回归断言。
- `morningglory/fqwebui/tests/kline-slim-ghosting.browser.spec.mjs` 的浏览器自动化回归。
- `morningglory/fqwebui/tests/kline-slim-zoom-pan.browser.spec.mjs` 的合并运行稳定性。
- `morningglory/fqwebui/package.json` / `pnpm-lock.yaml` 的 Playwright 测试依赖。

**Out of Scope**

- `draw-slim.js` 的绘图模型重写。
- 后端 `/api/stock_data` 与 `/api/stock_data_chanlun_structure` 改造。
- 宿主机部署、PR、生产或交易运行操作。

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- 验证并固化当前“重复切标的后图形稳定”的现状。
- 保留当前 steady-state 的 `setOption + dataZoom` 语义，不凭猜测修改生产生命周期。
- 提供可重复执行的浏览器自动化验收。

**不负责（Must Not）**

- 不在未拿到新复现证据前强行引入 `chart.clear()` 一类生产改动。
- 不把现有图层协议改成新的内部 DSL。
- 不用截图人工观察替代自动化回归。

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
- 浏览器回归继续使用前端测试中的 stub `/api/stock_data` 数据，按 `symbol` 产出稳定、可区分的 deterministic payload。

## 8. 破坏性变更（Breaking Changes）

无破坏性变更。

本次修改只调整结构性切换时的前端图表生命周期，不改变接口参数、返回 schema、默认 legend 选中状态和持久配置。

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- `D:\fqpack\freshquant\morningglory\fqwebui\src\views\js\kline-slim.js`
  -> `morningglory/fqwebui/src/views/js/kline-slim.js`
- `D:\fqpack\freshquant\morningglory\fqwebui\src\views\js\draw-slim.js`
  -> `morningglory/fqwebui/src/views/js/draw-slim.js`
- `D:\fqpack\freshquant\morningglory\fqwebui\tests\*`
  -> `morningglory/fqwebui/tests/*`

迁移策略：

- 不整页回迁旧仓；
- 只迁移“结构性切换时强制丢弃旧图实例残留”的语义；
- 继续沿用目标仓现有 `FRE-5` 之后收敛出的缩放/平移实现。

## 10. 测试与验收（Acceptance Criteria）

- [ ] `node --test tests/kline-slim-multi-period-chanlun.test.mjs` 能锁定当前 controller 生命周期语义：route switch 走 loading 路径，`chart.clear()` 仅留在空 symbol / 默认 symbol 分支。
- [ ] 新增 Playwright 回归：重复切换多个 `symbol`，额外打开 `15m / 30m` legend，保持 `中枢 / 段中枢` 打开，切回初始标的后截图或哈希与初始基线一致。
- [ ] 同一轮浏览器回归中，关闭 `中枢 / 段中枢` legend 后页面不会留下旧残影。
- [ ] 现有 `tests/kline-slim-zoom-pan.browser.spec.mjs` 继续通过，证明 `FRE-5` 修复未被回退。
- [ ] `pnpm build` 通过。

## 11. 风险与回滚（Risks / Rollback）

- 风险：issue 原始截图可能来自旧部署或更窄的现场条件，当前目标仓已无法直接复现。
  - 缓解：先把当前稳定行为锁成自动化回归；若用户后续提供新的稳定复现路径，再单开后续修复而不是继续猜测性改代码。
- 风险：截图型浏览器回归对 stub 数据稳定性敏感。
  - 缓解：测试中按 `symbol` 固定生成 deterministic payload，并扩大到“多轮切标的 + 额外周期 legend”的压力路径。
- 风险：ghosting 与 zoom/pan 浏览器规格并发运行时会同时写 `web/`，导致 `EBUSY`。
  - 缓解：新增共享 build lock，串行化 `vite build`。

回滚：

- 回退 `morningglory/fqwebui/src/views/js/kline-slim.js` 和新增测试文件即可；
- 不涉及后端、部署和数据库变更，回滚成本低。

## 12. 里程碑与拆分（Milestones）

- M1：RFC / 设计稿 / implementation plan 完成并进入 Human Review
- M2：核验当前目标仓与并行环境，确认 issue 现象在现代码上是否仍可复现
- M3：新增 ghosting 浏览器回归并固化当前稳定行为
- M4：ghosting 与 zoom/pan 回归可合并通过
- M5：进入 `Merging` 前完成 RED/GREEN 证据整理
