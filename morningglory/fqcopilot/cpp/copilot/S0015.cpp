#include "../chanlun/czsc.h"
#include "base_calculator.h"
#include "copilot.h"

/**
 * S0015 - MA250 支撑/阻力策略（迁移自 fqsignal S0003）
 *
 * 买入逻辑：线段起点 → 笔上破MA250 → 找2~3个向下笔形成上升支撑 → 分型确认
 * 卖出逻辑：线段起点 → 笔下破MA250 → 找2~3个向上笔形成下降阻力 → 分型确认
 *
 * ext_opt 编码：
 *   ext_opt % 1000       → MA周期（默认250）
 *   ext_opt / 1000 % 100 → 差值阈值（0=ATR*2，其他=固定值）
 *
 * 信号编码：统一编码格式 direction × (model_id × 1000 + occurrence × 100 + entrypoint)
 *   15101   → 确认买点（S0015, 第1次, 结构信号）
 *   -15101  → 确认卖点（S0015, 第1次, 结构信号）
 */

// ==============================================================================
// 买入信号检测
// ==============================================================================
static void find_buy_sigs(
    int length, std::vector<int> &result, const std::vector<float> &diffs,
    const std::vector<float> &stretch_sigs, const std::vector<float> &wave_sigs,
    const std::vector<float> &factor_sigs,
    const std::vector<float> &ma,
    const std::vector<float> &high, const std::vector<float> &low)
{
    for (int i = 0; i < length; i++)
    {
        // 买入起点：线段向下起点
        if (stretch_sigs[i] != -1)
            continue;

        int above_ma_bi_count = 0;
        std::vector<float> supports = {low[i]};

        for (int j = i + 1; j < length; j++)
        {
            // 一笔回到MA下方 → 重置
            if (wave_sigs[j] == -1 && high[j] < ma[j])
            {
                above_ma_bi_count = 0;
                supports = {low[j]};
            }

            // 笔底上破MA → 首次突破
            if (wave_sigs[j] == 1 && low[j] > ma[j])
            {
                above_ma_bi_count++;
                if (above_ma_bi_count == 1)
                {
                    // 找2~3个向下笔验证支撑
                    int count = 0;

                    for (int k = j + 1; k < length; k++)
                    {
                        if (low[k] < supports.front())
                            break;
                        if (stretch_sigs[k] == -1)
                            break;

                        if (wave_sigs[k] == -1)
                        {
                            count++;
                            supports.push_back(low[k]);

                            if (count == 2 || count == 3)
                            {
                                float min_v = *std::min_element(supports.begin() + 1, supports.end());
                                float max_v = *std::max_element(supports.begin() + 1, supports.end());
                                float diff = std::min(max_v - min_v, std::abs(supports.back() - supports[1]));

                                // 支撑位上升 + 差值收敛
                                if (diff <= diffs[k] &&
                                    supports.back() >= std::min(supports[supports.size() - 3], supports[supports.size() - 2]))
                                {
                                    // 找分型确认
                                    for (int l = k + 1; l < length; l++)
                                    {
                                        if (wave_sigs[l] == 1)
                                            break;
                                        if (factor_sigs[l] == -1)
                                        {
                                            result[l] = 15101; // S0015确认买点
                                            break;
                                        }
                                    }
                                }

                                if (count >= 3)
                                    break;
                            }
                        }
                    }
                }
            }

            if (stretch_sigs[j] == -1)
                break;
        }
    }
}

// ==============================================================================
// 卖出信号检测
// ==============================================================================
static void find_sell_sigs(
    int length, std::vector<int> &result, const std::vector<float> &diffs,
    const std::vector<float> &stretch_sigs, const std::vector<float> &wave_sigs,
    const std::vector<float> &factor_sigs,
    const std::vector<float> &ma,
    const std::vector<float> &high, const std::vector<float> &low)
{
    for (int i = 0; i < length; i++)
    {
        // 卖出起点：线段向上起点
        if (stretch_sigs[i] != 1)
            continue;

        int below_ma_bi_count = 0;
        std::vector<float> resistances = {high[i]};

        for (int j = i + 1; j < length; j++)
        {
            // 一笔回到MA上方 → 重置
            if (wave_sigs[j] == 1 && low[j] > ma[j])
            {
                below_ma_bi_count = 0;
                resistances = {high[j]};
            }

            // 笔顶下破MA → 首次跌破
            if (wave_sigs[j] == -1 && high[j] < ma[j])
            {
                below_ma_bi_count++;
                if (below_ma_bi_count == 1)
                {
                    // 找2~3个向上笔验证阻力
                    int count = 0;

                    for (int k = j + 1; k < length; k++)
                    {
                        if (high[k] > resistances.front())
                            break;
                        if (stretch_sigs[k] == 1)
                            break;

                        if (wave_sigs[k] == 1)
                        {
                            count++;
                            resistances.push_back(high[k]);

                            if (count == 2 || count == 3)
                            {
                                float min_v = *std::min_element(resistances.begin() + 1, resistances.end());
                                float max_v = *std::max_element(resistances.begin() + 1, resistances.end());
                                float diff = std::min(max_v - min_v, std::abs(resistances.back() - resistances[1]));

                                // 阻力位下降 + 差值收敛
                                if (diff <= diffs[k] &&
                                    resistances.back() <= std::max(resistances[resistances.size() - 3], resistances[resistances.size() - 2]))
                                {
                                    // 找分型确认
                                    for (int l = k + 1; l < length; l++)
                                    {
                                        if (wave_sigs[l] == -1)
                                            break;
                                        if (factor_sigs[l] == 1)
                                        {
                                            result[l] = -15101; // S0015确认卖点
                                            break;
                                        }
                                    }
                                }

                                if (count >= 3)
                                    break;
                            }
                        }
                    }
                }
            }

            if (stretch_sigs[j] == 1)
                break;
        }
    }
}

// ==============================================================================
// S0015 Calculator
// ==============================================================================
class S0015_Calculator : public BaseCalculator
{
private:
    void calculate()
    {
        // 解析 ext_opt（通过 ChanOptions 传递）
        int ext_opt = options.ext_opt;
        int ma_opt = (ext_opt > 0) ? ext_opt % 1000 : 250;
        int in_diff = (ext_opt > 0) ? ext_opt / 1000 % 100 : 0;

        // 差值阈值：0=ATR*2，否则固定值
        std::vector<float> diffs(length);
        if (in_diff == 0)
        {
            for (int i = 0; i < length; i++)
                diffs[i] = atrs[i] * 2;
        }
        else
        {
            diffs.assign(length, static_cast<float>(in_diff));
        }

        // BaseCalculator 未预计算，需手动调用
        auto factor_sigs = factor_confirm_sigs(length, std_bars);
        auto ma = MA(close, ma_opt);

        // 校验向量大小，防止越界
        if (static_cast<int>(factor_sigs.size()) != length ||
            static_cast<int>(ma.size()) != length)
        {
            return;
        }

        find_buy_sigs(length, inner_result, diffs, stretch_sigs, wave_sigs, factor_sigs, ma, high, low);
        find_sell_sigs(length, inner_result, diffs, stretch_sigs, wave_sigs, factor_sigs, ma, high, low);
    }

public:
    S0015_Calculator(
        const std::vector<float> &high, const std::vector<float> &low,
        const std::vector<float> &open, const std::vector<float> &close,
        const std::vector<float> &vol, int switch_opt,
        const ChanOptions &options)
        : BaseCalculator(high, low, open, close, vol, switch_opt, options)
    {
        calculate();
    }

    S0015_Calculator(
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

std::vector<int> F_S0015(
    const std::vector<float> &high, const std::vector<float> &low,
    const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt,
    const ChanOptions &options)
{
    S0015_Calculator calculator(high, low, open, close, vol, switch_opt, options);
    return calculator.result();
}

REGISTER_CALC(15, F_S0015)

std::vector<int> F_S0015_ctx(
    const std::vector<float> &high, const std::vector<float> &low,
    const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt,
    const ChanOptions &options, const ChanContext &ctx)
{
    return S0015_Calculator(high, low, open, close, vol, switch_opt, options, ctx).result();
}
