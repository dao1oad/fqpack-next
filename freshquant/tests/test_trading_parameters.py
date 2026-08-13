"""交易参数契约测试（步骤 8）：参数表由测试引用同一常量来源。"""

from __future__ import annotations

from datetime import timedelta

from freshquant.strategy.common import (
    DEFAULT_BUY_AMOUNT_EXPONENT,
    DEFAULT_TRADE_AMOUNT,
    MIN_BUY_AMOUNT_FLOOR,
)
from freshquant.strategy.guardian import (
    BUY_COOLDOWN_TIMEDELTA,
    SELL_COOLDOWN_TIMEDELTA,
)
from freshquant.strategy.guardian_buy_grid import DEFAULT_INITIAL_LOT_AMOUNT
from freshquant.strategy.guardian_ladder import EVENT_TTL_SECONDS
from freshquant.tpsl.service import _BASE_BUY_COOLDOWN_SECONDS
from freshquant.trading.board_lot import resolve_board_lot


def test_cooldown_parameters_match_docs_table():
    assert _BASE_BUY_COOLDOWN_SECONDS == 15 * 60
    assert BUY_COOLDOWN_TIMEDELTA == timedelta(minutes=15)
    assert SELL_COOLDOWN_TIMEDELTA == timedelta(minutes=15)


def test_board_lot_parameter_matches_docs_table():
    assert resolve_board_lot("000001") == 100
    assert resolve_board_lot("688001") == 200


def test_initial_lot_amount_parameter_matches_docs_table():
    assert DEFAULT_INITIAL_LOT_AMOUNT == 100000


def test_ladder_event_ttl_parameter_matches_docs_table():
    assert EVENT_TTL_SECONDS == 7 * 24 * 60 * 60


def test_mount_min_buy_exponent_parameters_match_docs_table():
    assert DEFAULT_TRADE_AMOUNT == 50000
    assert MIN_BUY_AMOUNT_FLOOR == 10000
    assert DEFAULT_BUY_AMOUNT_EXPONENT == 3.0
