from __future__ import annotations

import math

import pytest


def _load_module():
    try:
        import fqcopilot
    except Exception as exc:  # pragma: no cover - depends on local extension build
        pytest.skip(f"fqcopilot extension unavailable: {exc}")
    if not hasattr(fqcopilot, "fq_clxs_all"):
        pytest.skip("fqcopilot.fq_clxs_all is not available in the installed build")
    return fqcopilot


def _bars(length: int = 512):
    close = [
        100.0 + 0.08 * i + 2.5 * math.sin(i / 11.0) + 1.1 * math.sin(i / 3.0)
        for i in range(length)
    ]
    open_ = [x - 0.4 * math.sin(i / 5.0) for i, x in enumerate(close)]
    high = [
        max(o, c) + 0.8 + 0.2 * math.sin(i / 7.0)
        for i, (o, c) in enumerate(zip(open_, close))
    ]
    low = [
        min(o, c) - 0.8 - 0.2 * math.cos(i / 9.0)
        for i, (o, c) in enumerate(zip(open_, close))
    ]
    volume = [1000.0 + float((i * 37) % 200) for i in range(length)]
    return high, low, open_, close, volume


def test_all_18_production_models_return_finite_series() -> None:
    fqcopilot = _load_module()
    high, low, open_, close, volume = _bars()
    length = len(high)

    for model_id in range(10000, 10018):
        values = list(
            fqcopilot.fq_clxs(
                length,
                high,
                low,
                open_,
                close,
                volume,
                1560,
                0,
                0,
                model_id,
            )
        )
        assert len(values) == length
        assert all(math.isfinite(float(value)) for value in values)
        assert all(float(value).is_integer() for value in values)


def test_batch_entrypoint_matches_zero_switch_models() -> None:
    fqcopilot = _load_module()
    high, low, open_, close, volume = _bars()
    length = len(high)

    batch = [
        list(row)
        for row in fqcopilot.fq_clxs_all(
            length, high, low, open_, close, volume, 1560, 0, 0
        )
    ]
    assert len(batch) == 18
    assert all(len(row) == length for row in batch)

    # fq_clxs_all is the SALL/Func4 path and intentionally uses switch_opt=0.
    # Compare it with the corresponding low-four-digit model ids, not the
    # production single-model ids 10000..10017 (which select switch_opt=1).
    for model_id, expected in enumerate(batch):
        single = list(
            fqcopilot.fq_clxs(
                length,
                high,
                low,
                open_,
                close,
                volume,
                1560,
                0,
                0,
                model_id,
            )
        )
        assert single == expected
