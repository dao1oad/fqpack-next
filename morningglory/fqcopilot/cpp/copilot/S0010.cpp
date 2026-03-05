#include "copilot.h"
#include "../chanlun/czsc.h"
#include "signal_utils.h"
#include "base_calculator.h"


class S0010_Calculator : public BaseCalculator
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
            if (stretch_sigs[i] == 0.5 || stretch_sigs[i] == 1.0)
            {
                if (switch_opt == 0 || (switch_opt == 1 && trend_type == -1))
                {
                    find_buy_signals(i);
                }
            }
            else if (stretch_sigs[i] == -0.5 || stretch_sigs[i] == -1.0)
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
            if (stretch_sigs[x] == -1)
            {
                i = x;
                break;
            }
        }
        if (i >= 0)
        {
            std::vector<Pivot> pivots = locate_pivots(wave_sigs, high, low, 1, i, j);
            int pivots_num = static_cast<int>(pivots.size());
            int comprehensive_pivot_num = 0;
            for (int x = 0; x < pivots_num && comprehensive_pivot_num < 2; x++)
            {
                Pivot &pivot = pivots[x];
                int leave_wave_end = -1;
                for (int y = pivot.end + 1; y <= origin_pos; y++)
                {
                    if (wave_sigs[y] == 1)
                    {
                        leave_wave_end = y;
                        break;
                    }
                }
                if (leave_wave_end > -1)
                {
                    int m = -1;
                    for (int y = leave_wave_end + 1; y < length; y++)
                    {
                        if (wave_sigs[y] == -1)
                        {
                            m = y;
                            break;
                        }
                    }
                    if (m > -1)
                    {
                        for (int n = m; n < length; n++)
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
                if (pivot.is_comprehensive)
                {
                    comprehensive_pivot_num++;
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
            if (stretch_sigs[x] == 1)
            {
                i = x;
                break;
            }
        }
        if (i >= 0)
        {
            std::vector<Pivot> pivots = locate_pivots(wave_sigs, high, low, -1, i, j);
            int pivots_num = static_cast<int>(pivots.size());
            int comprehensive_pivot_num = 0;
            for (int x = 0; x < pivots_num && comprehensive_pivot_num < 2; x++)
            {
                Pivot &pivot = pivots[x];
                int leave_wave_end = -1;
                for (int y = pivot.end + 1; y <= origin_pos; y++)
                {
                    if (wave_sigs[y] == -1)
                    {
                        leave_wave_end = y;
                        break;
                    }
                }
                if (leave_wave_end > -1)
                {
                    int m = -1;
                    for (int y = leave_wave_end + 1; y < length; y++)
                    {
                        if (wave_sigs[y] == 1)
                        {
                            m = y;
                            break;
                        }
                    }
                    if (m > -1)
                    {
                        for (int n = m; n < length; n++)
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
                if (pivot.is_comprehensive)
                {
                    comprehensive_pivot_num++;
                }
            }
        }
    }

public:
    S0010_Calculator(
        const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
        const std::vector<float> &vol,
        int switch_opt, const ChanOptions &options) : BaseCalculator(high, low, open, close, vol, switch_opt, options)
    {
        calculate();
    }
};

std::vector<int> F_S0010(const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
                         const std::vector<float> &vol, int switch_opt, const ChanOptions &options)
{
    S0010_Calculator calculator(high, low, open, close, vol, switch_opt, options);
    return calculator.result();
}
