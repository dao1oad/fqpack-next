#pragma once

#include "copilot.h"
#include "../common/log.h"
#include "../common/common.h"
#include "../chanlun/czsc.h"
#include "s.h"
#include "../indicator/indicator.h"
#include "signal_utils.h"
#include "signal_encoding.h"
#include "chan_context.h"
#include <cstdlib>

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
    std::vector<float> strong_factors;
    std::vector<float> strong_swing_factors;
    int switch_opt;
    int length;
    ChanOptions options;

    virtual void calculate() = 0;
    // 信号编码: direction × (model_id × 1000 + occurrence × 100 + entrypoint)
    // occurrence <= 0 关闭信号；occurrence > 99 封顶为 99。
    static int encode_signal(int model_id, int occurrence, EntrypointType signal)
    {
        return ClxSignalEncoding::encode(
            model_id, occurrence, static_cast<int>(signal));
    }

    static int reencode_signal_for_model(
        int original_signal, int source_model_id, int target_model_id)
    {
        return ClxSignalEncoding::reencode_for_model(
            original_signal, source_model_id, target_model_id);
    }

    void initialize()
    {
        length = static_cast<int>(high.size());
        inner_result.assign(length, 0);
        swing_sigs = recognise_swing(length, high, low);
        wave_sigs = recognise_bi(length, high, low, close, options);
        stretch_sigs = recognise_duan(length, wave_sigs, high, low);
        trend_sigs = recognise_trend(static_cast<int>(length), stretch_sigs, high, low);
        std_bars = recognise_std_bars(length, high, low);
        strong_factors = STRONG_FACTAL(high, low, open, close, wave_sigs, std_bars);
        strong_swing_factors = STRONG_FACTAL(high, low, open, close, swing_sigs, std_bars);
        ma5 = MA(close, 5);
        std::tie(dif, dea, macd) = MACD(close, 12, 26, 9);
        atrs = ATR(high, low, close, 20);
    }

    void initialize_from_context(const ChanContext &ctx)
    {
        length = ctx.length;
        inner_result.assign(length, 0);
        swing_sigs = ctx.swing_sigs;
        wave_sigs = ctx.wave_sigs;
        stretch_sigs = ctx.stretch_sigs;
        trend_sigs = ctx.trend_sigs;
        std_bars = ctx.std_bars;
        strong_factors = ctx.strong_factors;
        strong_swing_factors = ctx.strong_swing_factors;
        ma5 = ctx.ma5;
        macd = ctx.macd;
        dif = ctx.dif;
        dea = ctx.dea;
        atrs = ctx.atrs;
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

    BaseCalculator(
        const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
        const std::vector<float> &vol,
        int switch_opt, const ChanOptions &options,
        const ChanContext &ctx)
        : high(high), low(low), open(open), close(close), vol(vol),
          switch_opt(switch_opt), options(options)
    {
        initialize_from_context(ctx);
    }

    std::vector<int> result() const
    {
        return inner_result;
    }
};
