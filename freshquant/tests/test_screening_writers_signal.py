# -*- coding: utf-8 -*-
"""screening writers 与 save_a_stock_signal 的接线测试（Issue #603 收尾）。

止损功能下线后 screening 结果不再携带止损价；save_signal 必须显式传
``stop_lose_price=None``，避免信号写库因缺必填位置参数被静默吞掉。
"""

from datetime import datetime

from freshquant.screening.base.strategy import ScreenResult
from freshquant.screening.writers.database import DatabaseOutput


def test_database_output_save_signal_wires_required_args(monkeypatch):
    captured = {}

    def fake_save_a_stock_signal(**kwargs):
        captured.update(kwargs)
        # 非 None 返回值跳过 on_signal 分支（strategy 为策略名，非对象）。
        return {"_id": "wired"}

    monkeypatch.setattr(
        "freshquant.screening.writers.database.save_a_stock_signal",
        fake_save_a_stock_signal,
    )
    result = ScreenResult(
        code="000001",
        name="平安银行",
        symbol="sz000001",
        period="1d",
        fire_time=datetime(2026, 3, 20, 9, 30),
        price=10.5,
        signal_type="CLXS_10001",
        tags=["s0001"],
    )

    DatabaseOutput.save_signal(result, strategy="screening")

    assert captured["code"] == "000001"
    assert captured["period"] == "1d"
    assert captured["price"] == 10.5
    assert captured["stop_lose_price"] is None
    assert captured["position"] == "BUY_LONG"
