# -*- coding: utf-8 -*-

from typing import Any

from freshquant.position_management.models import (
    ALLOW_OPEN,
    FORCE_PROFIT_REDUCE,
    HOLDING_ONLY,
)

PositionManagementRepository: Any = None
try:
    from freshquant.position_management.repository import (
        PositionManagementRepository as _PositionManagementRepository,
    )
except (
    ModuleNotFoundError
):  # pragma: no cover - allows lightweight imports in test contexts
    pass
else:
    PositionManagementRepository = _PositionManagementRepository

__all__ = [
    "ALLOW_OPEN",
    "FORCE_PROFIT_REDUCE",
    "HOLDING_ONLY",
    "PositionManagementRepository",
]
