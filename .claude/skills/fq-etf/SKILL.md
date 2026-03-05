---
description: ETF 数据采集 - 保存 ETF 列表、日线、分钟线数据
trigger:
  - "ETF 数据"
  - "保存 ETF"
  - "etf.*save"
---

用户请求 ETF 数据采集相关操作。

## CLI 命令映射

| 操作 | CLI 命令 |
|------|----------|
| 保存所有数据 | `uv run -m freshquant etf save` |
| 保存 ETF 列表 | `uv run -m freshquant etf.list save` |
| 保存日线数据 | `uv run -m freshquant etf.day save` |
| 保存分钟线 | `uv run -m freshquant etf.min save` |

## 参数说明

- `-e, --engine`: 数据源引擎，默认 `tdx`

请根据用户请求执行对应的命令。
