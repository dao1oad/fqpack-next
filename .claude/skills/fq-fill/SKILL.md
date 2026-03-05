---
description: 成交记录管理 - 管理股票、期货、数字货币的成交记录（list/rm/import）
trigger:
  - "成交记录"
  - "fill.*list"
  - "导入成交"
---

用户请求成交记录管理相关操作。

## CLI 命令映射

### 股票成交 (stock.fill)

| 操作 | CLI 命令 |
|------|----------|
| 列出成交 | `uv run -m freshquant stock.fill list [-c 代码] [-dt 日期]` |
| 删除成交 | `uv run -m freshquant stock.fill rm [--id ID] [--code 代码]` |
| 导入成交 | `uv run -m freshquant stock.fill import {buy\|sell} [代码] -q 数量 -p 价格 [-dt 日期]` |

### 期货成交 (future.fill)

| 操作 | CLI 命令 |
|------|----------|
| 列出成交 | `uv run -m freshquant future.fill list [-c 合约] [-dt 日期]` |
| 删除成交 | `uv run -m freshquant future.fill rm [--id ID] [--instrument-id 合约]` |
| 导入成交 | `uv run -m freshquant future.fill import {buy_open\|sell_close\|sell_open\|buy_close} --instrument-id 合约 -v 数量 -p 价格 [-dt 日期]` |

### 数字货币成交 (digital.fill)

| 操作 | CLI 命令 |
|------|----------|
| 列出成交 | `uv run -m freshquant digital.fill list [-c 合约] [-dt 日期]` |
| 删除成交 | `uv run -m freshquant digital.fill rm [--id ID] [--instrument-id 合约]` |
| 导入成交 | `uv run -m freshquant digital.fill import {buy_open\|sell_close\|sell_open\|buy_close} --instrument-id 合约 -v 数量 -p 价格 [-dt 日期]` |

## 参数说明

- `-c, --code`: 股票代码
- `--instrument-id`: 期货/数字货币合约代码
- `-dt, --date`: 日期时间（支持多种格式）
- `--id`: 记录 ID
- `-q, --quantity`: 股票数量
- `-v, --volume`: 期货/数字货币数量
- `-p, --price`: 成交价格

## 日期格式支持

- `YYYY-MM-DD HH:MM:SS`
- `YYYY/MM/DD HH:MM:SS`
- `YYYYMMDD HHMMSS`
- `YYYY-MM-DD HH:MM`
- `YYYY-MM-DD`
- `HH:MM:SS`（使用当天日期）
- `HH:MM`

## 期货操作类型

- `buy_open`: 买入开仓
- `sell_close`: 卖出平仓
- `sell_open`: 卖出开仓
- `buy_close`: 买入平仓

请根据用户请求执行对应的命令。
