# distutils: language = c++
# cython: language_level = 3

from libcpp.vector cimport vector

def fq_clxs(
    int length,
    vector[float] high, vector[float] low, vector[float] open, vector[float] close,
    vector[float] vol,
    int wave_opt, int stretch_opt, int trend_opt, int model_opt):
    return clxs(length, high, low, open, close, vol, wave_opt, stretch_opt, trend_opt, model_opt);
