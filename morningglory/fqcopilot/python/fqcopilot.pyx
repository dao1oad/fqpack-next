# distutils: language = c++
# cython: language_level = 3

from libcpp.vector cimport vector

def fq_clxs(
    int length,
    vector[float] high, vector[float] low, vector[float] open, vector[float] close,
    vector[float] vol,
    int wave_opt, int stretch_opt, int trend_opt, int model_opt):
    return clxs(length, high, low, open, close, vol, wave_opt, stretch_opt, trend_opt, model_opt);


def fq_clxs_all(
    int length,
    vector[float] high, vector[float] low, vector[float] open, vector[float] close,
    vector[float] vol,
    int wave_opt, int stretch_opt, int trend_opt):
    return clxs_all(length, high, low, open, close, vol, wave_opt, stretch_opt, trend_opt)


def fq_clxs_all_detailed(
    int length,
    vector[float] high, vector[float] low, vector[float] open, vector[float] close,
    vector[float] vol,
    int wave_opt, int stretch_opt, int trend_opt):
    """Return all raw model signals and direction-specific base trigger masks."""
    if length < 0:
        raise ValueError("length must be non-negative")
    if (high.size() != length or low.size() != length or
            open.size() != length or close.size() != length or
            vol.size() != length):
        raise ValueError("length must equal every OHLCV vector length")
    cdef vector[vector[int]] detailed = clxs_all_detailed_native(
        length, high, low, open, close, vol, wave_opt, stretch_opt, trend_opt)
    cdef int model_id
    signals_by_model = []
    for model_id in range(18):
        signals_by_model.append(detailed[model_id])
    return {
        "signals_by_model": signals_by_model,
        "buy_base_trigger_masks": detailed[18],
        "sell_base_trigger_masks": detailed[19],
    }
