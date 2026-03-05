# distutils: language = c++
# cython: language_level = 3

from libcpp cimport bool
from libcpp.vector cimport vector


cdef extern from "chanlun/czsc.cpp":
    pass

cdef extern from "chanlun/xd.cpp":
    pass

cdef extern from "chanlun/bi.cpp":
    pass

cdef extern from "chanlun/czsc.h":
    ctypedef struct Bar:
        int pos
        float high
        float low
    ctypedef struct StdBar:
        int pos
        int start
        int end
        int high_vertex_raw_pos
        int low_vertex_raw_pos
        float high
        float low
        float high_high
        float low_low
        float direction
        float factor
        float factor_high
        float factor_low
        float factor_strong
    ctypedef struct Pivot:
        int start
        int end
        float zg
        float zd
        float gg
        float dd
        float direction
        bool is_comprehensive
    ctypedef struct ChanOptions:
        int bi_mode
        int force_wave_stick_count
        int allow_pivot_across
        int merge_non_complehensive_wave
        
    int count_vertexes(vector[float] vertexes, int i, int j)
    vector[Pivot] locate_pivots(
        vector[float] vertexes,
        vector[float] high,
        vector[float] low,
        int direction,
        int i,
        int j)
    
    vector[Bar] recognise_bars(int length, vector[float] h, vector[float] l)
    vector[StdBar] recognise_std_bars(int length, vector[float] h, vector[float] l)
    vector[float] recognise_swing(int length, vector[float] h, vector[float] l)
    vector[float] recognise_bi(int length, vector[float] h, vector[float] l, ChanOptions& chan_options)
    vector[float] recognise_duan(int length, vector[float] bi, vector[float] h, vector[float] l)
    vector[Pivot] recognise_pivots(
        int length,
        vector[float] higher_level_sigs,
        vector[float] sigs,
        vector[float] h,
        vector[float] l,
        ChanOptions& chan_options)
    vector[float] recognise_trend(int length, vector[float] duan, vector[float] high, vector[float] low)