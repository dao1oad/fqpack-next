import pandas as pd
import pytest


def test_fullcalc_smoke():
    try:
        from freshquant.analysis.fullcalc_wrapper import run_fullcalc
    except Exception as e:  # pragma: no cover
        pytest.skip(f"fullcalc wrapper unavailable: {e}")

    df = pd.DataFrame(
        {
            "open": [1.0] * 20,
            "high": [1.1] * 20,
            "low": [0.9] * 20,
            "close": [1.0] * 20,
            "volume": [1.0] * 20,
        }
    )
    try:
        r = run_fullcalc(df, model_ids=[])
    except ModuleNotFoundError as e:
        pytest.skip(f"fullcalc extension not built: {e}")

    assert r["ok"] is True
    assert "bi" in r and len(r["bi"]) == 20
    assert r.get("signals") == []
