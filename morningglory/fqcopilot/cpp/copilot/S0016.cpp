#include "../chanlun/czsc.h"
#include "base_calculator.h"
#include "copilot.h"
#include "signal_utils.h"

/**
 * S0016 - 支撑/阻力区间反转策略
 *
 * 买点：当前向下线段(>=5笔)最低价进入前2个向下线段的支撑区间(分型区间)，
 *       收盘价高于前序线段低点，SignalUtils确认反转时产生买入信号。
 * 卖点：镜像反转。
 *
 * 信号编码：direction x (16 x 1000 + occurrence x 100 + entrypoint)
 *   16101  -> S0016, 第1次回踩, 结构信号 买入
 *   16207  -> S0016, 第2次回踩, MACD交叉 买入
 *   -16101 -> S0016, 第1次回踩, 结构信号 卖出
 */

// ============================================================================
// 线段摘要
// ============================================================================
struct StretchInfo
{
    int start_pos = -1;
    int end_pos = -1;
    float extreme_price = 0;
    int extreme_pos = -1;
    int bi_count = 0;
    float zone_high = 0;
    float zone_low = 0;
    bool has_zone = false;
};

// ============================================================================
// 根据原始K线位置找到包含它的 StdBar 索引，找不到返回 -1
// ============================================================================
static int find_std_bar_index(const std::vector<StdBar> &std_bars, int raw_pos)
{
    for (size_t s = 0; s < std_bars.size(); s++)
    {
        if (std_bars[s].start <= raw_pos && raw_pos <= std_bars[s].end)
            return static_cast<int>(s);
    }
    return -1;
}

// ============================================================================
// 从指定 StdBar 索引开始，搜索最近的分型区间
// ============================================================================
static bool find_zone_near(
    const std::vector<StdBar> &std_bars, int center_idx, int boundary_idx,
    float &zone_high, float &zone_low)
{
    // 向 boundary_idx 方向搜索
    int step = (boundary_idx > center_idx) ? 1 : -1;
    for (int s = center_idx; s >= 0 && s < static_cast<int>(std_bars.size()); s += step)
    {
        if (std_bars[s].factor != 0)
        {
            zone_high = std_bars[s].factor_high;
            zone_low = std_bars[s].factor_low;
            return true;
        }
        if ((step > 0 && s >= boundary_idx) || (step < 0 && s <= boundary_idx))
            break;
    }
    // 反方向搜索
    for (int s = center_idx - step; s >= 0 && s < static_cast<int>(std_bars.size()); s -= step)
    {
        if (std_bars[s].factor != 0)
        {
            zone_high = std_bars[s].factor_high;
            zone_low = std_bars[s].factor_low;
            return true;
        }
        if ((step > 0 && s <= boundary_idx) || (step < 0 && s >= boundary_idx))
            break;
    }
    return false;
}

// ============================================================================
// 收集同方向已确认线段
// ============================================================================
static std::vector<StretchInfo> collect_stretches(
    const std::vector<float> &stretch_sigs,
    const std::vector<float> &wave_sigs,
    const std::vector<float> &high,
    const std::vector<float> &low,
    const std::vector<StdBar> &std_bars,
    int length, float direction)
{
    std::vector<StretchInfo> result;

    float start_sig = (direction < 0) ? 1.0f : -1.0f;
    float end_sig = (direction < 0) ? -1.0f : 1.0f;

    for (int i = 0; i < length; i++)
    {
        if (stretch_sigs[i] != start_sig)
            continue;

        int end_pos = -1;
        for (int j = i + 1; j < length; j++)
        {
            if (stretch_sigs[j] == end_sig)
            {
                end_pos = j;
                break;
            }
        }
        if (end_pos < 0)
            continue;

        StretchInfo info;
        info.start_pos = i;
        info.end_pos = end_pos;

        for (int k = i + 1; k <= end_pos; k++)
        {
            float w = wave_sigs[k];
            if (w == 1.0f || w == -1.0f)
                info.bi_count++;
        }

        info.extreme_price = (direction < 0) ? low[i] : high[i];
        info.extreme_pos = i;
        for (int k = i; k <= end_pos; k++)
        {
            float price = (direction < 0) ? low[k] : high[k];
            if ((direction < 0 && price < info.extreme_price) ||
                (direction > 0 && price > info.extreme_price))
            {
                info.extreme_price = price;
                info.extreme_pos = k;
            }
        }

        int extreme_std_idx = find_std_bar_index(std_bars, info.extreme_pos);
        int start_std_idx = find_std_bar_index(std_bars, i);
        int end_std_idx = find_std_bar_index(std_bars, end_pos);

        if (extreme_std_idx >= 0)
        {
            int boundary = (start_std_idx >= 0) ? start_std_idx : extreme_std_idx;
            info.has_zone = find_zone_near(
                std_bars, extreme_std_idx, boundary,
                info.zone_high, info.zone_low);
        }
        if (!info.has_zone && end_std_idx >= 0)
        {
            info.has_zone = find_zone_near(
                std_bars, extreme_std_idx >= 0 ? extreme_std_idx : end_std_idx, end_std_idx,
                info.zone_high, info.zone_low);
        }

        result.push_back(info);
        i = end_pos;
    }

    return result;
}

// ============================================================================
// S0016 Calculator
// ============================================================================
class S0016_Calculator : public BaseCalculator
{
private:
    void calculate()
    {
        auto down_stretches = collect_stretches(
            stretch_sigs, wave_sigs, high, low, std_bars, length, -1);
        auto up_stretches = collect_stretches(
            stretch_sigs, wave_sigs, high, low, std_bars, length, 1);

        find_buy_sigs(down_stretches);
        find_sell_sigs(up_stretches);
    }

    void find_buy_sigs(const std::vector<StretchInfo> &stretches)
    {
        for (size_t idx = 2; idx < stretches.size(); idx++)
        {
            const auto &cur = stretches[idx];
            if (cur.bi_count < 5)
                continue;
            if (!cur.has_zone)
                continue;

            const StretchInfo *prevs[] = {&stretches[idx - 1], &stretches[idx - 2]};

            for (const auto *prev : prevs)
            {
                if (!prev->has_zone)
                    continue;
                if (cur.extreme_price > prev->zone_high)
                    continue;

                int occurrence = 0;
                for (int i = cur.extreme_pos; i < length; i++)
                {
                    if (wave_sigs[i] == 1.0f && i > cur.extreme_pos)
                        break;

                    if (low[i] < prev->zone_low - atrs[i])
                        break;

                    if (close[i] <= prev->extreme_price)
                        continue;

                    EntrypointType sig = SignalUtils::is_buy_signal(
                        i, high, low, open, close, vol, wave_sigs, std_bars, ma5, macd, strong_factors);

                    if (sig != EntrypointType::ENTRYPOINT_UNKNOWN)
                    {
                        inner_result[i] = encode_signal(16, ++occurrence, sig);
                        if (occurrence >= 3)
                            break;
                    }
                }
            }
        }
    }

    void find_sell_sigs(const std::vector<StretchInfo> &stretches)
    {
        for (size_t idx = 2; idx < stretches.size(); idx++)
        {
            const auto &cur = stretches[idx];
            if (cur.bi_count < 5)
                continue;
            if (!cur.has_zone)
                continue;

            const StretchInfo *prevs[] = {&stretches[idx - 1], &stretches[idx - 2]};

            for (const auto *prev : prevs)
            {
                if (!prev->has_zone)
                    continue;
                if (cur.extreme_price < prev->zone_low)
                    continue;

                int occurrence = 0;
                for (int i = cur.extreme_pos; i < length; i++)
                {
                    if (wave_sigs[i] == -1.0f && i > cur.extreme_pos)
                        break;

                    if (high[i] > prev->zone_high + atrs[i])
                        break;

                    if (close[i] >= prev->extreme_price)
                        continue;

                    EntrypointType sig = SignalUtils::is_sell_signal(
                        i, high, low, open, close, vol, wave_sigs, std_bars, ma5, macd, strong_factors);

                    if (sig != EntrypointType::ENTRYPOINT_UNKNOWN)
                    {
                        inner_result[i] = encode_signal(16, ++occurrence, sig);
                        if (occurrence >= 3)
                            break;
                    }
                }
            }
        }
    }

public:
    S0016_Calculator(
        const std::vector<float> &high, const std::vector<float> &low,
        const std::vector<float> &open, const std::vector<float> &close,
        const std::vector<float> &vol, int switch_opt,
        const ChanOptions &options)
        : BaseCalculator(high, low, open, close, vol, switch_opt, options)
    {
        calculate();
    }

    S0016_Calculator(
        const std::vector<float> &high, const std::vector<float> &low,
        const std::vector<float> &open, const std::vector<float> &close,
        const std::vector<float> &vol, int switch_opt,
        const ChanOptions &options,
        const ChanContext &ctx)
        : BaseCalculator(high, low, open, close, vol, switch_opt, options, ctx)
    {
        calculate();
    }
};

std::vector<int> F_S0016(
    const std::vector<float> &high, const std::vector<float> &low,
    const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt,
    const ChanOptions &options)
{
    S0016_Calculator calculator(high, low, open, close, vol, switch_opt, options);
    return calculator.result();
}

REGISTER_CALC(16, F_S0016)

std::vector<int> F_S0016_ctx(
    const std::vector<float> &high, const std::vector<float> &low,
    const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt,
    const ChanOptions &options, const ChanContext &ctx)
{
    return S0016_Calculator(high, low, open, close, vol, switch_opt, options, ctx).result();
}
