from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

package_root = Path("morningglory/fqxtrade").resolve()
if str(package_root) not in sys.path:
    sys.path.insert(0, str(package_root))

from freshquant.market_data.xtdata import adj_refresh_service
from freshquant.market_data.xtdata import market_producer as producer
from freshquant.market_data.xtdata import pools
from freshquant.market_data.xtdata import strategy_consumer as consumer
from freshquant.system_settings_contract import (
    DEFAULT_BROKER_SUBMIT_MODE,
    DEFAULT_XTDATA_MAX_SYMBOLS,
    DEFAULT_XTDATA_PREWARM_MAX_BARS,
    DEFAULT_XTDATA_QUEUE_BACKLOG_THRESHOLD,
    VALID_BROKER_SUBMIT_MODES,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

GUARDED_FILES = (
    "freshquant/system_settings.py",
    "freshquant/market_data/xtdata/market_producer.py",
    "freshquant/market_data/xtdata/strategy_consumer.py",
    "freshquant/market_data/xtdata/pools.py",
    "freshquant/market_data/xtdata/adj_refresh_service.py",
    "freshquant/preset/params.py",
)

# 旧内联兜底签名：同一配置的缺省值只允许在合同模块定义一次。
# 使用词边界避免误伤 `5000.0) or 5000.0` 之类的合法兜底。
FORBIDDEN_INLINE_FALLBACK_RE = re.compile(r"\bor (50|60|200|240)(?![\d.])")


def test_contract_defaults_are_the_single_source_of_truth():
    assert DEFAULT_XTDATA_MAX_SYMBOLS == 100
    assert DEFAULT_XTDATA_QUEUE_BACKLOG_THRESHOLD == 500
    assert DEFAULT_XTDATA_PREWARM_MAX_BARS == 20000
    assert DEFAULT_BROKER_SUBMIT_MODE == "normal"
    assert VALID_BROKER_SUBMIT_MODES == frozenset({"normal", "observe_only"})


def test_producer_defaults_reference_contract():
    config = producer.resolve_producer_runtime_config(
        settings_provider=SimpleNamespace(monitor=SimpleNamespace()),
        bootstrap_provider=SimpleNamespace(xtdata=SimpleNamespace(port=58610)),
    )
    assert config["max_symbols"] == DEFAULT_XTDATA_MAX_SYMBOLS
    assert config["trading_mode"] is True
    assert config["screening_mode"] is False


def test_consumer_defaults_reference_contract():
    config = consumer.resolve_consumer_runtime_config(
        settings_provider=SimpleNamespace(monitor=SimpleNamespace())
    )
    assert config["max_symbols"] == DEFAULT_XTDATA_MAX_SYMBOLS
    assert config["queue_backlog_threshold"] == DEFAULT_XTDATA_QUEUE_BACKLOG_THRESHOLD
    assert config["prewarm_max_bars"] == DEFAULT_XTDATA_PREWARM_MAX_BARS


def test_pools_defaults_reference_contract():
    assert pools._normalize_symbol_limit(None) == DEFAULT_XTDATA_MAX_SYMBOLS
    assert pools._normalize_symbol_limit(0) == DEFAULT_XTDATA_MAX_SYMBOLS
    assert pools._normalize_symbol_limit(-5) == DEFAULT_XTDATA_MAX_SYMBOLS
    assert pools._normalize_symbol_limit("bad") == DEFAULT_XTDATA_MAX_SYMBOLS
    assert pools._normalize_symbol_limit(42) == 42


def test_adj_refresh_default_code_loader_references_contract(monkeypatch):
    captured = {}

    def fake_load_monitor_codes(*, trading_mode, screening_mode, max_symbols):
        captured.update(
            {
                "trading_mode": trading_mode,
                "screening_mode": screening_mode,
                "max_symbols": max_symbols,
            }
        )
        return []

    monkeypatch.setattr(
        adj_refresh_service,
        "load_monitor_codes",
        fake_load_monitor_codes,
    )
    monkeypatch.setattr(
        adj_refresh_service.system_settings,
        "monitor",
        SimpleNamespace(),
    )

    assert adj_refresh_service._default_code_loader() == []
    assert captured["max_symbols"] == DEFAULT_XTDATA_MAX_SYMBOLS
    assert captured["trading_mode"] is True
    assert captured["screening_mode"] is False


def test_broker_submit_mode_defaults_reference_contract():
    from fqxtrade.xtquant.account import resolve_broker_submit_mode

    assert (
        resolve_broker_submit_mode(
            settings_provider=SimpleNamespace(xtquant=SimpleNamespace())
        )
        == DEFAULT_BROKER_SUBMIT_MODE
    )
    assert (
        resolve_broker_submit_mode(
            settings_provider=SimpleNamespace(
                xtquant=SimpleNamespace(broker_submit_mode="observe_only")
            )
        )
        == "observe_only"
    )
    assert (
        resolve_broker_submit_mode(
            settings_provider=SimpleNamespace(
                xtquant=SimpleNamespace(broker_submit_mode="paper_trade")
            )
        )
        == DEFAULT_BROKER_SUBMIT_MODE
    )


def test_target_consumers_have_no_legacy_inline_default_fallbacks():
    for relative_path in GUARDED_FILES:
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert FORBIDDEN_INLINE_FALLBACK_RE.search(source) is None, (
            f"{relative_path} 仍包含旧内联兜底；"
            "缺省值应只引用 system_settings_contract"
        )
