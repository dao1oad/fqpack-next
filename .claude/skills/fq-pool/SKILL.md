---
description: 股票池管理 - 管理股票池、预选池、必买池（list/copy/import/rm/update）
trigger:
  - "股票池"
  - "预选池"
  - "必买.*池"
  - "pool.*list"
  - "must.*pool"
---

用户请求股票池管理相关操作。

## CLI 命令映射

### 股票池 (stock.pool)

| 操作 | CLI 命令 |
|------|----------|
| 列出股票池 | `uv run -m freshquant stock.pool list [--category 分类]` |
| 复制股票代码 | `uv run -m freshquant stock.pool copy [--category 分类]` |
| 导入股票 | `uv run -m freshquant stock.pool import [-f 文件] [-cat 分类] [-c 代码]` |
| 删除股票 | `uv run -m freshquant stock.pool rm [--category 分类] [--code 代码] [--id ID]` |

### 预选池 (stock.pre-pool)

| 操作 | CLI 命令 |
|------|----------|
| 列出预选池 | `uv run -m freshquant stock.pre-pool list [--category 分类]` |
| 复制股票代码 | `uv run -m freshquant stock.pre-pool copy [--category 分类]` |
| 导入股票 | `uv run -m freshquant stock.pre-pool import [-f 文件] [-cat 分类] [-c 代码]` |
| 删除股票 | `uv run -m freshquant stock.pre-pool rm [--category 分类] [--code 代码] [--id ID]` |

### 必买池 (stock.must-pool)

| 操作 | CLI 命令 |
|------|----------|
| 列出必买池 | `uv run -m freshquant stock.must-pool list [--category 分类]` |
| 复制股票代码 | `uv run -m freshquant stock.must-pool copy [--category 分类]` |
| 导入股票 | `uv run -m freshquant stock.must-pool import -c 代码 -cat 分类 --stop-loss-price 止损价 [-ila 首次金额] [-la 每次金额]` |
| 删除股票 | `uv run -m freshquant stock.must-pool rm [--category 分类] [--code 代码] [--id ID]` |
| 更新字段 | `uv run -m freshquant stock.must-pool update --code 代码 --set "字段=值"` |

## 参数说明

- `-f, --file`: 从文件导入
- `-c, --code`: 股票代码（支持多个或逗号分隔）
- `-cat, --category`: 分类名称
- `--stop-loss-price`: 止损价格（必买池必需）
- `-ila, --initial-lot-amount`: 首次买入金额
- `-la, --lot-amount`: 每次买入金额
- `--set`: 设置字段（格式：`field=value`）
- `-d, --days`: 有效天数，默认 89

## 可更新字段（必买池）

- `lot_amount`: 每次买入金额
- `initial_lot_amount`: 首次买入金额
- `forever`: 是否永久交易
- `disabled`: 是否禁用
- `stop_loss_price`: 止损价格
- `category`: 分类名称

## 使用示例

```bash
# 列出所有股票池
uv run -m freshquant stock.pool list

# 列出指定分类的股票池
uv run -m freshquant stock.pool list --category 自选股

# 导入股票到必买池
uv run -m freshquant stock.must-pool import -c 300888 -cat 科技 --stop-loss-price 100 -ila 10000 -la 5000

# 更新必买池股票
uv run -m freshquant stock.must-pool update --code 300888 --set "disabled=false" --set "lot_amount=6000"
```

请根据用户请求执行对应的命令。
