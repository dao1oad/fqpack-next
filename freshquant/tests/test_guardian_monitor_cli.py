from pathlib import Path


def test_guardian_monitor_cli_only_exposes_event_mode():
    content = Path("freshquant/signal/astock/job/monitor_stock_zh_a_min.py").read_text(
        encoding="utf-8"
    )

    assert 'click.Choice(["event"])' in content
    assert '"poll"' not in content


def test_guardian_monitor_uses_guardian_capability_instead_of_strict_mode_match():
    content = Path("freshquant/signal/astock/job/monitor_stock_zh_a_min.py").read_text(
        encoding="utf-8"
    )

    assert "xtdata_mode_enables_guardian" in content
    assert 'expected guardian_1m. Exiting.' not in content


def test_guardian_monitor_disables_buy_zs_huila_signal():
    content = Path("freshquant/signal/astock/job/monitor_stock_zh_a_min.py").read_text(
        encoding="utf-8"
    )

    assert 'DISABLED_GUARDIAN_SIGNAL_TYPES = {"buy_zs_huila"}' in content
    assert "if s.signal_type in DISABLED_GUARDIAN_SIGNAL_TYPES:" in content
