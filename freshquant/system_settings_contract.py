# -*- coding: utf-8 -*-
"""统一运行设置合同。

本模块是后端运行/业务配置的“唯一缺省值与枚举合同”：

- 不 import DB、pools、system_settings 或任何业务服务，避免循环依赖；
- 所有后端默认解析都引用本模块常量，不在其他 Python 模块重复书写
  50/60/100/200/500/240/20000 等同一配置的内联兜底；
- 文档会描述数值，但代码真值只在合同模块定义一次。

启动/基础设施配置（freshquant_bootstrap.yaml / bootstrap_config.py）不属于
本合同的覆盖范围，两者共同构成两层正式配置真值。
"""

from __future__ import annotations

# XTData 订阅/信号能力开关（Mongo monitor.xtdata.* 的缺省值）。
DEFAULT_XTDATA_TRADING_MODE = True
DEFAULT_XTDATA_SCREENING_MODE = False

# XTData 最大监控标的数。100 是券商订阅最大值的业务口径；
# 仅作为缺省值，不静默覆盖 Mongo 中显式保存的历史值，也不新增 HARD_CAP 钳制。
DEFAULT_XTDATA_MAX_SYMBOLS = 100

# consumer 进入 backlog / catchup 的队列深度阈值。
DEFAULT_XTDATA_QUEUE_BACKLOG_THRESHOLD = 500

# consumer 预热和窗口回填时保留的最大 bar 数。
DEFAULT_XTDATA_PREWARM_MAX_BARS = 20000

# broker 提交模式：normal 真实发单；observe_only 全链路落库但不提交券商。
DEFAULT_BROKER_SUBMIT_MODE = "normal"
VALID_BROKER_SUBMIT_MODES = frozenset({"normal", "observe_only"})

DEFAULT_XTQUANT_ACCOUNT_TYPE = "STOCK"

__all__ = [
    "DEFAULT_XTDATA_TRADING_MODE",
    "DEFAULT_XTDATA_SCREENING_MODE",
    "DEFAULT_XTDATA_MAX_SYMBOLS",
    "DEFAULT_XTDATA_QUEUE_BACKLOG_THRESHOLD",
    "DEFAULT_XTDATA_PREWARM_MAX_BARS",
    "DEFAULT_BROKER_SUBMIT_MODE",
    "VALID_BROKER_SUBMIT_MODES",
    "DEFAULT_XTQUANT_ACCOUNT_TYPE",
]
