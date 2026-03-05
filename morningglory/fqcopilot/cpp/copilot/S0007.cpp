#include "copilot.h"
#include "../common/log.h"
#include "../common/common.h"
#include "../chanlun/czsc.h"
#include "s.h"
#include "../indicator/indicator.h"
#include "signal_utils.h"
#include "base_calculator.h"

// 顶底互换的选股模型
class S0007_Calculator : public BaseCalculator
{
private:

    void calculate()
    {

        for (int i = 0; i < length; i++)
        {
            if (wave_sigs[i] == 1)
            {
                find_buy_signals(i);
            }
            else if (wave_sigs[i] == -1)
            {
                find_sell_signals(i);
            }
        }
    }

    void find_buy_signals(int origin_pos)
    {
        int v[3] = {-1, -1, -1};
        int found = 0;
        
        // 从origin_pos开始向后查找
        for (int i = origin_pos + 1; i < length && found < 3; i++) {
            if (wave_sigs[i] == -1) {  // 找到笔的低点
                v[found] = i;
                found++;
            }
        }
        float price_range_high = high[origin_pos] + 2 * atrs[origin_pos];
        float price_range_low = high[origin_pos];
        for (int k = 1; k < 3; k++)
        {
            int i = v[k];
            if (i >= 0 && std::min(open[i], close[i]) >= price_range_low && low[i] <= price_range_high)
            {
                for (int n = i; n < length; n++)
                {
                    if (wave_sigs[n] == 1)
                    {
                        break;
                    }

                    EntrypointType signal = SignalUtils::is_buy_signal(
                        n, high, low, open, close, vol, wave_sigs, std_bars, ma5, macd);

                    if (signal != EntrypointType::ENTRYPOINT_UNKNOWN)
                    {
                        inner_result[n] = static_cast<int>(signal);
                        break;
                    }
                }
            }
            else if (low[i] < price_range_low)
            {
                break;
            }
        }
    }

    void find_sell_signals(int origin_pos)
    {
        int v[3] = {-1, -1, -1};
        int found = 0;
        
        // 从origin_pos开始向后查找
        for (int i = origin_pos + 1; i < length && found < 3; i++) {
            if (wave_sigs[i] == 1) {  // 找到笔的高点
                v[found] = i;
                found++;
            }
        }
        float price_range_high = low[origin_pos];
        float price_range_low = low[origin_pos] - 2 * atrs[origin_pos];
        for (int k = 1; k < 3; k++)
        {
            int i = v[k];
            if (i >= 0 && std::max(open[i], close[i]) <= price_range_high && high[i] >= price_range_low)
            {
                for (int n = i; n < length; n++)
                {
                    if (wave_sigs[n] == -1)
                    {
                        break;
                    }

                    EntrypointType signal = SignalUtils::is_sell_signal(
                        n, high, low, open, close, vol, wave_sigs, std_bars, ma5, macd);

                    if (signal != EntrypointType::ENTRYPOINT_UNKNOWN)
                    {
                        inner_result[n] = static_cast<int>(signal);
                        break;
                    }
                }
            }
            else if (high[i] > price_range_high)
            {
                break;
            }
        }
    }

public:
    S0007_Calculator(
        const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
        const std::vector<float> &vol,
        int switch_opt, const ChanOptions &options) : BaseCalculator(high, low, open, close, vol, switch_opt, options)
    {
        calculate();
    }

};

std::vector<int> F_S0007(const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options)
{
    S0007_Calculator calculator(high, low, open, close, vol, switch_opt, options);
    return calculator.result();
}
