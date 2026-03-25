# Kline Slim 平移精度与批量运行态设计

## 背景

`kline-slim` 当前还存在 3 个交互问题：

- 鼠标平移只支持横轴，无法对已经手动缩放的纵轴做平移
- 画线编辑输入框已经是三位小数，但图上拖拽取价仍在控制器里四舍五入到两位
- `Guardian 倍量价格` / `止盈价格` 的 `全部开启` 只改配置开关，不同步运行态，导致面板开关看起来全开但 K 线图上的横线仍保持未激活样式

## 目标

- 在不破坏现有画线拖拽的前提下，为主图增加可控的双轴平移手势
- 把画线编辑从输入、拖拽、回显到保存统一为小数点后三位
- 把 `全部开启 / 全部关闭` 的语义改成“配置开关 + 运行态一起切换”

## 方案

### 推荐方案

- 普通左键拖拽继续保持当前横轴平移行为
- 新增 `Shift + 左键拖拽` 执行双轴平移：
  - 横向拖拽平移 `xRange`
  - 纵向拖拽平移 `yRange`
  - 一旦触发该手势，视口进入 `manual` Y 模式
- 图上拖拽取价改为 `toFixed(3)`，十字准星价格显示也同步为三位
- 批量开关按钮语义改为：
  - Guardian：保存 `buy_enabled` 后，再保存 `buy_active`
  - 止盈：保存 `manual_enabled` 后，再执行 `rearm`，让 `armed_levels` 跟随当前配置
- 行内单独的每层开关仍只改配置层，不暴露运行态编辑入口

### 不采用的方案

- 直接把普通拖拽改成默认双轴平移：会与画线拖拽抢占同一个手势
- 只改图上线条样式、不同步运行态：会让界面和后端真实状态继续不一致
- 为止盈单独新增前端“运行态批量编辑”入口：与“运行态只读”原则冲突

## 数据语义

- Guardian 批量开启/关闭：
  - 配置层：`buy_enabled`
  - 运行态：`buy_active`
- 止盈批量开启/关闭：
  - 配置层：`manual_enabled`
  - 运行态：`armed_levels`
- 运行态仍然不提供逐层手动编辑，只允许批量按钮在配置切换时顺带对齐

## 影响面

- 图表控制器：`morningglory/fqwebui/src/views/js/kline-slim-chart-controller.mjs`
- 图表渲染：`morningglory/fqwebui/src/views/js/kline-slim-chart-renderer.mjs`
- 价格面板保存链路：`morningglory/fqwebui/src/views/js/kline-slim-price-panel.mjs`
- 页面交互：`morningglory/fqwebui/src/views/js/kline-slim.js`
- 当前文档：`docs/current/modules/kline-webui.md`

## 测试策略

- 先补失败测试，分别覆盖：
  - `Shift + 左键拖拽` 后 `xRange` 和 `yRange` 都发生变化
  - 图上拖拽价格能保留三位小数
  - Guardian 批量按钮会额外写入 `buy_active`
  - 止盈批量按钮会在保存配置后执行 `rearm`
- 再做最小实现让测试转绿
- 最后跑相关前端测试与构建，确认无回归
