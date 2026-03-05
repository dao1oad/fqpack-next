---
description: A股数据采集 - 保存股票列表、板块、日线、分钟线、除权等数据
trigger:
  - "股票数据"
  - "保存股票"
  - "stock.*save"
  - "A股.*采集"
---

用户请求 A股数据采集相关操作。

## CLI 命令映射

| 操作 | CLI 命令 |
|------|----------|
| 保存所有数据 | `uv run -m freshquant stock save` |
| 保存股票列表 | `uv run -m freshquant stock.list save` |
| 保存板块信息 | `uv run -m freshquant stock.block save` |
| 保存日线数据 | `uv run -m freshquant stock.day save` |
| 保存分钟线 | `uv run -m freshquant stock.min save` |
| 保存除权数据 | `uv run -m freshquant stock.xdxr save` |

## 参数说明

- `-e, --engine`: 数据源引擎，默认 `tdx`（通达信）

## 使用示例

```bash
# 保存所有股票数据
uv run -m freshquant stock save

# 仅保存日线数据
uv run -m freshquant stock.day save
```

请根据用户请求执行对应的命令。
