---
description: 股票浏览与筛选 - 浏览股票K线图、缠论筛选（browse/screen）
trigger:
  - "K线图"
  - "浏览股票"
  - "股票.*筛选"
  - "缠论"
---

用户请求股票浏览与筛选相关操作。

## CLI 命令映射

### K线浏览

| 操作 | CLI 命令 |
|------|----------|
| 浏览K线图 | `uv run -m freshquant stock browse <代码> [-p 周期]` |

### 缠论筛选

| 操作 | CLI 命令 |
|------|----------|
| 股票筛选 | `uv run -m freshquant stock screen [模型] [-d 天数]` |

## 参数说明

### K线浏览

- `<代码>`: 股票代码（如 300888）
- `-p, --period`: K线周期，默认 `1m`
  - 支持：`1m`/`5m`/`15m`/`30m`/`1h`/`1d`

### 股票筛选

- `[模型]`: 筛选模型，默认 `clxs`
- `-d, --days`: 筛选天数，默认 1
- `-wo, --wave-opt`: 波浪参数，默认 1560
- `-so, --stretch-opt`: 伸展参数，默认 0
- `-to, --trend-opt`: 趋势参数，默认 1
- `-mo, --model-opt`: 模型参数，默认 10001
- `-c, --code`: 指定股票代码

## 使用示例

```bash
# 浏览股票K线图（默认1分钟）
uv run -m freshquant stock browse 300888

# 浏览日K线
uv run -m freshquant stock browse 300888 -p 1d

# 缠论筛选（默认参数）
uv run -m freshquant stock screen

# 筛选指定股票
uv run -m freshquant stock screen -c 300888
```

请根据用户请求执行对应的命令。
