# distutils: language = c++
# cython: language_level = 3

from libcpp cimport bool
from libcpp.vector cimport vector
from libcpp cimport int

cdef extern from "func_set.cpp":
    pass

cdef extern from "func_set.h":
    vector[float] clxs(
        int length,
        vector[float] high, vector[float] low, vector[float] open, vector[float] close,
        vector[float] vol,
        int wave_opt, int stretch_opt, int trend_opt, int model_opt);
