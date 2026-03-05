# distutils: language = c++
# cython: language_level = 3

from libcpp.vector cimport vector

def fq_recognise_bars(int length, vector[float] high, vector[float] low):
    return recognise_bars(length, high, low)

def fq_recognise_std_bars(int length, vector[float] high, vector[float] low):
    return recognise_std_bars(length, high, low)

def fq_recognise_swing(int length, vector[float] high, vector[float] low):
    return recognise_swing(length, high, low);

def fq_recognise_bi(int length, vector[float] high, vector[float] low):
    return recognise_bi(length, high, low);

def fq_recognise_duan(int length, vector[float] bi, vector[float] high, vector[float] low):
    return recognise_duan(length, bi, high, low)

def fq_recognise_pivots(int length, vector[float] duan, vector[float] bi, vector[float] high, vector[float] low):
    return recognise_pivots(length, duan, bi, high, low)
