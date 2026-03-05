---
description: 指数数据采集 - 保存指数列表、日线、分钟线数据
trigger:
  - "指数数据"
  - "保存指数"
  - "index.*save"
---

用户请求指数数据采集相关操作。

## CLI 命令映射

| 操作 | CLI 命令 |
|------|----------|
| 保存所有数据 | `uv run -m freshquant index save` |
| 保存指数列表 | `uv run -m freshquant index.list save` |
| 保存日线数据 | `uv run -m freshquant index.day save` |
| 保存分钟线 | `uv run -m freshquant index.min save` |

## 参数说明

- `-e, --engine`: 数据源引擎，默认 `tdx`

请根据用户请求执行对应的命令。
