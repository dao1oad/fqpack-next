# 系统设置参数（params）参考

## 当前定位

`freshquant.params` 是当前系统的 Mongo 系统设置集合，承载运行中的业务参数真值。

当前新系统实际使用的 `code` 只有 4 组：

- `notification`
- `monitor`
- `xtquant`
- `guardian`

当前库里已经清理掉的旧参数，不再属于正式配置面：

- `macd_config`
- `TEST_STAGE11`
- `dagster`
- `notification.webhook.dingtalk_1.*`
- `monitor.stock.periods`
- `monitor.stock.auto_open`
- `monitor.range`
- `xtquant.total_position`
- `xtquant.daily_threshold.*`
- `xtquant.is_force_stop`
- `guardian.stock.position_pct`
- `guardian.stock.auto_open`
- `guardian.stock.min_amount`

## 当前结构

每条文档结构固定为：

```json
{
  "code": "monitor",
  "value": {
    "xtdata": {
      "mode": "guardian_1m"
    }
  }
}
```

读取方式以 `queryParam("<code>.<path>")` 为主；缺字段时由代码默认值兜底。

## notification

用途：钉钉通知配置。

当前有效字段：

- `notification.webhook.dingtalk.private`
  - 含义：私密钉钉机器人 Webhook。
  - 用途：持仓内信号、must_pool 信号、市场数据告警默认发私密机器人。
  - 是否必填：否。
  - 空值行为：不报错，但对应通知不会真正发出。
- `notification.webhook.dingtalk.public`
  - 含义：公共钉钉机器人 Webhook。
  - 用途：部分公共买点通知会走这里。
  - 是否必填：否。
  - 空值行为：不报错，但对应通知不会真正发出。

当前没有新系统用途的邮件参数；不要再往 `notification` 下写 SMTP 或邮件接收人。

示例：

```json
{
  "code": "notification",
  "value": {
    "webhook": {
      "dingtalk": {
        "private": "https://oapi.dingtalk.com/robot/send?access_token=***",
        "public": "https://oapi.dingtalk.com/robot/send?access_token=***"
      }
    }
  }
}
```

## monitor

用途：XTData 监控范围、消费节流和预热参数。

### monitor.xtdata.mode

- 含义：XTData 实时监控模式。
- 类型：`str`
- 正式支持值：
  - `guardian_1m`
  - `guardian_and_clx_15_30`
- 缺省值：`guardian_1m`
- 非法值行为：自动归一到 `guardian_1m`
- 兼容读取值：
  - `clx_15_30`
    - 读取时自动归一到 `guardian_and_clx_15_30`
- 模式语义：
  - `guardian_1m`
    - 监控集合 = `xt_positions + must_pool`
    - Guardian event 正常运行
    - 不跑 `stock_pools` 的 15/30 分钟 CLX 补充池
  - `guardian_and_clx_15_30`
    - 监控集合 = Guardian 池优先 + 未过期 `stock_pools` 补足
    - Guardian event 正常运行
    - XTData consumer 会继续跑 15/30 分钟 CLX 模型并写 `realtime_screen_multi_period`

### monitor.xtdata.max_symbols

- 含义：XTData 最大监控标的数。
- 类型：`int`
- 是否必填：否
- 缺省值：`50`
- 非法值行为：小于等于 `0` 或无法解析时回退到 `50`

### monitor.xtdata.queue_backlog_threshold

- 含义：consumer 进入 backlog / catchup 的阈值。
- 类型：`int`
- 是否必填：否
- 缺省值：`200`
- 用途：控制 `strategy_consumer` 在队列积压时的处理策略

### monitor.xtdata.prewarm.max_bars

- 含义：consumer 预热和窗口回填时保留的最大 bar 数。
- 类型：`int`
- 是否必填：否
- 缺省值：`20000`

示例：

```json
{
  "code": "monitor",
  "value": {
    "xtdata": {
      "mode": "guardian_1m",
      "max_symbols": 50,
      "queue_backlog_threshold": 200,
      "prewarm": {
        "max_bars": 20000
      }
    }
  }
}
```

## xtquant

用途：XT 客户端连接、broker 提交模式和普通融资负债自动还款。

### xtquant.path

- 含义：MiniQMT `userdata_mini` 路径。
- 类型：`str`
- 是否必填：是
- 用途：
  - XT broker
  - 仓位管理信用查询
  - `ensure_xt_mini_qmt`

### xtquant.account

- 含义：XT 交易账号。
- 类型：`str`
- 是否必填：是
- 用途：
  - XT broker
  - 仓位管理
  - Gantt 读模型

### xtquant.account_type

- 含义：XT 账户类型。
- 类型：`str`
- 支持值：
  - `STOCK`
  - `CREDIT`
- 缺省值：`STOCK`
- 当前主链建议值：`CREDIT`
  - 原因：仓位管理信用详情查询要求必须是 `CREDIT`

### xtquant.broker_submit_mode

- 含义：broker 提交模式。
- 类型：`str`
- 支持值：
  - `normal`
  - `observe_only`
- 缺省值：`normal`
- 非法值行为：自动回退到 `normal`
- 语义：
  - `normal`
    - 正常发单
  - `observe_only`
    - 全链路落库和展示，但不真正提交到 broker

### xtquant.auto_repay.enabled

- 含义：是否开启 XT 自动还款。
- 类型：`bool`
- 是否必填：否
- 缺省值：`true`
- 生效前提：
  - `xtquant.account_type=CREDIT`
- 运行语义：
  - `true`
    - `xt_auto_repay.worker` 会参与盘中低频巡检与 `14:55 / 15:05` 固定时点还款判断
  - `false`
    - worker 只记录 skip 事件，不会进入还款候选

### xtquant.auto_repay.reserve_cash

- 含义：自动还款留底现金。
- 类型：`float`
- 是否必填：否
- 缺省值：`5000`
- 生效前提：
  - `xtquant.account_type=CREDIT`
- 运行语义：
  - 只有 `m_dAvailable > reserve_cash` 才会进入自动还款候选
  - 候选还款额固定按 `min(m_dAvailable - reserve_cash, m_dFinDebt)` 计算
  - 当前只作用于普通融资负债，不作用于专项负债

示例：

```json
{
  "code": "xtquant",
  "value": {
    "path": "D:\\迅投极速策略交易系统交易终端 东海证券QMT实盘\\userdata_mini",
    "account": "068000076370",
    "account_type": "CREDIT",
    "broker_submit_mode": "observe_only",
    "auto_repay": {
      "enabled": true,
      "reserve_cash": 5000
    }
  }
}
```

## guardian

用途：Guardian 主链的交易金额、阈值和网格间距配置。

### guardian.stock.lot_amount

- 含义：默认单次买入金额。
- 类型：`float`
- 是否必填：否
- 缺省值：`50000`
- 实际优先级：
  - `instrument_strategy.lot_amount`
  - `must_pool.lot_amount`
  - `guardian.stock.lot_amount`

### guardian.stock.threshold

- 含义：Guardian 买卖阈值配置。
- 类型：`object`
- 是否必填：否
- 缺省结构：

```json
{
  "mode": "percent",
  "percent": 1
}
```

- 支持模式：
  - `percent`
    - 字段：`percent`
  - `atr`
    - 字段：`atr.period`
    - 字段：`atr.multiplier`

### guardian.stock.grid_interval

- 含义：Guardian 卖出网格间距配置。
- 类型：`object`
- 是否必填：否
- 缺省结构：

```json
{
  "mode": "percent",
  "percent": 3
}
```

- 支持模式：
  - `percent`
    - 字段：`percent`
  - `atr`
    - 字段：`atr.period`
    - 字段：`atr.multiplier`

示例：

```json
{
  "code": "guardian",
  "value": {
    "stock": {
      "lot_amount": 50000.0,
      "threshold": {
        "mode": "percent",
        "percent": 1
      },
      "grid_interval": {
        "mode": "percent",
        "percent": 3
      }
    }
  }
}
```

## 当前建议

- `params` 只保留 `notification / monitor / xtquant / guardian`
- 连接类基础设施参数不要再写入 `params`
  - 例如 `mongodb.*`
  - `redis.*`
  - `tdx.*`
- 标的级覆盖配置继续放在 `instrument_strategy`
- 仓位管理阈值继续放在 `pm_configs`

## 相关文档

- [当前配置](../configuration.md)
- [当前存储](../storage.md)
- [股票池与持仓](./stock-pools-and-positions.md)
