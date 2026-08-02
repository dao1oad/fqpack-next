# distutils: language = c++
# cython: language_level = 3

from libcpp cimport bool, int
from libcpp.vector cimport vector


cdef extern from "func_set.cpp":
    pass

cdef extern from "func_set.h":
    vector[float] clxs(
        int length,
        vector[float] high, vector[float] low, vector[float] open, vector[float] close,
        vector[float] vol,
        int wave_opt, int stretch_opt, int trend_opt, int model_opt)

    vector[vector[float]] clxs_all(
        int length,
        vector[float] high, vector[float] low, vector[float] open, vector[float] close,
        vector[float] vol,
        int wave_opt, int stretch_opt, int trend_opt, int switch_opt) except +

    vector[int] clxs_s0002_entrypoint3_evidence(
        int length,
        vector[float] high, vector[float] low, vector[float] open, vector[float] close,
        vector[float] vol,
        int wave_opt, int stretch_opt, int trend_opt, int switch_opt) except +
