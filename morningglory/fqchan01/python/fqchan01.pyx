# distutils: language = c++
# cython: language_level = 3

from libcpp.vector cimport vector

cdef class FqChanOptions:
    cdef ChanOptions *thisptr
    
    def __cinit__(self, int inclusion_mode=1, int bi_mode=6, int force_wave_stick_count=15,
                 int allow_pivot_across=0, int merge_non_complehensive_wave=0):
        self.thisptr = new ChanOptions()
        self.thisptr.inclusion_mode = inclusion_mode
        self.thisptr.bi_mode = bi_mode
        self.thisptr.force_wave_stick_count = force_wave_stick_count
        self.thisptr.allow_pivot_across = allow_pivot_across
        self.thisptr.merge_non_complehensive_wave = merge_non_complehensive_wave
    
    def __dealloc__(self):
        del self.thisptr
    
    @property
    def inclusion_mode(self):
        return self.thisptr.inclusion_mode
    
    @inclusion_mode.setter
    def inclusion_mode(self, int value):
        self.thisptr.inclusion_mode = value
    
    @property
    def bi_mode(self):
        return self.thisptr.bi_mode
    
    @bi_mode.setter
    def bi_mode(self, int value):
        self.thisptr.bi_mode = value
    
    @property
    def force_wave_stick_count(self):
        return self.thisptr.force_wave_stick_count
    
    @force_wave_stick_count.setter
    def force_wave_stick_count(self, int value):
        self.thisptr.force_wave_stick_count = value
    
    @property
    def allow_pivot_across(self):
        return self.thisptr.allow_pivot_across
    
    @allow_pivot_across.setter
    def allow_pivot_across(self, int value):
        self.thisptr.allow_pivot_across = value
    
    @property
    def merge_non_complehensive_wave(self):
        return self.thisptr.merge_non_complehensive_wave
    
    @merge_non_complehensive_wave.setter
    def merge_non_complehensive_wave(self, int value):
        self.thisptr.merge_non_complehensive_wave = value


def fq_recognise_bars(int length, vector[float] h, vector[float] l):
    return recognise_bars(length, h, l)

def fq_recognise_std_bars(
        int length, 
        vector[float] h, 
        vector[float] l,
        FqChanOptions chan_options=None):
    cdef ChanOptions opts
    if chan_options is None:
        opts = ChanOptions()
        opts.inclusion_mode = 1
        opts.bi_mode = 6
        opts.force_wave_stick_count = 15
        opts.allow_pivot_across = 0
        opts.merge_non_complehensive_wave = 0
    else:
        opts = chan_options.thisptr[0]
    return recognise_std_bars(length, h, l, opts)

def fq_recognise_swing(
        int length, 
        vector[float] h, 
        vector[float] l,
        FqChanOptions chan_options=None):
    cdef ChanOptions opts
    if chan_options is None:
        opts = ChanOptions()
        opts.inclusion_mode = 1
        opts.bi_mode = 6
        opts.force_wave_stick_count = 15
        opts.allow_pivot_across = 0
        opts.merge_non_complehensive_wave = 0
    else:
        opts = chan_options.thisptr[0]
    return recognise_swing(length, h, l, opts)

def fq_recognise_bi(
        int length, 
        vector[float] h, 
        vector[float] l, 
        FqChanOptions chan_options=None):
    cdef ChanOptions opts
    if chan_options is None:
        opts = ChanOptions()
        opts.inclusion_mode = 1
        opts.bi_mode = 6
        opts.force_wave_stick_count = 15
        opts.allow_pivot_across = 0
        opts.merge_non_complehensive_wave = 0
    else:
        opts = chan_options.thisptr[0]
    return recognise_bi(length, h, l, opts);

def fq_recognise_duan(int length, vector[float] bi, vector[float] h, vector[float] l):
    return recognise_duan(length, bi, h, l)

def fq_recognise_pivots(
        int length,
        vector[float] higher_level_sigs,
        vector[float] sigs,
        vector[float] h,
        vector[float] l,
        FqChanOptions chan_options=None):
    cdef ChanOptions opts
    if chan_options is None:
        opts = ChanOptions()
        opts.inclusion_mode = 1
        opts.bi_mode = 6
        opts.force_wave_stick_count = 15
        opts.allow_pivot_across = 0
        opts.merge_non_complehensive_wave = 0
    else:
        opts = chan_options.thisptr[0]
    return recognise_pivots(length, higher_level_sigs, sigs, h, l, opts)

def fq_count_vertexes(vector[float] vertexes, int i, int j):
    return count_vertexes(vertexes, i, j)

def fq_locate_pivots(vector[float] vertexes, vector[float] high, vector[float] low, int direction, int i, int j):
    return locate_pivots(vertexes, high, low, direction, i, j)

def fq_recognise_trend(int length, vector[float] duan, vector[float] high, vector[float] low):
    return recognise_trend(length, duan, high, low)
