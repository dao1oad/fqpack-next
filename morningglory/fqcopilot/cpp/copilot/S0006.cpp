#include "copilot.h"
#include "../common/log.h"
#include "../common/common.h"
#include "../chanlun/czsc.h"
#include "s.h"
#include "../indicator/indicator.h"
#include "signal_utils.h"
#include "base_calculator.h"

class S0006_Calculator : public BaseCalculator
{
private:

    void calculate()
    {

        for (int i = 0; i < length; i++)
        {
            if (stretch_sigs[i] == -1 || stretch_sigs[i] == -0.5)
            {
                find_buy_signals(i);
            }
            else if (stretch_sigs[i] == 1 || stretch_sigs[i] == 0.5)
            {
                find_sell_signals(i);
            }
        }
    }

    void find_buy_signals(int origin_pos)
    {
        // 先找到前一个线段的低点
        int v[2] = {-1, -1};
        int x = 0;
        int i = origin_pos - 1;
        for (; i >= 0; i--)
        {
            if (stretch_sigs[i] == -1)
            {
                v[x] = i;
                x = x + 1;
                if (x == 2)
                {
                    break;
                }
            }
        }
        for (int k = 0; k < 2; k++)
        {
            i = v[k];
            if (i >= 0)
            {
                float price_range_high = low[i] + 2 * atrs[i];
                float price_range_low = low[i] - 2 * atrs[i];
                if (low[origin_pos] >= price_range_low && low[origin_pos] <= price_range_high)
                {
                    for (int n = origin_pos; n < length; n++)
                    {
                        if (wave_sigs[n] == 1)
                        {
                            break;
                        }

                        EntrypointType signal = SignalUtils::is_buy_signal(
                            n, high, low, open, close, vol, wave_sigs, std_bars, ma5, macd);

                        if (signal != EntrypointType::ENTRYPOINT_UNKNOWN)
                        {
                            if (close[n] >= low[i])
                            {
                                inner_result[n] = static_cast<int>(signal);
                            }
                            break;
                        }
                    }
                }
            }
        }
    }

    void find_sell_signals(int origin_pos)
    {
        // 先找到前两个线段的高点
        int v[2] = {-1, -1};
        int x = 0;
        int i = origin_pos - 1;
        for (; i >= 0; i--)
        {
            if (stretch_sigs[i] == 1)
            {
                v[x] = i;
                x = x + 1;
                if (x == 2)
                {
                    break;
                }
            }
        }
        for (int k = 0; k < 2; k++)
        {
            i = v[k];
            if (i >= 0)
            {
                float price_range_high = high[i] + 2 * atrs[i];
                float price_range_low = high[i] - 2 * atrs[i];
                if (high[origin_pos] >= price_range_low && high[origin_pos] <= price_range_high)
                {
                    for (int n = origin_pos; n < length; n++)
                    {
                        if (wave_sigs[n] == -1)
                        {
                            break;
                        }

                        EntrypointType signal = SignalUtils::is_sell_signal(
                            n, high, low, open, close, vol, wave_sigs, std_bars, ma5, macd);

                        if (signal != EntrypointType::ENTRYPOINT_UNKNOWN)
                        {
                            if (close[n] <= high[i])
                            {
                                inner_result[n] = static_cast<int>(signal);
                            }
                            break;
                        }
                    }
                }
            }
        }
    }

public:
    S0006_Calculator(
        const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
        const std::vector<float> &vol,
        int switch_opt, const ChanOptions &options) : BaseCalculator(high, low, open, close, vol, switch_opt, options)
    {
        calculate();
    }
};

std::vector<int> F_S0006(const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options)
{
    S0006_Calculator calculator(high, low, open, close, vol, switch_opt, options);
    return calculator.result();
}
