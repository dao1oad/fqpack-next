---
description: 实盘交易查询 - 查询资产、成交、委托、持仓记录（xt-asset/xt-trade/xt-order/xt-position）
trigger:
  - "资产查询"
  - "成交记录"
  - "委托记录"
  - "持仓"
  - "xt.*list"
---

用户请求实盘交易查询相关操作。

## CLI 命令映射

### 资产查询 (xt-asset)

| 操作 | CLI 命令 |
|------|----------|
| 列出资产 | `uv run -m freshquant xt-asset list` |
| 删除资产 | `uv run -m freshquant xt-asset rm --id ID` |

### 成交记录 (xt-trade)

| 操作 | CLI 命令 |
|------|----------|
| 列出成交 | `uv run -m freshquant xt-trade list [--code 代码] [--date 日期] [--fields 字段]` |
| 删除成交 | `uv run -m freshquant xt-trade rm [--id ID] [--code 代码]` |

### 委托记录 (xt-order)

| 操作 | CLI 命令 |
|------|----------|
| 列出委托 | `uv run -m freshquant xt-order list [--code 代码] [--date 日期] [--fields 字段]` |
| 删除委托 | `uv run -m freshquant xt-order rm [--id ID] [--code 代码]` |

### 持仓记录 (xt-position)

| 操作 | CLI 命令 |
|------|----------|
| 列出持仓 | `uv run -m freshquant xt-position list [--code 代码] [--account 账户] [--fields 字段]` |
| 复制持仓代码 | `uv run -m freshquant xt-position copy [--code 代码] [--account 账户]` |
| 删除持仓 | `uv run -m freshquant xt-position rm [--id ID] [--code 代码]` |

## 参数说明

- `--code`: 股票代码（支持带或不带后缀，如 300888 或 300888.SZ）
- `--date`: 日期（支持 YYYYMMDD、YYYY.MM.DD、YYYY-MM-DD 格式）
- `--fields`: 显示字段（逗号分隔，如 `id,stock_code,traded_price`）
- `--account`: 账户 ID
- `--id`: 记录 ID

## 默认显示字段

### 成交记录
`id, account_id, stock_code, name, order_id, order_type, traded_price, traded_volume, traded_amount, traded_time, strategy_name, source`

### 委托记录
`id, account_id, stock_code, name, order_id, order_type, price, order_volume, traded_price, traded_volume, order_time, strategy_name, source, price_type`

### 持仓记录
`id, account_id, stock_code, name, avg_price, volume, market_value, frozen_volume, can_use_volume, source`

## 使用示例

```bash
# 查询所有资产
uv run -m freshquant xt-asset list

# 查询指定股票的成交记录
uv run -m freshquant xt-trade list --code 300888

# 查询指定日期的委托记录
uv run -m freshquant xt-order list --date 20240128

# 查询持仓并复制代码
uv run -m freshquant xt-position copy
```

请根据用户请求执行对应的命令。
