from pathlib import Path
import sys
from types import SimpleNamespace

package_root = Path("morningglory/fqxtrade").resolve()
if str(package_root) not in sys.path:
    sys.path.insert(0, str(package_root))

from fqxtrade.xtquant.account import (
    resolve_broker_submit_mode,
    resolve_stock_account,
)


def test_resolve_stock_account_uses_configured_account_type():
    seen = {}

    class FakeStockAccount:
        def __init__(self, account_id, account_type="STOCK"):
            seen["account_id"] = account_id
            seen["account_type"] = account_type

    account, account_id, account_type = resolve_stock_account(
        settings_provider=SimpleNamespace(
            xtquant=SimpleNamespace(
                account="068000076370",
                account_type="CREDIT",
            )
        ),
        stock_account_cls=FakeStockAccount,
    )

    assert isinstance(account, FakeStockAccount)
    assert account_id == "068000076370"
    assert account_type == "CREDIT"
    assert seen == {
        "account_id": "068000076370",
        "account_type": "CREDIT",
    }


def test_resolve_stock_account_defaults_to_stock():
    seen = {}

    class FakeStockAccount:
        def __init__(self, account_id, account_type="STOCK"):
            seen["account_id"] = account_id
            seen["account_type"] = account_type

    account, account_id, account_type = resolve_stock_account(
        settings_provider=SimpleNamespace(
            xtquant=SimpleNamespace(account="068000076370")
        ),
        stock_account_cls=FakeStockAccount,
    )

    assert isinstance(account, FakeStockAccount)
    assert account_id == "068000076370"
    assert account_type == "STOCK"
    assert seen == {
        "account_id": "068000076370",
        "account_type": "STOCK",
    }


def test_resolve_broker_submit_mode_defaults_to_normal():
    assert (
        resolve_broker_submit_mode(
            settings_provider=SimpleNamespace(
                xtquant=SimpleNamespace(account="068000076370")
            )
        )
        == "normal"
    )


def test_resolve_broker_submit_mode_accepts_observe_only():
    assert (
        resolve_broker_submit_mode(
            settings_provider=SimpleNamespace(
                xtquant=SimpleNamespace(broker_submit_mode="observe_only")
            )
        )
        == "observe_only"
    )


def test_resolve_broker_submit_mode_normalizes_invalid_value_to_normal():
    assert (
        resolve_broker_submit_mode(
            settings_provider=SimpleNamespace(
                xtquant=SimpleNamespace(broker_submit_mode="paper_trade")
            )
        )
        == "normal"
    )
