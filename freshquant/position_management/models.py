# -*- coding: utf-8 -*-

from dataclasses import dataclass, field

ALLOW_OPEN = "ALLOW_OPEN"
HOLDING_ONLY = "HOLDING_ONLY"
FORCE_PROFIT_REDUCE = "FORCE_PROFIT_REDUCE"


@dataclass
class PositionDecision:
    allowed: bool
    state: str
    reason_code: str
    decision_id: str
    reason_text: str = ""
    meta: dict = field(default_factory=dict)
