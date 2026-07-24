#include "batch_calculator.h"
#include "base_calculator.h"
#include "../chanlun/czsc.h"
#include "../indicator/indicator.h"
#include "../common/common.h"
#include "signal_utils.h"

// ctx 辅助函数声明
extern std::vector<int> F_S0000_ctx(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &, const ChanContext &);
extern std::vector<int> F_S0001_ctx(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &, const ChanContext &);
extern std::vector<int> F_S0002_ctx(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &, const ChanContext &);
extern std::vector<int> F_S0003_ctx(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &, const ChanContext &);
extern std::vector<int> F_S0004_ctx(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &, const ChanContext &);
extern std::vector<int> F_S0005_ctx(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &, const ChanContext &);
extern std::vector<int> F_S0006_ctx(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &, const ChanContext &);
extern std::vector<int> F_S0007_ctx(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &, const ChanContext &);
extern std::vector<int> F_S0008_ctx(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &, const ChanContext &);
extern std::vector<int> F_S0009_ctx(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &, const ChanContext &);
extern std::vector<int> F_S0010_ctx(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &, const ChanContext &);
extern std::vector<int> F_S0011_ctx(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &, const ChanContext &);
extern std::vector<int> F_S0012_ctx(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &, const ChanContext &);
extern std::vector<int> F_S0013_ctx(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &, const ChanContext &);
extern std::vector<int> F_S0014_ctx(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &, const ChanContext &);
extern std::vector<int> F_S0015_ctx(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &, const ChanContext &);
extern std::vector<int> F_S0016_ctx(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &, const ChanContext &);
extern std::vector<int> F_S0017_ctx(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &, const ChanContext &);

// ============================================================================
// BatchCalculator
// ============================================================================

BatchCalculator::BatchCalculator(
    const std::vector<float> &high, const std::vector<float> &low,
    const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol,
    int switch_opt, const ChanOptions &options)
    : high(high), low(low), open(open), close(close), vol(vol),
      switch_opt(switch_opt), options(options)
{
    int length = static_cast<int>(high.size());
    ctx.length = length;
    // recognise_* 函数接受非 const 引用，需要局部可变拷贝
    std::vector<float> h(high), l(low), c(close);
    ChanOptions mut_options(options);
    ctx.std_bars = recognise_std_bars(length, h, l);
    std::vector<Bar> raw_bars = recognise_bars(length, h, l);
    ctx.swing_sigs = recognise_swing_from_std_bars(length, ctx.std_bars);
    ctx.wave_sigs = recognise_bi_from_precomputed(
        length, c, mut_options, raw_bars, ctx.std_bars);
    ctx.strong_factors = STRONG_FACTAL(
        high, low, open, close, ctx.wave_sigs, ctx.std_bars);
    ctx.strong_swing_factors = STRONG_FACTAL(
        high, low, open, close, ctx.swing_sigs, ctx.std_bars);
    ctx.stretch_sigs = recognise_duan(length, ctx.wave_sigs, h, l);
    ctx.trend_sigs = recognise_trend(length, ctx.stretch_sigs, h, l);
    ctx.ma5 = MA(c, 5);
    std::tie(ctx.dif, ctx.dea, ctx.macd) = MACD(c, 12, 26, 9);
    ctx.atrs = ATR(h, l, c, 20);
}

std::vector<std::vector<int>> BatchCalculator::calc_all()
{
    std::vector<std::vector<int>> results(18);
    results[0] = F_S0000_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    results[1] = F_S0001_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    results[2] = F_S0002_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    results[3] = F_S0003_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    results[4] = F_S0004_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    results[5] = F_S0005_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    results[6] = F_S0006_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    results[7] = F_S0007_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    results[8] = F_S0008_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    results[9] = F_S0009_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    results[10] = F_S0010_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    results[11] = F_S0011_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    results[12] = F_S0012_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    results[13] = F_S0013_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    results[14] = F_S0014_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    results[15] = F_S0015_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    results[16] = F_S0016_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    results[17] = F_S0017_ctx(high, low, open, close, vol, switch_opt, options, ctx);
    return results;
}

DetailedBatchResult BatchCalculator::calc_all_detailed()
{
    DetailedBatchResult result;
    result.signals = calc_all();
    std::tie(result.buy_base_trigger_masks, result.sell_base_trigger_masks) =
        SignalUtils::calc_base_trigger_masks(
            high, low, open, close, vol,
            ctx.wave_sigs, ctx.std_bars, ctx.ma5, ctx.macd);

    return result;
}
