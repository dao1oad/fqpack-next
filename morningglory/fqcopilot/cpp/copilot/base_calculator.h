#pragma once

#include "copilot.h"
#include "../common/log.h"
#include "../common/common.h"
#include "../chanlun/czsc.h"
#include "s.h"
#include "../indicator/indicator.h"
#include "signal_utils.h"

class BaseCalculator
{
protected:
    std::vector<float> high;
    std::vector<float> low;
    std::vector<float> open;
    std::vector<float> close;
    std::vector<float> vol;
    std::vector<float> ma5;
    std::vector<float> macd;
    std::vector<float> dif;
    std::vector<float> dea;
    std::vector<float> atrs;
    std::vector<int> inner_result;
    std::vector<float> swing_sigs;
    std::vector<float> wave_sigs;
    std::vector<float> stretch_sigs;
    std::vector<float> trend_sigs;
    std::vector<StdBar> std_bars;
    int switch_opt;
    int length;
    ChanOptions options;

    virtual void calculate() = 0;

    void initialize()
    {
        length = static_cast<int>(high.size());
        inner_result.assign(length, 0);
        swing_sigs = recognise_swing(length, high, low);
        wave_sigs = recognise_bi(length, high, low, options);
        stretch_sigs = recognise_duan(length, wave_sigs, high, low);
        trend_sigs = recognise_trend(static_cast<int>(length), stretch_sigs, high, low);
        std_bars = recognise_std_bars(length, high, low);
        ma5 = MA(close, 5);
        std::tie(dif, dea, macd) = MACD(close, 12, 26, 9);
        atrs = ATR(high, low, close, 20);
    }

public:
    BaseCalculator(
        const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
        const std::vector<float> &vol,
        int switch_opt, const ChanOptions &options) : high(high), low(low), open(open), close(close), vol(vol),
                                                      switch_opt(switch_opt), options(options)
    {
        initialize();
    }

    std::vector<int> result() const
    {
        return inner_result;
    }
};
