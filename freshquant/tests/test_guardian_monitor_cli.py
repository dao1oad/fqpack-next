from pathlib import Path


def test_guardian_monitor_cli_only_exposes_event_mode():
    content = Path("freshquant/signal/astock/job/monitor_stock_zh_a_min.py").read_text(
        encoding="utf-8"
    )

    assert 'click.Choice(["event"])' in content
    assert '"poll"' not in content
