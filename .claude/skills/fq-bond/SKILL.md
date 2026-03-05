---
description: 债券数据采集 - 保存债券列表、日线、分钟线数据，国债逆回购
trigger:
  - "债券数据"
  - "保存债券"
  - "bond.*save"
  - "逆回购"
---

用户请求债券数据采集相关操作。

## CLI 命令映射

| 操作 | CLI 命令 |
|------|----------|
| 保存所有数据 | `uv run -m freshquant bond save` |
| 保存债券列表 | `uv run -m freshquant bond.list save` |
| 保存日线数据 | `uv run -m freshquant bond.day save` |
| 保存分钟线 | `uv run -m freshquant bond.min save` |
| 国债逆回购 | `uv run -m freshquant bond do reverse-repo` |

请根据用户请求执行对应的命令。
