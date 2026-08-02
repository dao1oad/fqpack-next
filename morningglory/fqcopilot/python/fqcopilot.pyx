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
    int wave_opt, int stretch_opt, int trend_opt, int switch_opt=0):
    """Calculate all 18 models; 0 is legacy_sall_v0 and 1 is production_v1."""
    if switch_opt != 0 and switch_opt != 1:
        raise ValueError("switch_opt must be 0 or 1")
    return clxs_all(
        length, high, low, open, close, vol,
        wave_opt, stretch_opt, trend_opt, switch_opt)


def fq_s0002_entrypoint3_evidence(
    int length,
    vector[float] high, vector[float] low, vector[float] open, vector[float] close,
    vector[float] vol,
    int wave_opt, int stretch_opt, int trend_opt, int switch_opt):
    """Return bar-aligned structural trigger evidence for S0002 entrypoint 3.

    Trigger codes are +1 buy engulfing, +2 buy normal-fractal fallback,
    -1 sell engulfing, and -2 sell normal-fractal fallback. Zero means that
    entrypoint 3 did not trigger or its origin is unknown. Business decoders
    must persist model_id and the raw signal independently.
    """
    if switch_opt != 0 and switch_opt != 1:
        raise ValueError("switch_opt must be 0 or 1")

    cdef vector[int] evidence = clxs_s0002_entrypoint3_evidence(
        length, high, low, open, close, vol,
        wave_opt, stretch_opt, trend_opt, switch_opt)
    trigger_codes = [code for code in evidence]
    trigger_names = {
        1: "buy_engulfing",
        2: "buy_normal_fractal_fallback",
        -1: "sell_engulfing",
        -2: "sell_normal_fractal_fallback",
    }
    return {
        "trigger_codes": trigger_codes,
        "triggers": [trigger_names.get(code) for code in trigger_codes],
    }
