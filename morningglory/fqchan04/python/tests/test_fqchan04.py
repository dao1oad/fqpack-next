import inspect

import pytest

import fqchan04


DEFAULT_OPTIONS = {
    "bi_mode": 6,
    "force_wave_stick_count": 15,
    "allow_pivot_across": 0,
    "merge_non_complehensive_wave": 0,
}


def test_fq_recognise_bi_supports_close_and_legacy_options_position():
    parameters = list(inspect.signature(fqchan04.fq_recognise_bi).parameters)
    assert parameters == ["length", "h", "l", "c", "chan_options"]

    high = [104.0, 105.0, 101.0, 101.0]
    low = [100.0, 101.0, 97.0, 95.0]

    legacy = fqchan04.fq_recognise_bi(4, high, low, DEFAULT_OPTIONS)
    keyword = fqchan04.fq_recognise_bi(
        4, high, low, chan_options=DEFAULT_OPTIONS
    )
    assert legacy == keyword

    with pytest.raises(TypeError, match="provided twice"):
        fqchan04.fq_recognise_bi(
            4,
            high,
            low,
            DEFAULT_OPTIONS,
            chan_options=DEFAULT_OPTIONS,
        )


def test_fq_recognise_bi_distinguishes_normal_and_strong_top_confirmation():
    high = [104.0, 105.0, 101.0, 101.0]
    low = [100.0, 101.0, 97.0, 95.0]
    normal_close = [101.9, 104.7, 100.5, 96.3]
    strong_close = [101.9, 104.7, 97.4, 96.3]

    normal = fqchan04.fq_recognise_bi(4, high, low, normal_close)
    strong = fqchan04.fq_recognise_bi(4, high, low, strong_close)

    assert normal == [-3.0, 1.0, 11.0, -1.0]
    assert strong == [-3.0, 1.0, 12.0, -1.0]


def test_fq_recognise_bi_distinguishes_normal_and_strong_bottom_confirmation():
    high = [104.0, 103.0, 105.0, 106.0]
    low = [101.0, 100.0, 102.0, 102.0]
    normal_close = [102.6, 102.3, 102.5, 102.3]
    strong_close = [102.6, 102.3, 104.7, 102.3]

    normal = fqchan04.fq_recognise_bi(4, high, low, normal_close)
    strong = fqchan04.fq_recognise_bi(4, high, low, strong_close)

    assert normal == [-3.0, -1.0, -11.0, 1.0]
    assert strong == [-3.0, -1.0, -12.0, 1.0]


def test_single_bar_input_is_supported():
    bars = fqchan04.fq_recognise_std_bars(1, [10.0], [9.0])
    assert bars == [
        {
            "pos": 0,
            "start": 0,
            "end": 0,
            "high_vertex_raw_pos": 0,
            "low_vertex_raw_pos": 0,
            "high": 10.0,
            "low": 9.0,
            "high_high": 10.0,
            "low_low": 9.0,
            "direction": 1.0,
            "factor": 0.0,
            "factor_high": 10.0,
            "factor_low": 9.0,
            "factor_strong": 0.0,
        }
    ]
