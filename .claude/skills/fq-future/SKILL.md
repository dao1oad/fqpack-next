---
description: 期货数据采集 - 保存期货列表、日线、分钟线数据
trigger:
  - "期货数据"
  - "保存期货"
  - "future.*save"
---

用户请求期货数据采集相关操作。

## CLI 命令映射

| 操作 | CLI 命令 |
|------|----------|
| 保存所有数据 | `uv run -m freshquant future save` |
| 保存期货列表 | `uv run -m freshquant future.list save` |
| 保存日线数据 | `uv run -m freshquant future.day save` |
| 保存分钟线 | `uv run -m freshquant future.min save` |

## 参数说明

- `-e, --engine`: 数据源引擎，默认 `tdx`

请根据用户请求执行对应的命令。
