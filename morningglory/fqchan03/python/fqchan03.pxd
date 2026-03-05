# distutils: language = c++
# cython: language_level = 3

from libcpp.vector cimport vector
from libcpp cimport bool

cdef extern from "Comm.cpp":
    pass

cdef extern from "Comm.h":
    ctypedef struct Bar:
        int i
        float high
        float low
    ctypedef struct MergedBar:
        int start
        int end
        int vertex
        float high
        float low
        float high_high
        float low_low
        float direction
    ctypedef struct Pivot:
        int start
        int end
        float zg
        float zd
        float gg
        float dd
        float direction
        bool affirm

    vector[Bar] recognise_bars(int length, vector[float] high, vector[float] low)
    vector[MergedBar] recognise_std_bars(int length, vector[float] high, vector[float] low)
    vector[float] recognise_swing(int length, vector[float] high, vector[float] low)
    vector[float] recognise_bi(int length, vector[float] high, vector[float] low)
    vector[float] recognise_duan(int length, vector[float] bi, vector[float] high, vector[float] low)
    vector[Pivot] recognise_pivots(int length, vector[float] duan, vector[float] bi, vector[float] high, vector[float] low);
