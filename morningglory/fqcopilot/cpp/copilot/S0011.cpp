#include "copilot.h"
#include "../chanlun/czsc.h"
#include "signal_utils.h"
#include "base_calculator.h"


class S0011_Calculator : public BaseCalculator
{
private:
    void calculate()
    {
        int trend_type = 0;
        for (int i = 0; i < length; i++)
        {
            if (trend_sigs[i] == 0.5 || trend_sigs[i] == 1)
            {
                trend_type = 1;
            }
            else if (trend_sigs[i] == -0.5 || trend_sigs[i] == -1)
            {
                trend_type = -1;
            }
            if (stretch_sigs[i] == -0.5 || stretch_sigs[i] == -1.0)
            {
                if (switch_opt == 0 || (switch_opt == 1 && trend_type == -1))
                {
                    find_buy_signals(i);
                }
            }
            else if (stretch_sigs[i] == 0.5 || stretch_sigs[i] == 1.0)
            {
                if (switch_opt == 0 || (switch_opt == 1 && trend_type == 1))
                {
                    find_sell_signals(i);
                }
            }
        }
    }

    void find_buy_signals(int origin_pos)
    {
        int i = -1;
        int j = origin_pos;
        for (int x = origin_pos - 1; x >= 0; x--)
        {
            if (stretch_sigs[x] == 1.0)
            {
                i = x;
                break;
            }
        }
        if (i >= 0)
        {
            std::unordered_map<float, int> values_num = count_values_float(wave_sigs, {1.0, -1.0}, i, j, false);
            int total_count = 0;
            for (const auto &pair : values_num)
            {
                total_count += pair.second;
            }
            if (total_count >= 4)
            {
                int a = -1;
                int b = -1;
                int c = -1;
                for (int x = j; x >= 0; x--)
                {
                    if (wave_sigs[x] == 1.0)
                    {
                        a = x;
                        break;
                    }
                }
                for (int x = j; x < length; x++)
                {
                    if (wave_sigs[x] == 1.0)
                    {
                        b = x;
                        break;
                    }
                }
                if (a >= 0 && b >= 0 && high[b] > high[a])
                {
                    for (int x = b + 1; x < length; x++)
                    {
                        if (wave_sigs[x] == -1.0)
                        {
                            c = x;
                            break;
                        }
                    }
                }
                if (c >= 0)
                {
                    for (int n = c; n < length; n++)
                    {
                        if (wave_sigs[n] == 1)
                        {
                            break;
                        }
                        EntrypointType signal = SignalUtils::is_buy_signal(
                            n, high, low, open, close, vol, wave_sigs, std_bars, ma5, macd);

                        if (signal != EntrypointType::ENTRYPOINT_UNKNOWN)
                        {
                            inner_result[n] = 100 + static_cast<int>(signal);
                            break;
                        }
                    }
                }
            }
        }
    }

    void find_sell_signals(int origin_pos)
    {
        int i = -1;
        int j = origin_pos;
        for (int x = origin_pos - 1; x >= 0; x--)
        {
            if (stretch_sigs[x] == -1.0)
            {
                i = x;
                break;
            }
        }
        if (i >= 0)
        {
            std::unordered_map<float, int> values_num = count_values_float(wave_sigs, {1.0, -1.0}, i, j, false);
            int total_count = 0;
            for (const auto &pair : values_num)
            {
                total_count += pair.second;
            }
            if (total_count >= 4)
            {
                int a = -1;
                int b = -1;
                int c = -1;
                for (int x = j; x >= 0; x--)
                {
                    if (wave_sigs[x] == -1.0)
                    {
                        a = x;
                        break;
                    }
                }
                for (int x = j; x < length; x++)
                {
                    if (wave_sigs[x] == -1.0)
                    {
                        b = x;
                        break;
                    }
                }
                if (a >= 0 && b >= 0 && low[b] < low[a])
                {
                    for (int x = b + 1; x < length; x++)
                    {
                        if (wave_sigs[x] == 1.0)
                        {
                            c = x;
                            break;
                        }
                    }
                }
                if (c >= 0)
                {
                    for (int n = c; n < length; n++)
                    {
                        if (wave_sigs[n] == -1)
                        {
                            break;
                        }
                        EntrypointType signal = SignalUtils::is_sell_signal(
                            n, high, low, open, close, vol, wave_sigs, std_bars, ma5, macd);

                        if (signal != EntrypointType::ENTRYPOINT_UNKNOWN)
                        {
                            inner_result[n] = -100 - static_cast<int>(signal);
                            break;
                        }
                    }
                }
            }
        }
    }

public:
    S0011_Calculator(
        const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
        const std::vector<float> &vol,
        int switch_opt, const ChanOptions &options) : BaseCalculator(high, low, open, close, vol, switch_opt, options)
    {
        calculate();
    }
};

std::vector<int> F_S0011(const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
                         const std::vector<float> &vol, int switch_opt, const ChanOptions &options)
{
    S0011_Calculator calculator(high, low, open, close, vol, switch_opt, options);
    return calculator.result();
}
