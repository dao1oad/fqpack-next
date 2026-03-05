#include "copilot.h"
#include "../common/log.h"
#include "../common/common.h"
#include "../chanlun/czsc.h"
#include "s.h"
#include "../indicator/indicator.h"
#include "signal_utils.h"
#include "base_calculator.h"

class S0003_Calculator : public BaseCalculator
{
private:
    void calculate()
    {

        for (int i = 0; i < length; i++)
        {
            if (stretch_sigs[i] == -1)
            {
                find_buy_signals(i);
            }
            else if (stretch_sigs[i] == 1)
            {
                find_sell_signals(i);
            }
        }
    }

    void find_buy_signals(int start_idx)
    {
        int v[9] = {start_idx, 0, 0, 0, 0, 0, 0, 0, 0};
        int x = 0;
        for (int j = v[x] + 1; j < length; j++)
        {
            if (wave_sigs[j] == 1 || wave_sigs[j] == -1)
            {
                x = x + 1;
                v[x] = j;
                if (x == 8)
                {
                    break;
                }
            }
        }
        // Handle both x == 7 and x == 8 cases
        if (x >= 6)
        {
            if (x == 7)
            {
                x = 6;
            }
            // Check if low[v[0]] is the minimum among relevant pivots
            bool is_min = true;
            for (int k = 2; k <= 6; k += 2)
            {
                if (low[v[0]] > low[v[k]])
                {
                    is_min = false;
                    break;
                }
            }

            if (is_min)
            {
                // Check the zigzag pattern
                bool pattern_ok = (high[v[3]] < high[v[1]] &&
                                   low[v[4]] < low[v[2]] &&
                                   high[v[5]] > high[v[3]] &&
                                   low[v[6]] > low[v[4]]);
                if (pattern_ok)
                {
                    int s0 = static_cast<int>(v[6]);
                    for (int n = s0; n < length; n++)
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
                    if (x == 8 && low[v[0]] < low[v[8]] && low[v[8]] > low[v[4]])
                    {
                        int s0 = static_cast<int>(v[8]);
                        for (int n = s0; n < length; n++)
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
                }
            }
        }
    }

    void find_sell_signals(int start_idx)
    {
        int v[9] = {start_idx, 0, 0, 0, 0, 0, 0, 0, 0};
        size_t x = 0;
        for (int j = v[x] + 1; j < length; j++)
        {
            if (wave_sigs[j] == 1 || wave_sigs[j] == -1)
            {
                x = x + 1;
                v[x] = j;
                if (x == 8)
                {
                    break;
                }
            }
        }
        // Handle both x == 7 and x == 8 cases
        if (x >= 6)
        {
            if (x == 7)
            {
                x = 6;
            }
            // Check if high[v[0]] is the maximum among relevant pivots
            bool is_max = true;
            for (int k = 2; k <= 6; k += 2)
            {
                if (high[v[0]] < high[v[k]])
                {
                    is_max = false;
                    break;
                }
            }

            if (is_max)
            {
                // Check the inverted zigzag pattern
                bool pattern_ok = (low[v[3]] > low[v[1]] &&
                                   high[v[4]] > high[v[2]] &&
                                   low[v[5]] < low[v[3]] &&
                                   high[v[6]] < high[v[4]]);
                if (pattern_ok)
                {
                    int s0 = static_cast<int>(v[6]);
                    for (int n = s0; n < length; n++)
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
                    if (x == 8 && high[v[0]] > high[v[8]] && high[v[8]] < high[v[4]])
                    {
                        int s0 = static_cast<int>(v[8]);
                        for (int n = s0; n < length; n++)
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
                }
            }
        }
    }

public:
    S0003_Calculator(
        const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
        const std::vector<float> &vol,
        int switch_opt, const ChanOptions &options) : BaseCalculator(high, low, open, close, vol, switch_opt, options)
    {
        calculate();
    }

};

std::vector<int> F_S0003(const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options)
{
    S0003_Calculator calculator(high, low, open, close, vol, switch_opt, options);
    return calculator.result();
}
