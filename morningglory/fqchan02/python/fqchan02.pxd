# distutils: language = c++
# cython: language_level = 3

from libcpp cimport bool
from libcpp.vector cimport vector


cdef extern from "ZhongShu.cpp":
    pass

cdef extern from "Bi.cpp":
    pass

cdef extern from "Duan.cpp":
    pass

cdef extern from "KxianChuLi.cpp":
    pass

cdef extern from "BiChuLi.cpp":
    pass

cdef extern from "Bi.h":
    vector[float] Bi1(int length, vector[float] h, vector[float] l)
    vector[float] Bi2(int length, vector[float] h, vector[float] l)

cdef extern from "Duan.h":
    vector[float] Duan1(int length, vector[float] bi, vector[float] h, vector[float] l)
    vector[float] Duan2(int length, vector[float] bi, vector[float] h, vector[float] l)

cdef extern from "ZhongShu.h":
    ctypedef struct Pivot:
        int start
        int end
        float zg
        float zd
        float gg
        float dd
        float direction
        bool affirm
    vector[Pivot] ZS(int length, vector[float] bi, vector[float] h, vector[float] l)

cdef extern from "KxianChuLi.h":
    ctypedef struct Bar:
        int i
        float high
        float low
    ctypedef struct StdBar:
        int start
        int end
        int vertex
        float high
        float low
        float high_high
        float low_low
        float direction
    vector[Bar] recognise_bars(int length, vector[float] high, vector[float] low)
    vector[StdBar] recognise_std_bars(int length, vector[float] high, vector[float] low)
