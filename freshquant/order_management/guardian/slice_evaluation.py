# -*- coding: utf-8 -*-
"""Guardian 逐切片卖出判定领域函数。

Guardian 与 Position Review 必须共享这一份逐切片止盈语义，禁止各自复制
“最低切片全局门槛 + 成本价比较”算法。价格比较统一走 ``Decimal`` + 最小价位
（0.01）规范化，消除二进制浮点边界（例如 ``21.580000000000002 > 21.58``）。

语义真值（与 bug 文档/方案 v4 对齐）：

- 每个 Guardian slice 独立计算卖出阈值：
  - percent 模式：``threshold = guardian_price * (1 + percent / 100)``
  - atr 模式：``threshold = guardian_price + threshold_delta``（同一历史 ATR
    参数对每个 slice 使用，不允许只对最低 slice 做一次全局 gate）
- 可卖判定：``normalized_signal_price >= threshold_price``，价格统一先按
  ``0.01`` 最小价位规范化（ROUND_HALF_UP），阈值保留 ``0.0001`` 精度。
- 返回值同时给出 ``eligible_slices``、``raw_quantity`` 与逐 slice 的
  ``threshold_evidence``，供 Trace / Position Review / simulate CLI 使用。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

PRICE_TICK = Decimal("0.01")
THRESHOLD_PRECISION = Decimal("0.0001")
DEFAULT_THRESHOLD_MODE = "percent"
DEFAULT_THRESHOLD_PERCENT = 1


def to_decimal(value: Any) -> Decimal:
    """把价格/配置值稳定转成 Decimal，float 先走 ``str`` 避免二进制噪声。"""

    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def normalize_price_to_tick(value: Any) -> Decimal:
    """把价格规范化为 A 股最小价位（0.01，ROUND_HALF_UP）。"""

    return to_decimal(value).quantize(PRICE_TICK, rounding=ROUND_HALF_UP)


def build_slice_threshold(
    guardian_price: Any,
    threshold_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """按配置计算单个 slice 的独立止盈阈值。"""

    config = dict(threshold_config or {})
    mode = str(config.get("mode") or DEFAULT_THRESHOLD_MODE).strip().lower()
    base_price = to_decimal(guardian_price)
    if mode == "atr":
        delta = to_decimal(config.get("threshold_delta"))
        threshold_price = (base_price + delta).quantize(
            THRESHOLD_PRECISION,
            rounding=ROUND_HALF_UP,
        )
        return {
            "threshold_mode": "atr",
            "threshold_ratio": None,
            "threshold_delta": str(delta),
            "threshold_price": str(threshold_price),
            "threshold_price_normalized": str(
                threshold_price.quantize(PRICE_TICK, rounding=ROUND_HALF_UP)
            ),
        }

    percent = to_decimal(config.get("percent", DEFAULT_THRESHOLD_PERCENT))
    threshold_price = (base_price * (1 + percent / 100)).quantize(
        THRESHOLD_PRECISION,
        rounding=ROUND_HALF_UP,
    )
    return {
        "threshold_mode": "percent",
        "threshold_ratio": str((percent / 100).quantize(THRESHOLD_PRECISION)),
        "threshold_delta": None,
        "threshold_price": str(threshold_price),
        "threshold_price_normalized": str(
            threshold_price.quantize(PRICE_TICK, rounding=ROUND_HALF_UP)
        ),
    }


def resolve_sell_threshold_config(
    threshold_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """从 ``eval_stock_threshold_price`` 的结果派生逐 slice 阈值配置。

    percent 模式直接使用配置百分比；ATR 模式把 ``top_river - base`` 的增量
    作为每个 slice 独立使用的 ``threshold_delta``（不允许只对最低 slice 做
    一次全局 gate）。
    """

    threshold_result = dict(threshold_result or {})
    config = dict(threshold_result.get("config") or {})
    mode = str(config.get("mode") or DEFAULT_THRESHOLD_MODE).strip().lower()
    if mode == "atr":
        base_price = to_decimal(threshold_result.get("base_price") or 0)
        top_river_price = to_decimal(threshold_result.get("top_river_price") or 0)
        return {
            "mode": "atr",
            "threshold_delta": str(top_river_price - base_price),
        }
    return {
        "mode": "percent",
        "percent": float(config.get("percent", DEFAULT_THRESHOLD_PERCENT)),
    }


def evaluate_guardian_sell_slices(
    slices: list[dict[str, Any]],
    signal_price: Any,
    threshold_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """逐 slice 独立判定卖出资格，返回可卖数量与逐 slice 阈值证据。

    输入 ``slices`` 接受两类结构（同一领域函数被 Guardian 的 arranged fill、
    Position Review 的重放 inventory、simulate CLI 的 slice 文档共用）：

    - slice 文档：``guardian_price / remaining_quantity``
    - arranged fill 行：``price / quantity``

    边界规则：``normalized_signal_price >= threshold_price``（阈值保留 4 位小数，
    信号价先按 0.01 规范化），不依赖二进制 float 的 ``>``。
    """

    normalized_signal = normalize_price_to_tick(signal_price)
    eligible_slices: list[dict[str, Any]] = []
    threshold_evidence: list[dict[str, Any]] = []
    raw_quantity = 0

    for raw_item in list(slices or []):
        item = dict(raw_item or {})
        guardian_price = item.get("guardian_price")
        if guardian_price is None:
            guardian_price = item.get("price")
        remaining_quantity = item.get("remaining_quantity")
        if remaining_quantity is None:
            remaining_quantity = item.get("quantity")
        if guardian_price in {None, ""}:
            continue
        try:
            remaining = int(remaining_quantity or 0)
        except (TypeError, ValueError):
            remaining = 0
        if remaining <= 0:
            continue

        entry_id = str(item.get("entry_id") or "").strip() or None
        entry_slice_id = str(item.get("entry_slice_id") or "").strip() or None
        guardian_decimal = normalize_price_to_tick(guardian_price)
        threshold = build_slice_threshold(guardian_decimal, threshold_config)
        threshold_price = to_decimal(threshold["threshold_price"])
        eligible = normalized_signal >= threshold_price

        evidence: dict[str, Any] = {
            "entry_id": entry_id,
            "entry_slice_id": entry_slice_id,
            "guardian_price": str(guardian_decimal),
            "guardian_price_normalized": str(guardian_decimal),
            "threshold_mode": threshold["threshold_mode"],
            "threshold_ratio": threshold["threshold_ratio"],
            "threshold_delta": threshold["threshold_delta"],
            "threshold_price": threshold["threshold_price"],
            "threshold_price_normalized": threshold["threshold_price_normalized"],
            "signal_price_normalized": str(normalized_signal),
            "eligible": bool(eligible),
            "remaining_quantity": remaining,
            "eligible_quantity": remaining if eligible else 0,
        }
        threshold_evidence.append(evidence)
        if eligible:
            eligible_slices.append(evidence)
            raw_quantity += remaining

    eligible_slices.sort(
        key=lambda item: (
            to_decimal(item.get("guardian_price_normalized") or "0"),
            item.get("entry_slice_id") or "",
        )
    )
    threshold_evidence.sort(
        key=lambda item: (
            to_decimal(item.get("guardian_price_normalized") or "0"),
            item.get("entry_slice_id") or "",
        )
    )
    return {
        "raw_quantity": int(raw_quantity),
        "eligible_slices": eligible_slices,
        "threshold_evidence": threshold_evidence,
        "normalization": {
            "price_tick": str(PRICE_TICK),
            "signal_price_raw": str(to_decimal(signal_price)),
            "signal_price_normalized": str(normalized_signal),
            "comparison": "normalized_signal >= threshold_price",
        },
    }


__all__ = [
    "DEFAULT_THRESHOLD_MODE",
    "DEFAULT_THRESHOLD_PERCENT",
    "PRICE_TICK",
    "THRESHOLD_PRECISION",
    "build_slice_threshold",
    "evaluate_guardian_sell_slices",
    "normalize_price_to_tick",
    "resolve_sell_threshold_config",
    "to_decimal",
]
