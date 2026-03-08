# XTData 默认模式改为 guardian_1m Design

## 目标

将 `monitor.xtdata.mode` 的缺省语义从 `clx_15_30` 改为 `guardian_1m`，并收口为单一解析点，避免 Producer、Consumer、Guardian 与初始化脚本各自维护不同默认值。

## 方案

- 在 XTData 现有模块中新增统一的 mode 标准化 helper
- helper 只接受两个合法值：`guardian_1m`、`clx_15_30`
- 对缺省、空字符串和非法值统一回退到 `guardian_1m`
- Producer / Consumer / Guardian / `preset/params.py` 全部改为复用该 helper 或共享默认常量

## 边界

- 显式设置 `clx_15_30` 的实例保持不变
- 不修改 `load_monitor_codes()` 的池选择逻辑
- 不自动补 `stock_pools`

## 验证

- 单测覆盖默认值标准化
- 单测覆盖 `preset/params.py` 的初始化默认写入
- 运行时通过宿主机 Producer/Consumer 重启后观察 `prewarm codes` 是否从 0 变为持仓数量
