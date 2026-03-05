# distutils: language = c++
# cython: language_level = 3

from libcpp.vector cimport vector

def fq_recognise_bars(int length, vector[float] high, vector[float] low):
    return recognise_bars(length, high, low)

def fq_recognise_std_bars(int length, vector[float] high, vector[float] low):
    return recognise_std_bars(length, high, low)

def fq_recognise_swing(int length, vector[float] h, vector[float] l):
    return Bi1(length, h, l);

def fq_recognise_bi(int length, vector[float] h, vector[float] l):
    return Bi2(length, h, l);

def fq_recognise_duan1(int length, vector[float] bi, vector[float] h, vector[float] l):
    return Duan1(length, bi, h, l)

def fq_recognise_duan2(int length, vector[float] bi, vector[float] h, vector[float] l):
    return Duan2(length, bi, h, l)

def fq_recognise_duan(int length, vector[float] bi, vector[float] h, vector[float] l):
    return Duan1(length, bi, h, l)

def fq_recognise_pivots(int length, vector[float] duan, vector[float] bi, vector[float] h, vector[float] l):
    return ZS(length, bi, h, l)
