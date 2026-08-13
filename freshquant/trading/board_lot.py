# -*- coding: utf-8 -*-
"""整手（board lot）解析 helper（根⑤，路线步骤 7）。

交易参数调用点的整手股数统一经本模块解析，不再散落 100/200 字面量。
key = (exchange, board, security_type)；科创板（STAR，代码 688/689 开头）按
上交所规则建模：买入 ≥200 股、以 1 股递增；其余 A 股按 100 股整手。
"""

from __future__ import annotations

_STAR_BOARD_MARKERS = {"科创", "star", "kcb"}
_STAR_CODE_PREFIXES = ("688", "689")


def _is_star_market(
    *,
    code: str = "",
    exchange: str = "",
    board: str = "",
    security_type: str = "",
) -> bool:
    board_text = str(board or "").strip().lower()
    if board_text.startswith("科创") or board_text in _STAR_BOARD_MARKERS:
        return True
    security_type_text = str(security_type or "").strip().lower()
    if (
        security_type_text.startswith("科创")
        or security_type_text in _STAR_BOARD_MARKERS
    ):
        return True
    exchange_text = str(exchange or "").strip().upper()
    code_text = str(code or "").strip().upper()
    digits = "".join(ch for ch in code_text if ch.isdigit())
    if exchange_text in {"SH", "SSE"} and digits.startswith(_STAR_CODE_PREFIXES):
        return True
    return digits.startswith(_STAR_CODE_PREFIXES)


def resolve_board_lot(
    code: str = "",
    *,
    exchange: str = "",
    board: str = "",
    security_type: str = "",
) -> int:
    """返回整手基准股数：科创板 200（1 股递增），其余 A 股 100（整手）。"""

    return (
        200
        if _is_star_market(
            code=code,
            exchange=exchange,
            board=board,
            security_type=security_type,
        )
        else 100
    )


def is_board_lot_quantity(
    quantity,
    *,
    code: str = "",
    exchange: str = "",
    board: str = "",
    security_type: str = "",
) -> bool:
    """数量是否合法：
    - 科创板（STAR）：≥200 股（1 股递增）；
    - 其余 A 股：100 股整手整数倍（>0）。
    """

    try:
        normalized = int(quantity)
    except (TypeError, ValueError):
        return False
    if normalized <= 0:
        return False
    if _is_star_market(
        code=code,
        exchange=exchange,
        board=board,
        security_type=security_type,
    ):
        return normalized >= 200
    return normalized % 100 == 0


def floor_to_board_lot(
    quantity,
    *,
    code: str = "",
    exchange: str = "",
    board: str = "",
    security_type: str = "",
) -> int:
    """卖出可提交数量：
    - 科创板（STAR）：≥200 股保持原值（1 股递增，不取整），<200 → 0；
    - 其余 A 股：向下取整到 100 股整手倍数。
    """

    try:
        value = max(int(quantity), 0)
    except (TypeError, ValueError):
        return 0
    if _is_star_market(
        code=code,
        exchange=exchange,
        board=board,
        security_type=security_type,
    ):
        return value if value >= 200 else 0
    return value - (value % 100)


def quantity_for_amount(
    amount,
    price,
    *,
    code: str = "",
    exchange: str = "",
    board: str = "",
    security_type: str = "",
) -> int:
    """金额→可买数量：
    - 科创板（STAR）：floor(amount/price)，≥200 保持（1 股递增），<200 → 0；
    - 其余 A 股：floor(amount / price / 100) * 100。
    """

    try:
        amount_value = float(amount)
        price_value = float(price)
    except (TypeError, ValueError):
        return 0
    if amount_value <= 0 or price_value <= 0:
        return 0
    raw_quantity = int(amount_value / price_value)
    if _is_star_market(
        code=code,
        exchange=exchange,
        board=board,
        security_type=security_type,
    ):
        return raw_quantity if raw_quantity >= 200 else 0
    return raw_quantity - (raw_quantity % 100)
