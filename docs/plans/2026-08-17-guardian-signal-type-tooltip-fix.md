# Guardian 信号类型溯源 + K 线悬浮框固定显示 修复方案

> 日期：2026-08-17
> 分支：`codex/fix-guardian-signal-type-tooltip`
> 交付：合并到本地 `main`，不推送远程、不部署（用户明确指示）。
> 一致性：方案经 Devin Ultra 第一轮只读评审，按评审意见修订后实施（见「Devin 评审修订」）。

## 1. 背景与目标

### 问题 A：图表悬浮框"信号类型"与运行观测不一致

- 运行观测显示 600037（2026-08-17 09:52）Guardian 信号为「看涨背驰」（`macd_bullish_divergence`）。
- kline-slim 行情图表交易复盘悬浮框"信号类型"却显示 `buy_zs_huila`。
- 根因（已在 116 用真实数据核验）：
  1. Guardian 事件链禁用 `buy_zs_huila` 的过滤（PR #250）**已生效**：当天 `stock_signals` 仅 1 条，`remark=看涨背驰`，无任何 `buy_zs_huila` 被保存。
  2. 悬浮框的信号类型来自 position-review 读模型 `resolve_signal_type()`
     （`freshquant/position_review/chart_projection.py`）：订单 `om_order_requests`
     无 `signal_type` 字段，`strategy_context.guardian_buy_grid={path:"holding_add",
     base_amount:20000}` 命中分支 `path in {"holding_add",""} and base_amount is not
     None → 返回 "buy_zs_huila"`，与真实触发信号无关。
  3. `stock_signals` 文档只存中文 `remark`，未存原始 `signal_type`，读模型无从恢复真实类型。

### 问题 B：悬浮框无法停留查看

- ECharts tooltip 默认行为：鼠标移入悬浮框时立即消失，无法滚动/查看完整详情。
- 期望：悬浮框出现后不自动消失，鼠标可移入；点击悬浮框外部任意处才消失。

## 2. 最终方案

### A. 后端：信号类型溯源

1. `freshquant/signal/a_stock_common.py::save_a_stock_signal`
   - 增加 `signal_type=None` 关键字参数；`$set` 中仅当非 None 时写入 `signal_type` 字段
     （向后兼容全部旧调用方；不影响唯一索引与并发 upsert）。
2. 调用点传入真实类型：
   - `freshquant/signal/astock/job/monitor_stock_zh_a_min.py`：`signal_type=s.signal_type`（Guardian 事件链，1min/5m 共用同一调用点）。
   - `freshquant/analysis/custom_stock_signal.py`、`freshquant/screening/writers/database.py`：把已有 `signal_type` 一并传入（同机制，无回归）。
3. `freshquant/position_review/service.py::_serialize_timeline_signal`
   - 序列化输出增加 `signal_type` 字段（透传），复盘读模型（timeline / chart / review）统一受益。
4. `freshquant/position_review/chart_projection.py::resolve_signal_type`
   - 优先级调整为：
     1. manual source 判定（不变，最先）
     2. `request.signal_type` 显式类型（不变）
     3. **新增**：关联信号文档 `signal.signal_type` 显式类型——仅当类型在
        `SIGNAL_TYPE_REGISTRY` 且与 side 一致（buy → buy 系 3 类；sell → 不新增，
        Guardian 卖侧原始类型不在 registry，维持既有兜底，记为非目标）
     4. **新增排序**：remark 关键词扫描提前到 buy_grid 推导之前（旧数据无
        `signal_type` 时按 remark 恢复真实类型）；`_BUY_SIGNAL_KEYWORDS` 增加
        `"背驰"`（macd_bullish_divergence）与 `"v反"`（buy_v_reverse），覆盖
        Guardian 中文 remark「看涨背驰 / V反上涨」。
     5. buy_grid 推导仅作无任何证据时的兜底（行为与现状一致）。

### B. 前端：悬浮框固定显示

5. `morningglory/fqwebui/src/views/js/kline-slim-chart-renderer.mjs`
   - 顶层 `tooltip` 配置（`buildKlineSlimChartOption`，约 1768 行）增加
     `enterable: true`、`alwaysShowContent: true`（tooltip 组件级选项放顶层，
     订单复盘与 CLX 两个 series 同时生效）。
6. `morningglory/fqwebui/src/views/js/kline-slim-chart-controller.mjs`
   - 新增 zr 级 `click` 监听：点击空白（`event.target` 为空）→ `hideTip`。
   - 新增 `document` 级 `click` 监听：点击图表容器外部 → `hideTip`；
     点击 tooltip 内部 / 图表容器内元素不消失。
   - `applyScene` / `clear` 时主动 `hideTip`，防止切周期/换标的后的陈旧悬浮框残留。
   - `dispose` 时移除新增监听。

### C. 测试与构建

- 后端 pytest：
  - `test_a_stock_common.py`：`signal_type` 落库 / 缺省不写字段。
  - `test_position_review_refactor.py`：`resolve_signal_type` 优先级
    （signal.signal_type > buy_grid；关键词「背驰 / v反」；side 不一致忽略；
    未知类型兜底）；`_serialize_timeline_signal` 透传。
  - `test_guardian_monitor_cli.py`：事件链调用点传 `signal_type`。
- 前端 node 测试：
  - `kline-slim-order-review-renderer.test.mjs`：顶层 tooltip 含
    `enterable / alwaysShowContent`。
  - `kline-slim-chart-controller.test.mjs`：空白点击 hideTip、元素点击不 hide、
    容器外点击 hideTip、applyScene hideTip。
- 按仓库惯例执行 `pnpm run build` 重建 `web/assets` 产物并提交；eslint 通过。

### D. 文档同步

- `docs/current/modules/strategy-guardian.md`：`stock_signals` 存储字段增加 `signal_type`。
- `docs/current/modules/kline-webui.md`：复盘 marker「信号类型」语义（真实信号类型优先）
  与悬浮框交互（固定显示、点击外部关闭）。

### E. 交付

- feature branch 测试全绿后，合并到**本地 `main`**；不推送、不部署；合并后删除 feature branch。

## 3. 非目标

- Guardian 卖侧（`sell_zs_huila` / `sell_v_reverse` / `macd_bearish_divergence`）
  不入 `SIGNAL_TYPE_REGISTRY`，卖侧悬浮框维持既有推导口径。
- 不对历史 `stock_signals` 做一次性 backfill（关键词扫描已覆盖存量中文 remark 主场景）。
- 不改 PositionReview 独立页 / 组合总览的既有交互（本轮仅 kline-slim 行情图表）。

## 4. Devin 评审修订（第一轮，只读）

按 Devin Ultra 评审意见落地：
- A4：`signal.signal_type` 分支放在 manual 判定之后、加 side 一致性校验（已并入 2.A.4）。
- 验收陷阱：`_BUY_SIGNAL_KEYWORDS` 补「背驰」并让关键词扫描先于 buy_grid 推导
  （600037 存量信号无 `signal_type`，仅靠该路径才能正确显示）。
- B5：`enterable / alwaysShowContent` 放顶层 tooltip；`applyScene / clear` 主动 hideTip。
- B6：空白点击用 zr 级 `click`（`event.target` 为空）实现；document 级监听按
  「容器内不隐藏」。
- D：合并本地 `main` 与 AGENTS.md 冲突——按用户明确指示执行（仅本地合并、不推送）。
