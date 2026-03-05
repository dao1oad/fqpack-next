#include "copilot.h"
#include "../common/log.h"
#include "../common/common.h"
#include "../chanlun/czsc.h"
#include "s.h"
#include "../indicator/indicator.h"
#include "signal_utils.h"
#include "base_calculator.h"

// 风浪@vx

class TAILORED_S0001_Calculator : public BaseCalculator
{
private:
    void calculate()
    {

        for (int i = 0; i < length; i++)
        {
            if (stretch_sigs[i] == -1)
            {
                // 从一个向下线段的结束点往后开始寻找分型中枢的突破点
                find_buy_signals(i);
            }
            else if (stretch_sigs[i] == 1)
            {
                // 从一个向上线段的结束点往后开始寻找分型中枢的突破点
                find_sell_signals(i);
            }
        }
    }

    void find_buy_signals(int origin_pos)
    {
        // 找买点
        // 1. 当前是向上线段的时候，收盘价突破分型中枢。
        // 2. 盘整/趋势一买后收盘价突破中枢分型，要求分型中枢在笔中枢最低点的上方。
        // 2. 二买/类二买之后收盘价突破分型中枢。
        // 4. 线段低点是前面线段起点的附近且比前面线段起点高，收盘价突破分型中枢。
        // 5. 前面或者当前向上线段是趋势背驰则停止预警，一直要等到盘整一买后才可以重新预警。
        if (stretch_sigs[origin_pos] != -1)
        {
            return;
        }
        // 找到允许的最低支撑价格
        float support_price = 0;
        for (int i = origin_pos - 1; i >= 0; i--)
        {
            if (stretch_sigs[i] == 1)
            {
                auto pivots = locate_pivots(wave_sigs, high, low, -1, i, origin_pos);
                int pivots_num = static_cast<int>(pivots.size());
                if (pivots_num > 0)
                {
                    Pivot &last_pivot = pivots.back();
                    float price_diff_a = 0;
                    float price_diff_b = 0;
                    for (int m = last_pivot.start - 1; m >= i; m--)
                    {
                        if (wave_sigs[m] == 1)
                        {
                            price_diff_a = high[m] - low[last_pivot.start];
                            break;
                        }
                    }
                    price_diff_b = high[last_pivot.end] - low[origin_pos];
                    // 中枢高高作为一个支撑价格
                    if (price_diff_b < price_diff_a)
                    {
                        support_price = last_pivot.dd;
                    }
                }
                break;
            }
        }
        
        for (int j = origin_pos; j < length; j++)
        {
            // 又碰到一个向下线段的终点了，针对这个线段就不用再预警了。
            if (j > origin_pos && (low[j] < low[origin_pos] || stretch_sigs[j] == -1 || stretch_sigs[j] == -0.5))
            {
                break;
            }
            // 如果已经碰到两个笔中枢了，针对这个线段也不用再预警了。
            // 以后还要加上趋势背驰才算，这里先不考虑，因为背驰判断还没做。
            if (stretch_sigs[j] == 1)
            {
                auto pivots = locate_pivots(wave_sigs, high, low, 1, origin_pos, j);
                if (pivots.size() >= 2)
                {
                    int standard_count = 0;
                    for (const auto &pivot : pivots)
                    {
                        if (pivot.is_comprehensive)
                        {
                            standard_count++;
                        }
                    }
                    if (standard_count >= 2)
                    {
                        break;
                    }
                }
            }
            if (support_price == 0)
            {
                if (stretch_sigs[j] == 1 || stretch_sigs[j] == 0.5)
                {
                    support_price = low[origin_pos];
                }
                if (j > origin_pos && wave_sigs[j] == -1)
                {
                    support_price = low[origin_pos];
                }
            }
            
            if (support_price == 0)
            {
                continue;
            }
            if (wave_sigs[j] == -1)
            {
                // 遇到向下笔的低点，针对这个向下笔有没有买点
                int x = -1;
                int y = j;
                int z = -1;
                // 向前查找x点，x点是wave_sigs[x] == 1的点，且x不能比i小
                for (int k = y - 1; k >= 0; k--)
                {
                    if (wave_sigs[k] == 1)
                    {
                        x = k;
                        break;
                    }
                }
                if (x > -1)
                {
                    std::vector<Pivot> pivots = locate_pivots(swing_sigs, high, low, -1, x, y);
                    // 找pivots中最后一个标准中枢
                    Pivot last_standard_pivot;
                    bool found = false;
                    for (auto it = pivots.rbegin(); it != pivots.rend(); ++it)
                    {
                        if (it->is_comprehensive)
                        {
                            last_standard_pivot = *it;
                            if (last_standard_pivot.zg > support_price)
                            {
                                found = true;
                            }               
                            break;
                        }
                    }
                    if (found)
                    {
                        // 找y后面突破中枢高点的K线
                        int v_idx = 0;
                        for (int k = y + 1; k < length && v_idx < 3; k++)
                        {
                            if ((close[k - 1] <= last_standard_pivot.zg || low[k] <= last_standard_pivot.zg) && close[k] > last_standard_pivot.zg)
                            {
                                // 找到突破点，设置买点信号
                                inner_result[k] = static_cast<int>(EntrypointType::ENTRYPOINT_BUY_OPEN_1);
                            }
                            if (wave_sigs[k] == 1)
                            {
                                break;
                            }
                            if (swing_sigs[k] == 1)
                            {
                                v_idx++;
                            }
                        }
                    }
                }
                // 从y向后查找z点
                for (int k = y + 1; k < length; k++)
                {
                    if (wave_sigs[k] == 1)
                    {
                        z = k;
                        break;
                    }
                }
                if (z > -1)
                {
                    std::vector<Pivot> pivots = locate_pivots(swing_sigs, high, low, 1, y, z);
                    // 对每个标准中枢寻找突破中枢高点的K线
                    for (const auto &pivot : pivots)
                    {
                        if (pivot.is_comprehensive)
                        {
                            for (int k = pivot.end; k <= z; k++)
                            {
                                if ((close[k - 1] <= pivot.zg || low[k] <= pivot.zg) && close[k] > pivot.zg)
                                {
                                    // 找到突破点，设置买点信号
                                    inner_result[k] = static_cast<int>(EntrypointType::ENTRYPOINT_BUY_OPEN_1);
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    void find_sell_signals(int origin_pos)
    {
        if (stretch_sigs[origin_pos] != 1)
        {
            return;
        }
        // 找到允许的最高阻力价格
        float resistance_price = 0;
        for (int i = origin_pos - 1; i >= 0; i--)
        {
            if (stretch_sigs[i] == -1)
            {
                auto pivots = locate_pivots(wave_sigs, high, low, 1, i, origin_pos);
                int pivots_num = static_cast<int>(pivots.size());
                if (pivots_num > 0)
                {
                    Pivot &last_pivot = pivots.back();
                    float price_diff_a = 0;
                    float price_diff_b = 0;
                    for (int m = last_pivot.start - 1; m >= i; m--)
                    {
                        if (wave_sigs[m] == -1)
                        {
                            price_diff_a = high[last_pivot.start] - low[m];
                            break;
                        }
                    }
                    price_diff_b = high[origin_pos] - low[last_pivot.end];
                    // 中枢低低作为一个阻力价格
                    if (price_diff_b < price_diff_a)
                    {
                        resistance_price = last_pivot.gg;
                    }
                }
                break;
            }
        }
        
        for (int j = origin_pos; j < length; j++)
        {
            // 又碰到一个向上线段的终点了，针对这个线段就不用再预警了。
            if (j > origin_pos && (high[j] > high[origin_pos] || stretch_sigs[j] == 1 || stretch_sigs[j] == 0.5))
            {
                break;
            }
            // 如果已经碰到两个笔中枢了，针对这个线段也不用再预警了。
            if (stretch_sigs[j] == -1)
            {
                auto pivots = locate_pivots(wave_sigs, high, low, -1, origin_pos, j);
                if (pivots.size() >= 2)
                {
                    int standard_count = 0;
                    for (const auto &pivot : pivots)
                    {
                        if (pivot.is_comprehensive)
                        {
                            standard_count++;
                        }
                    }
                    if (standard_count >= 2)
                    {
                        break;
                    }
                }
            }
            if (resistance_price == 0)
            {
                if (stretch_sigs[j] == -1 || stretch_sigs[j] == -0.5)
                {
                    resistance_price = high[origin_pos];
                }
                if (j > origin_pos && wave_sigs[j] == 1)
                {
                    resistance_price = high[origin_pos];
                }
            }
            
            if (resistance_price == 0)
            {
                continue;
            }
            if (wave_sigs[j] == 1)
            {
                // 遇到向上笔的高点，针对这个向上笔有没有卖点
                int x = -1;
                int y = j;
                int z = -1;
                // 向前查找x点，x点是wave_sigs[x] == -1的点，且x不能比i小
                for (int k = y - 1; k >= 0; k--)
                {
                    if (wave_sigs[k] == -1)
                    {
                        x = k;
                        break;
                    }
                }
                if (x > -1)
                {
                    std::vector<Pivot> pivots = locate_pivots(swing_sigs, high, low, 1, x, y);
                    // 找pivots中最后一个标准中枢
                    Pivot last_standard_pivot;
                    bool found = false;
                    for (auto it = pivots.rbegin(); it != pivots.rend(); ++it)
                    {
                        if (it->is_comprehensive)
                        {
                            last_standard_pivot = *it;
                            if (last_standard_pivot.zd < resistance_price)
                            {
                                found = true;
                            }               
                            break;
                        }
                    }
                    if (found)
                    {
                        // 找y后面突破中枢低点的K线
                        int v_idx = 0;
                        for (int k = y + 1; k < length && v_idx < 3; k++)
                        {
                            if ((close[k - 1] >= last_standard_pivot.zd || high[k] >= last_standard_pivot.zd) && close[k] < last_standard_pivot.zd)
                            {
                                // 找到突破点，设置卖点信号
                                inner_result[k] = static_cast<int>(EntrypointType::ENTRYPOINT_SELL_OPEN_1);
                            }
                            if (wave_sigs[k] == -1)
                            {
                                break;
                            }
                            if (swing_sigs[k] == -1)
                            {
                                v_idx++;
                            }
                        }
                    }
                }
                // 从y向后查找z点
                for (int k = y + 1; k < length; k++)
                {
                    if (wave_sigs[k] == -1)
                    {
                        z = k;
                        break;
                    }
                }
                if (z > -1)
                {
                    std::vector<Pivot> pivots = locate_pivots(swing_sigs, high, low, -1, y, z);
                    // 对每个标准中枢寻找突破中枢低点的K线
                    for (const auto &pivot : pivots)
                    {
                        if (pivot.is_comprehensive)
                        {
                            for (int k = pivot.end; k <= z; k++)
                            {
                                if ((close[k - 1] >= pivot.zd || high[k] >= pivot.zd) && close[k] < pivot.zd)
                                {
                                    // 找到突破点，设置卖点信号
                                    inner_result[k] = static_cast<int>(EntrypointType::ENTRYPOINT_SELL_OPEN_1);
                                }
                            }
                        }
                    }
                }
            }
        }
    }

public:
    TAILORED_S0001_Calculator(
        const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
        const std::vector<float> &vol,
        int switch_opt, const ChanOptions &options) : BaseCalculator(high, low, open, close, vol, switch_opt, options)
    {
        calculate();
    }
};

std::vector<int> TAILORED_F_S0001(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options)
{
    TAILORED_S0001_Calculator calculator(high, low, open, close, vol, switch_opt, options);
    return calculator.result();
}
