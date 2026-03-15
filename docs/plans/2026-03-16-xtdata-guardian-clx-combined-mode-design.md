# XTData Guardian + CLX 联合模式设计

## 背景

当前 `monitor.xtdata.mode` 只有两种正式取值：

- `guardian_1m`
- `clx_15_30`

但这两个值在代码中承担了三种职责：

- 决定 XTData producer 的订阅池来源
- 决定 XTData consumer 是否启用 15/30 分钟 CLX 模型
- 决定 Guardian event 入口是否直接退出

这导致当前系统只能二选一运行：

- 选 `guardian_1m` 时，Guardian 主链可用，但 `stock_pools` 的 CLX 15/30 信号不会刷新
- 选 `clx_15_30` 时，CLX 15/30 可用，但 Guardian event 会直接退出

目标需求是把两条能力合并到同一个正式模式中运行，并保持 Guardian 池优先级高于 CLX 池。

## 目标

- 新增正式模式 `guardian_and_clx_15_30`
- 让联合模式同时具备：
  - Guardian 1 分钟事件链
  - CLX 15/30 分钟模型筛选
- 联合模式订阅池规则改为：
  - 先取 `guardian_1m` 池
  - 再补 `clx_15_30` 池
  - 去重后总数不超过 `monitor.xtdata.max_symbols`
- 兼容历史配置值 `clx_15_30`
  - 读取时按联合模式执行
  - 新写回和前端展示统一切换为 `guardian_and_clx_15_30`

## 非目标

- 不拆分成多套 producer / consumer 进程
- 不新增第二个配置字段来分别控制 Guardian 和 CLX
- 不改变 Guardian 的时间窗、阈值、网格、止盈止损等交易语义
- 不把 `stock_pools` 直接纳入 Guardian 的默认下单池

## 设计

### 1. 模式语义收口

在 `freshquant/market_data/xtdata/pools.py` 引入统一模式语义层：

- 规范模式：
  - `guardian_1m`
  - `guardian_and_clx_15_30`
- 兼容别名：
  - `clx_15_30 -> guardian_and_clx_15_30`
- 非法值：
  - 回退到 `guardian_1m`

同时提供能力判断接口，供不同运行链按能力而不是按裸字符串判断：

- 是否启用 Guardian
- 是否启用 CLX 15/30
- 当前模式应装载的订阅池

### 2. 联合池加载规则

`load_monitor_codes()` 的逻辑改成基于模式能力装配：

- `guardian_1m`
  - 只返回 `xt_positions + must_pool`
- `guardian_and_clx_15_30`
  - 先加载 `xt_positions + must_pool`
  - 再加载未过期 `stock_pools`
  - 按“guardian 在前、clx 在后”的顺序去重
  - 最终按 `monitor.xtdata.max_symbols` 截断

这样可以保证：

- Guardian 池优先保留
- CLX 池只做补足
- producer / consumer / 其它代码对池子规则保持单一真值

### 3. Producer 行为

`freshquant/market_data/xtdata/market_producer.py` 保持单实例：

- 配置仍只读取 `monitor.xtdata.mode`
- 订阅池改成调用新的联合池装载逻辑
- 联合模式下订阅“Guardian 优先 + CLX 补足”的并集

不引入第二套 producer，避免重复订阅、重复连接 XTData、重复心跳和重复排障入口。

### 4. Consumer 行为

`freshquant/market_data/xtdata/strategy_consumer.py` 保持单实例：

- 继续维护 1/5/15/30 分钟窗口
- CLX 模型开关从
  - `self.mode == "clx_15_30"`
  改为
  - “当前模式是否启用 CLX 能力”
- 联合模式下：
  - 1 分钟链路继续输出 Guardian 所需的 chanlun payload / pubsub
  - 15/30 分钟继续跑 CLX `10001-10012`
  - 命中的 CLX 信号继续写入 `realtime_screen_multi_period`

这样两条功能链共享同一个 consumer 的 prewarm、回填、窗口与 runtime observability。

### 5. Guardian event 行为

`freshquant/signal/astock/job/monitor_stock_zh_a_min.py` 当前只允许 `guardian_1m`。

改造后：

- 只要模式启用了 Guardian 能力，就允许 Guardian event 进程运行
- 联合模式下 Guardian 仍只关注 Guardian 池
  - `xt_positions + must_pool`
- Guardian 自身的交易规则保持不变：
  - timing
  - threshold
  - grid interval
  - cooldown
  - position management
  - submit / tpsl 相关链路

也就是说，联合模式是“同一套 XTData 订阅和 consumer 同时服务两条功能链”，不是“让 CLX-only 股票直接进入 Guardian 下单逻辑”。

### 6. 配置兼容与写回

后端读取时：

- `guardian_1m` 原样保留
- `clx_15_30` 归一为 `guardian_and_clx_15_30`
- `guardian_and_clx_15_30` 原样保留

后端写回和前端展示时：

- 只展示两个正式值：
  - `guardian_1m`
  - `guardian_and_clx_15_30`

这样线上已有 `clx_15_30` 文档或 Mongo 配置升级后不会失效，但新系统正式真值只保留新命名。

### 7. 初始化边界

`freshquant/initialize.py` 的 `run_runtime_bootstrap()` 目前会按当前 `monitor.xtdata.mode` 取池子，给 `instrument_strategy` 批量补默认 Guardian 策略。

联合模式下如果直接使用联合池，会把 CLX-only 的 `stock_pools` 标的也写成 Guardian 策略默认值，语义不对。

因此这里需要改成：

- 无论当前运行模式是什么
- Guardian 默认策略绑定都固定只基于 Guardian 池

这样运行期 bootstrap 不会把 CLX-only 标的误绑定到 Guardian。

## 影响面

后端核心：

- `freshquant/market_data/xtdata/pools.py`
- `freshquant/market_data/xtdata/market_producer.py`
- `freshquant/market_data/xtdata/strategy_consumer.py`
- `freshquant/signal/astock/job/monitor_stock_zh_a_min.py`

配置与初始化：

- `freshquant/system_settings.py`
- `freshquant/system_config_service.py`
- `freshquant/preset/params.py`
- `freshquant/initialize.py`

前端：

- `morningglory/fqwebui/src/views/SystemSettings.vue`
- 相关前端测试

文档：

- `docs/current/modules/market-data-xtdata.md`
- `docs/current/modules/strategy-guardian.md`
- `docs/current/reference/system-settings-params.md`
- 其它引用旧二选一语义的当前文档

## 测试策略

后端重点测试：

- 模式归一
  - `clx_15_30 -> guardian_and_clx_15_30`
- 联合池加载
  - guardian 优先
  - CLX 补足
  - 去重
  - 截断不超过 `max_symbols`
- producer runtime config / subscription pool
- consumer 联合模式下 15/30 CLX 开关
- Guardian event 联合模式下不退出
- `initialize.py` 联合模式下仍只用 Guardian 池初始化默认策略

前端重点测试：

- 系统设置页 mode 选项只剩两个正式值
- 设置汇总显示与 sanitizer 在新模式下保持正常

## 风险与规避

- 风险：联合池逻辑改变后，XTData 订阅数量可能更接近 `max_symbols`
  - 规避：明确 guardian 优先，CLX 只补足
- 风险：旧配置值 `clx_15_30` 被错误回退到 `guardian_1m`
  - 规避：在统一归一层显式兼容旧值
- 风险：联合模式下误把 CLX-only 标的带入 Guardian 默认策略绑定
  - 规避：`initialize.py` 固定按 Guardian 池做默认 Guardian 策略 bootstrap

## 验收口径

- `monitor.xtdata.mode=guardian_and_clx_15_30` 时：
  - producer 订阅联合池
  - 联合池中 Guardian 池优先
  - 总数不超过 `monitor.xtdata.max_symbols`
  - consumer 继续写 Guardian 依赖的 1 分钟链路
  - consumer 继续写 CLX 15/30 信号到 `realtime_screen_multi_period`
  - Guardian event 正常运行，不因模式退出
- 历史值 `clx_15_30` 读取后按联合模式执行
- 系统设置页与文档同步切到新正式命名
