# Frontend Optimization Roadmap Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不重写框架的前提下，收口 `fqwebui` 的混合架构、隐式全局、构建体积风险与测试债，让后续前端改动更快、更稳、更可维护。

**Architecture:** 继续沿用当前已经成型的 `workbench primitives + page controller + api module` 方向，不做 Vue 框架级迁移，不搞一次性大重构。先补工程护栏与共享基础层，再按页面复杂度和业务收益逐步把 legacy 页迁到统一写法，最后补类型化与质量门升级。

**Tech Stack:** Vue 3、Vite、Element Plus、TanStack Vue Query、Vue Router、Node built-in test、Playwright

---

### Task 1: 固化当前前端基线与质量护栏

**Files:**
- Modify: `morningglory/fqwebui/tests/build-budget.test.mjs`
- Modify: `morningglory/fqwebui/tests/frontend-quality-gates.test.mjs`
- Modify: `morningglory/fqwebui/package.json`
- Modify: `morningglory/fqwebui/vite.config.js`

**Step 1: 先把“配置存在”升级为“产物受约束”**

- 在 `build-budget.test.mjs` 中增加真实 bundle 预算断言，而不是只检查 `manualChunks` 和 `chunkSizeWarningLimit` 字段存在。
- 预算先按当前构建产物给出可执行上限：
  - `vendor-echarts` 不允许继续明显膨胀
  - `vendor-element-plus` 不允许继续明显膨胀
  - `vendor-core` 不允许继续明显膨胀
  - `index` 主入口不允许继续吞页面代码
- `frontend-quality-gates.test.mjs` 增加一条约束：`KNOWN_RED_TEST_FILES` 数量只能减少，不能增加。

**Step 2: 运行测试，确认新护栏先失败再收口**

Run:

```powershell
node --test morningglory/fqwebui/tests/build-budget.test.mjs morningglory/fqwebui/tests/frontend-quality-gates.test.mjs
```

Expected: 若预算或 known-red 规则未实现，先看到失败，再进入实现。

**Step 3: 在 `vite.config.js` 中补构建预算元信息**

- 保留现有 `manualChunks` 方向。
- 增加一个可被测试读取的预算配置对象，例如 `bundleBudget`，避免测试去硬编码散落的 chunk 名和阈值。
- 不在这一轮做更激进的 chunk 拆分，只先让预算成为正式约束。

**Step 4: 再跑相关测试**

Run:

```powershell
node --test morningglory/fqwebui/tests/build-budget.test.mjs morningglory/fqwebui/tests/frontend-quality-gates.test.mjs
cd morningglory/fqwebui
npm run build
```

Expected: PASS，且本轮 build 仍成功。

### Task 2: 修共享运行时隐患，先处理 cache 和轮询

**Files:**
- Modify: `morningglory/fqwebui/src/global.js`
- Modify: `morningglory/fqwebui/src/views/js/future-control.js`
- Modify: `morningglory/fqwebui/src/views/FuturePositionList.vue`
- Modify: `morningglory/fqwebui/src/views/RuntimeObservability.vue`
- Modify: `morningglory/fqwebui/src/http.test.mjs`
- Create: `morningglory/fqwebui/src/global.test.mjs`

**Step 1: 为 `SimpleCache` 语义补失败测试**

- 断言 `set(key, value, ttlSeconds)` 能真正覆盖默认 TTL。
- 断言过期键会被清除。
- 断言 legacy 三参调用不是“看起来支持、其实无效”。

**Step 2: 跑失败测试**

Run:

```powershell
node --test morningglory/fqwebui/src/global.test.mjs morningglory/fqwebui/src/http.test.mjs
```

Expected: 新增的 cache TTL 断言先失败。

**Step 3: 写最小实现**

- 让 `SimpleCache.set()` 真正支持可选 TTL 参数，或者删掉三参调用并统一改成显式缓存 API；两者选一个，不要继续保留“假三参”。
- 处理 legacy 轮询资源释放：
  - `FuturePositionList.vue` 当前 `setInterval` 没有对应清理，先补上销毁时 `clearInterval`
  - `future-control.js` 里同类轮询统一检查
  - 保持 `RuntimeObservability.vue` 现有 `stopPollingTimer` 模式，向前对齐

**Step 4: 跑页面相关测试**

Run:

```powershell
node --test morningglory/fqwebui/src/global.test.mjs morningglory/fqwebui/src/views/runtime-observability.test.mjs
```

Expected: PASS

### Task 3: 收口共享基础层，减少 `globalProperties` 和空 Vuex

**Files:**
- Modify: `morningglory/fqwebui/src/main.js`
- Modify: `morningglory/fqwebui/src/global.js`
- Modify: `morningglory/fqwebui/src/store/index.js`
- Create: `morningglory/fqwebui/src/config/tradingConstants.mjs`
- Modify: `morningglory/fqwebui/src/views/js/future-control.js`
- Modify: `morningglory/fqwebui/src/views/js/kline-mixin.js`
- Modify: `morningglory/fqwebui/src/views/FuturePositionList.vue`
- Modify: `morningglory/fqwebui/src/views/StatisticsChat.vue`

**Step 1: 先写防回退测试**

- 为 `frontend-quality-gates.test.mjs` 增加两条约束：
  - `src/store/index.js` 只能在仍有真实消费者时保留
  - futures legacy 页使用的账户常量应来自显式 config 模块，而不是 `this.$futureAccount` 一类全局注入

**Step 2: 跑失败测试**

Run:

```powershell
node --test morningglory/fqwebui/tests/frontend-quality-gates.test.mjs
```

Expected: 新增断言失败。

**Step 3: 写最小实现**

- 抽出 `tradingConstants.mjs`，把 `$futureAccount`、`$globalFutureAccount`、`$stopRate` 这类常量改为显式导入。
- 若 `src/store/index.js` 仍无真实使用者，就从 `main.js` 中移除 Vuex 注册，并删除空 store。
- `global.js` 保留必须存在的最小内容；不再让它承担“共享常量仓库”职责。

**Step 4: 跑回归**

Run:

```powershell
cd morningglory/fqwebui
npm run test:unit
npm run build
```

Expected: PASS

### Task 4: 把 Query/HTTP 策略平台化，不再每页散写默认值

**Files:**
- Modify: `morningglory/fqwebui/src/main.js`
- Modify: `morningglory/fqwebui/src/http.js`
- Create: `morningglory/fqwebui/src/lib/queryClient.mjs`
- Create: `morningglory/fqwebui/src/lib/queryPolicies.mjs`
- Modify: `morningglory/fqwebui/src/views/SignalList.vue`
- Modify: `morningglory/fqwebui/src/views/ModelSignalList.vue`
- Modify: `morningglory/fqwebui/src/views/StockPositionList.vue`
- Modify: `morningglory/fqwebui/src/views/js/kline-big.js`
- Modify: `morningglory/fqwebui/src/views/js/multi-period.js`
- Modify: `morningglory/fqwebui/src/components/StockPools.vue`
- Modify: `morningglory/fqwebui/src/components/StockMustPools.vue`
- Modify: `morningglory/fqwebui/src/components/StockCjsd.vue`
- Test: `morningglory/fqwebui/src/http.test.mjs`
- Create: `morningglory/fqwebui/src/lib/queryPolicies.test.mjs`

**Step 1: 为共享策略补失败测试**

- 断言 `QueryClient` 默认值存在统一 `staleTime` / retry / refetch 行为。
- 断言“30s 刷新”、“10s 刷新”、“10min 刷新”来自命名策略，而不是页面内魔法数字。
- 断言 `http.js` 至少具备显式 `timeout` 和可读的基础配置。

**Step 2: 跑失败测试**

Run:

```powershell
node --test morningglory/fqwebui/src/http.test.mjs morningglory/fqwebui/src/lib/queryPolicies.test.mjs
```

Expected: 新增断言失败。

**Step 3: 写最小实现**

- 在 `queryClient.mjs` 中集中创建 QueryClient，并在 `main.js` 注册。
- 在 `queryPolicies.mjs` 里定义：
  - `pollingFast`
  - `pollingNormal`
  - `pollingSlow`
  - `staticLike`
- 现有 13 处 `useQuery` 改为调用共享策略，去掉散落的 `staleTime: 5000`/`refetchInterval` 魔法值。
- `http.js` 增加显式 `timeout`，并保留统一 response unwrap。

**Step 4: 运行核心回归**

Run:

```powershell
cd morningglory/fqwebui
npm run test:unit
npm run test:browser-smoke
```

Expected: PASS

### Task 5: 完成路由级代码拆分，压主入口体积

**Files:**
- Modify: `morningglory/fqwebui/src/router/index.js`
- Modify: `morningglory/fqwebui/tests/build-budget.test.mjs`
- Test: `morningglory/fqwebui/src/router/pageMeta.test.mjs`

**Step 1: 先写失败测试**

- 断言旧核心页也改为动态 import：
  - `FuturesControl.vue`
  - `StockControl.vue`
  - `MultiPeriod.vue`
  - `KlineBig.vue`
  - `KlineSlim.vue`
  - `StockPools.vue`
  - `StockCjsd.vue`
- 保留 `pageMeta`、标题和默认跳转行为不变。

**Step 2: 跑失败测试**

Run:

```powershell
node --test morningglory/fqwebui/src/router/pageMeta.test.mjs morningglory/fqwebui/tests/build-budget.test.mjs
```

Expected: 新增断言失败。

**Step 3: 写最小实现**

- 将旧静态页全部切到 `() => import(...)`。
- 不改路由 URL，不改页面元信息协议，不在这一轮引入嵌套路由重构。

**Step 4: 跑构建并记录体积变化**

Run:

```powershell
cd morningglory/fqwebui
npm run build
```

Expected: 主入口 chunk 明显下降，且路由行为不回退。

### Task 6: 按复杂度顺序拆最重页面，先拆 `RuntimeObservability`

**Files:**
- Modify: `morningglory/fqwebui/src/views/RuntimeObservability.vue`
- Modify: `morningglory/fqwebui/src/views/runtimeObservability.mjs`
- Create: `morningglory/fqwebui/src/views/runtimeObservabilityController.mjs`
- Create: `morningglory/fqwebui/src/views/runtimeObservabilityDerived.mjs`
- Create: `morningglory/fqwebui/src/views/runtimeObservabilityPolling.mjs`
- Test: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`

**Step 1: 补失败测试，锁定拆分边界**

- 断言页面只保留模板装配和交互绑定，不再承载大块派生逻辑。
- 断言默认组件回填不会覆盖用户手动选择。
- 断言 polling 生命周期统一由共享 polling 模块处理。

**Step 2: 跑失败测试**

Run:

```powershell
node --test morningglory/fqwebui/src/views/runtime-observability.test.mjs
```

Expected: 新增断言失败。

**Step 3: 写最小实现**

- `RuntimeObservability.vue` 只负责模板、事件绑定、局部样式。
- `runtimeObservabilityController.mjs` 管页面状态迁移和用户交互。
- `runtimeObservabilityDerived.mjs` 管 traces / events / sidebar 的派生结果。
- `runtimeObservabilityPolling.mjs` 管轮询启停与清理。
- `runtimeObservability.mjs` 保留纯格式化、归一化、映射函数。

**Step 4: 跑单测和 smoke**

Run:

```powershell
node --test morningglory/fqwebui/src/views/runtime-observability.test.mjs
cd morningglory/fqwebui
npm run test:browser-smoke
```

Expected: PASS

### Task 7: 第二批拆 legacy 交易页，优先 `KlineSlim` / `FuturePositionList`

**Files:**
- Modify: `morningglory/fqwebui/src/views/KlineSlim.vue`
- Modify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Modify: `morningglory/fqwebui/src/views/FuturePositionList.vue`
- Modify: `morningglory/fqwebui/src/views/js/future-control.js`
- Create: `morningglory/fqwebui/src/views/klineSlimController.mjs`
- Create: `morningglory/fqwebui/src/views/futurePositionController.mjs`
- Test: `morningglory/fqwebui/src/views/klineSlim.test.mjs`
- Test: `morningglory/fqwebui/tests/kline-slim-*.test.mjs`

**Step 1: 先做不改 UI 的结构性拆分**

- 目标是把 `this` 风格逻辑从页面里剥出来，不在这一步追求视觉变化。
- 优先抽：
  - 轮询与刷新
  - query 参数解析
  - 图表外部状态与价格层级保存
  - legacy 缓存控制

**Step 2: 跑相关测试**

Run:

```powershell
cd morningglory/fqwebui
npm run test:unit
```

Expected: 相关 `kline-slim` 用例保持通过，known-red 数量不增加。

### Task 8: 渐进式类型化，从纯逻辑模块开始

**Files:**
- Modify: `morningglory/fqwebui/jsconfig.json`
- Create: `morningglory/fqwebui/tsconfig.json`
- Modify: `morningglory/fqwebui/package.json`
- Create: `morningglory/fqwebui/src/api/types.d.ts`
- Modify: `morningglory/fqwebui/src/api/*.js`
- Modify: `morningglory/fqwebui/src/views/*Page.mjs`

**Step 1: 先上类型检查，不强行全量改 TS**

- 引入 `vue-tsc --noEmit` 或等价类型检查命令。
- 先让 `api` 和 `*Page.mjs` 获得稳定边界类型。
- 第一轮不改全部 `.vue`，不碰最重模板页。

**Step 2: 跑类型检查并修掉首批高价值告警**

Run:

```powershell
cd morningglory/fqwebui
npx vue-tsc --noEmit
```

Expected: 先看到现状告警，再分批收敛到可持续维护水平。

### Task 9: 清 known-red，扩 smoke 覆盖

**Files:**
- Modify: `morningglory/fqwebui/scripts/run-node-tests.mjs`
- Modify: `morningglory/fqwebui/scripts/run-browser-smoke.mjs`
- Modify: `morningglory/fqwebui/tests/*.browser.spec.mjs`
- Modify: `.github/workflows/ci.yml`

**Step 1: 建立还债顺序**

- 先把 7 个 known-red 按“能否快速恢复”分成三类：
  - 直接修
  - 需要先拆结构再修
  - 保留到后续专项
- browser smoke 在现有 `daily-screening / system-settings / workbench-overlap` 基础上，优先补一个 `kline-slim` 关键路径。

**Step 2: 逐个移出 known-red 白名单**

Run:

```powershell
cd morningglory/fqwebui
npm run test:unit:all
```

Expected: known-red 数量逐步下降，最终不再依赖白名单跳过。

### Task 10: 最终验证与文档同步

**Files:**
- Modify: `docs/current/architecture.md`
- Modify: `docs/current/runtime.md`
- Modify: `docs/current/troubleshooting.md`
- Modify: `docs/current/deployment.md`

**Step 1: 跑完整前端 gate**

Run:

```powershell
cd morningglory/fqwebui
npm run lint
npm run test:unit
npm run test:browser-smoke
npm run build
```

Expected: 全绿。

**Step 2: 同步当前事实文档**

- `architecture.md` 记录前端共享架构方向：
  - `workbench primitives`
  - `page controller`
  - query policy / http base layer
- `runtime.md` 记录浏览器 smoke 与前端 gate 现状。
- `troubleshooting.md` 记录前端常见排障口径：
  - bundle budget 超限
  - browser smoke 失败
  - known-red 清理策略
- `deployment.md` 保持前端 gate 与 deploy 口径一致。

**Step 3: 再跑一次本地预检查入口**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File script/fq_local_preflight.ps1 -Mode Ensure
```

Expected: 前端相关 gate 通过，且文档与当前事实一致。
