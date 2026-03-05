# distutils: language = c++
# cython: language_level = 3

from libcpp.vector cimport vector

def fq_recognise_bars(int length, vector[float] h, vector[float] l):
    return recognise_bars(length, h, l)

def fq_recognise_std_bars(int length, vector[float] h, vector[float] l):
    return recognise_std_bars(length, h, l)

def fq_recognise_swing(int length, vector[float] h, vector[float] l):
    return recognise_swing(length, h, l);

def fq_recognise_bi(
        int length, 
        vector[float] h, 
        vector[float] l, 
        ChanOptions chan_options=ChanOptions(bi_mode=6, force_wave_stick_count=15, allow_pivot_across=0, merge_non_complehensive_wave=0)):
    return recognise_bi(length, h, l, chan_options);

def fq_recognise_duan(int length, vector[float] bi, vector[float] h, vector[float] l):
    return recognise_duan(length, bi, h, l)

def fq_recognise_pivots(
        int length,
        vector[float] higher_level_sigs,
        vector[float] sigs,
        vector[float] h,
        vector[float] l,
        ChanOptions chan_options=ChanOptions(bi_mode=6, force_wave_stick_count=15, allow_pivot_across=0, merge_non_complehensive_wave=0)):
    return recognise_pivots(length, higher_level_sigs, sigs, h, l, chan_options)

def fq_count_vertexes(vector[float] vertexes, int i, int j):
    return count_vertexes(vertexes, i, j)

def fq_locate_pivots(vector[float] vertexes, vector[float] high, vector[float] low, int direction, int i, int j):
    return locate_pivots(vertexes, high, low, direction, i, j)

def fq_recognise_trend(int length, vector[float] duan, vector[float] high, vector[float] low):
    return recognise_trend(length, duan, high, low)
