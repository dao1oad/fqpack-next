# FreshQuant

Python 金融量化分析工具包，支持 A股、ETF、指数、债券、期货的多周期数据采集、缠论分析、回测与实盘交易。

## 开发命令

> **虚拟环境**：所有 Python 命令需在 `.venv` 虚拟环境中运行

| 命令 | 用途 |
|------|------|
| `python -m freshquant` | 启动 CLI (fqctl) |
| `install.bat` | 安装依赖（调用 install.py） |
| `pre-commit run --all-files` | 代码检查（black/mypy/isort） |
| `pytest` | 运行测试 |

### CLI 命令组

- `fqctl stock` - A股数据与信号
- `fqctl etf` - ETF 数据
- `fqctl index` - 指数数据
- `fqctl future` - 期货数据
- `fqctl bond` - 债券数据
- `fqctl {xt_asset,xt_trade,xt_order,xt_position}` - 实盘交易

## 架构概览

### 核心模块

**freshquant/** - 主包
- `analysis/` - 缠论分析
- `backtest/` - 回测框架（基于 Backtrader）
- `data/` - 多源数据采集（akshare/tdx/ldhq）
- `market_data/` - 行情下载与聚合
- `gateway/` - 交易网关（TDX 行情接口）
- `live_trading/` - 实盘交易
- `scheduler/` - 任务调度
- `screening/` - 选股策略框架
- `signal/` - 交易信号生成
- `cli.py` - 命令行入口

**morningglory/** - 微服务子项目
- `fqchan0X` - 缠论分析服务
- `fqdagster` - Dagster 工作流
- `fqwebui` - Web UI
- `fqxtrade` - MiniQMT 实盘对接

### 数据流

```
数据源 → market_data/ → MongoDB/Redis → signal/ → live_trading/ → MiniQMT
```

### 配置管理

- 主配置：`~/.freshquant/freshquant.yaml`
- 环境变量：`.env`（Docker 服务）
- 支持环境变量覆盖：`FRESHQUANT_<SECTION>__<KEY>`

## 代码规范

### 格式化

- Black：`--skip-string-normalization`
- isort：`--profile black`

### 类型检查

- mypy：`--ignore-missing-imports --disable-error-code=no-untyped-def`

### Git Hooks

- pre-commit：black/mypy/isort/pygrep-hooks

### 项目特有约定

- 数据结构强类型（避免未定义 dict）
- 虚拟环境：`.venv`
- 包管理：uv（禁止 pip/poetry/conda）
- 日志输出：`logs/`

## 技术栈

| 类别 | 依赖 |
|------|------|
| **数据** | pandas/polars/numpy/pymongo/redis |
| **采集** | akshare/tushare/yfinance |
| **分析** | quantstats/qlib/scipy/pyecharts |
| **Web** | FastAPI/Flask |
| **任务** | Dagster/Celery/APScheduler |
| **交易** | MiniQMT（本地客户端） |
| **测试** | pytest |

## 环境变量

| 变量 | 说明 |
|------|------|
| `FRESHQUANT_MONGODB__HOST` | MongoDB 主机 |
| `FRESHQUANT_REDIS__HOST` | Redis 主机 |
| `FRESHQUANT_DAGSTER__HOME` | Dagster 家目录 |
| `FRESHQUANT_TDX__HOME` | 通达信数据目录 |

## Docker 服务

| 服务 | 用途 |
|------|------|
| `fq_mongodb` | MongoDB |
| `fq_redis` | Redis |
| `fq_tdxhq` | TDX 行情服务 |

## 实盘对接

**架构**：Docker 监控服务 → Redis 队列 → 本地 fq_xtrade → MiniQMT

- 监控：`python -m freshquant.signal.astock.job.monitor_stock_zh_a_min`
- 下单：`python -m fxqtrade.xtquant.broker`
- 配置：数据库 `params` 表（key: `xtquant`/`monitor`）

## 按需参考文档

**开始任务前，请先阅读对应的 `docs/agent/` 文档**：

| 任务类型 | 参考文档 |
|---------|---------|
| 文档导航 | [docs/agent/index.md](docs/agent/index.md) |

### 模块说明

#### screening/ - 选股策略框架

统一的选股模块，提供策略模式接口。

**目录结构**：
```
freshquant/screening/
├── base/
│   └── strategy.py      # 抽象基类 ScreenStrategy
├── strategies/          # 策略实现
│   ├── chanlun_service.py   # 缠论信号（微服务）
│   ├── chanlun_la_hui.py    # 拉回中枢策略
│   └── clxs.py               # 垂直线段选股
└── output/             # 输出模块
    ├── database.py      # MongoDB 输出
    └── report.py        # HTML/控制台报表
```

**使用示例**：
```python
from freshquant.screening import ChanlunServiceStrategy

async def main():
    strategy = ChanlunServiceStrategy(periods=['60m', '1d'])
    results = await strategy.screen()
    # 结果自动保存到数据库

import asyncio
asyncio.run(main())
```

## 注意事项

1. 永远使用简体中文进行沟通和文档编写
