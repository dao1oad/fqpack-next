from __future__ import annotations

import math
import random

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


def _random_bars(seed: int, length: int = 700):
    rng = random.Random(seed)
    close = []
    value = 100.0
    for index in range(length):
        drift = 0.10 if (index // 45) % 2 == 0 else -0.10
        value = max(5.0, value + drift + rng.gauss(0, 1.4))
        close.append(value)

    open_, high, low, volume = [], [], [], []
    previous_close = close[0]
    for current_close in close:
        current_open = previous_close + rng.gauss(0, 0.55)
        open_.append(current_open)
        high.append(max(current_open, current_close) + abs(rng.gauss(0.25, 0.12)))
        low.append(min(current_open, current_close) - abs(rng.gauss(0.25, 0.12)))
        volume.append(1000.0 + rng.randrange(1000))
        previous_close = current_close
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


def test_batch_entrypoint_matches_legacy_zero_switch_models() -> None:
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

    explicit_batch = [
        list(row)
        for row in fqcopilot.fq_clxs_all(
            length, high, low, open_, close, volume, 1560, 0, 0, 0
        )
    ]
    assert explicit_batch == batch

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


def test_batch_entrypoint_matches_all_production_models() -> None:
    fqcopilot = _load_module()
    samples = [_bars(), *(_random_bars(seed) for seed in (1, 6, 9))]

    for sample_index, (high, low, open_, close, volume) in enumerate(samples):
        length = len(high)
        batch = [
            list(row)
            for row in fqcopilot.fq_clxs_all(
                length, high, low, open_, close, volume, 1560, 0, 0, 1
            )
        ]

        assert len(batch) == 18
        assert all(len(row) == length for row in batch)
        for model_id, actual in enumerate(batch, start=10000):
            expected = list(
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
            assert (
                actual == expected
            ), f"production parity failed for sample {sample_index}, {model_id}"


def test_legacy_and_production_profiles_remain_distinct() -> None:
    fqcopilot = _load_module()
    high, low, open_, close, volume = _random_bars(1)
    length = len(high)

    legacy = fqcopilot.fq_clxs_all(
        length, high, low, open_, close, volume, 1560, 0, 0, 0
    )
    production = fqcopilot.fq_clxs_all(
        length, high, low, open_, close, volume, 1560, 0, 0, 1
    )
    changed_models = {
        model_id
        for model_id, (legacy_row, production_row) in enumerate(zip(legacy, production))
        if list(legacy_row) != list(production_row)
    }

    assert changed_models == {1, 2, 5, 9, 10, 11, 12}


def test_batch_entrypoint_rejects_unknown_switch_profile() -> None:
    fqcopilot = _load_module()
    high, low, open_, close, volume = _bars(32)

    with pytest.raises(ValueError, match="switch_opt must be 0 or 1"):
        fqcopilot.fq_clxs_all(len(high), high, low, open_, close, volume, 1560, 0, 0, 2)


def test_batch_entrypoint_rejects_misaligned_bar_count() -> None:
    fqcopilot = _load_module()
    high, low, open_, close, volume = _bars(32)

    with pytest.raises(ValueError, match="length must match all OHLCV series"):
        fqcopilot.fq_clxs_all(
            len(high) - 1, high, low, open_, close, volume, 1560, 0, 0, 1
        )


@pytest.mark.parametrize(
    ("seed", "expected_code", "expected_trigger"),
    [
        (6, 1, "buy_engulfing"),
        (2, 2, "buy_normal_fractal_fallback"),
        (9, -1, "sell_engulfing"),
        (1, -2, "sell_normal_fractal_fallback"),
    ],
)
def test_s0002_entrypoint3_evidence_is_aligned_with_raw_signal(
    seed: int, expected_code: int, expected_trigger: str
) -> None:
    fqcopilot = _load_module()
    high, low, open_, close, volume = _random_bars(seed)
    length = len(high)

    evidence = fqcopilot.fq_s0002_entrypoint3_evidence(
        length, high, low, open_, close, volume, 1560, 0, 0, 1
    )
    codes = list(evidence["trigger_codes"])
    triggers = list(evidence["triggers"])
    signals = list(
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
            10002,
        )
    )

    assert len(codes) == length
    assert len(triggers) == length
    assert expected_code in codes
    assert expected_trigger in triggers
    for signal, code, trigger in zip(signals, codes, triggers):
        if code == 0:
            assert trigger is None
            continue
        assert int(signal) != 0
        assert abs(int(signal)) % 100 == 3
        assert (int(signal) > 0) == (code > 0)
