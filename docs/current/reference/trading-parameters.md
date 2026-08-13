# 交易参数表（步骤 8：参数表由测试引用同一常量来源）

> 本表是交易参数的单一文档真值。数值来源于代码常量/配置键，测试通过
> `freshquant/tests/test_trading_parameters.py` 引用同一来源断言，防止
> 文档与实现漂移（路线步骤 8，A7/B4/S1 口径裁定后）。

| 参数 | 默认值 | 代码来源 | 说明 |
| --- | --- | --- | --- |
| 买入线冷却 `base_buy:<code>` | 15 分钟 | `freshquant.tpsl.service._BASE_BUY_COOLDOWN_SECONDS` | 买入线提交侧独立冷却 |
| 单标的买入冷却 `buy:<code>` | 15 分钟 | `freshquant.strategy.guardian.BUY_COOLDOWN_TIMEDELTA` | 提交成功后写入；D2 后唯一首开冷却 |
| 卖出冷却 `sell:<code>` | 15 分钟 | `freshquant.strategy.guardian.SELL_COOLDOWN_TIMEDELTA` | Guardian 卖出冷却 |
| 整手（board lot） | 100 股（科创板 200 股 + 1 股递增） | `freshquant.trading.board_lot.resolve_board_lot` | 步骤 7 收口唯一来源 |
| 初始网格金额 | 100000 | `freshquant.strategy.guardian_buy_grid.DEFAULT_INITIAL_LOT_AMOUNT` | 首开/做T 初始金额默认 |
| mount（卖出金额门槛） | 50000 | `freshquant.strategy.common.DEFAULT_TRADE_AMOUNT` | 可卖金额 < mount 不卖 |
| 最小买入金额 | 10000 | `freshquant.strategy.common.MIN_BUY_AMOUNT_FLOOR`（配置键 `params.guardian.stock.min_buy_amount`） | 所有买入路径门槛，下限钳制 |
| 做T 金额指数 | 3（范围 1–5） | `freshquant.strategy.common.DEFAULT_BUY_AMOUNT_EXPONENT`（配置键 `params.guardian.stock.buy_amount_exponent`） | B = R × t^n |
| 档位消耗（止盈） | 提交关本档 / 成交关本档及更低档 | `guardian_ladder.on_takeprofit_trigger` / `on_takeprofit_fill` | A7 以代码为真值；无可提交数量保留档位（B4/S1） |
| 阶梯事件保留期 | 7 天 | `freshquant.strategy.guardian_ladder.EVENT_TTL_SECONDS` | guardian_ladder_events TTL |
