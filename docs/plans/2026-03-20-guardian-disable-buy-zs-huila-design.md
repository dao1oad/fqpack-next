# Guardian 关闭 buy_zs_huila 事件响应设计

## 背景

当前 Guardian 正式事件链路会在 1 分钟 bar 更新后计算并保存 `buy_zs_huila`，随后继续进入 `stock_signals`、`StrategyGuardian.on_signal` 和 runtime trace。

本次要求是临时关闭 `buy_zs_huila`：

- 不再响应
- 页面不再可见
- runtime trace 也不再保留

## 目标

- `buy_zs_huila` 不再进入 Guardian 正式事件链
- 不再写入 `stock_signals`
- 不再触发 `StrategyGuardian.on_signal`
- 不再产生对应 runtime trace

## 非目标

- 不改动其他 5 类 Guardian 信号
- 不把该开关做成系统配置
- 不改动通用信号类型定义或其它非 Guardian 调用方

## 方案比较

### 方案 1：在 `calculate_guardian_signals_latest()` 里删除 `buy_zs_huila`

优点：

- 从源头移除，最彻底

缺点：

- 影响所有调用该 helper 的路径
- 变更面超出 Guardian 当前正式事件链

### 方案 2：在 `monitor_stock_zh_a_min.py` 里过滤 `buy_zs_huila`

优点：

- 只影响 Guardian 当前正式事件入口
- `stock_signals`、页面和 runtime trace 会一起消失
- 其余 5 类信号不受影响

缺点：

- 底层 helper 仍保留 `buy_zs_huila` 计算能力

### 方案 3：在 `save_a_stock_signal()` 或 `StrategyGuardian.on_signal()` 里拦截

优点：

- 代码改动集中

缺点：

- 容易留下部分副作用
- 如果在 `on_signal()` 拦截，页面和入库仍可能保留

## 结论

采用方案 2。

在 `freshquant/signal/astock/job/monitor_stock_zh_a_min.py` 中对 `calculate_guardian_signals_latest()` 的结果做最小过滤，直接跳过 `buy_zs_huila`，不调用 `save_a_stock_signal()`。

## 测试策略

- 新增 Guardian 事件模式回归测试
- 先证明当前实现会尝试保存 `buy_zs_huila`
- 再改实现并验证：
  - `buy_zs_huila` 被过滤
  - 其余信号仍继续保存

## 部署影响

- 改动位于 `freshquant/signal/**`
- 按部署矩阵需要重启 Guardian 运行面
