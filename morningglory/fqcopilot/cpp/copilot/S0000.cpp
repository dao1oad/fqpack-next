#include "copilot.h"
#include "../common/log.h"
#include "../common/common.h"
#include "../chanlun/czsc.h"
#include "../indicator/indicator.h"
#include "s.h"
#include "signal_utils.h"
#include "base_calculator.h"

class S0000_Calculator : public BaseCalculator
{
private:
    void calculate() override
    {
        for (int i = 0; i < length; ++i)
        {
            if (wave_sigs[i] == 0.5 || wave_sigs[i] == 1)
            {
                find_sell_sigs(i);
            }
            else if (wave_sigs[i] == -0.5 || wave_sigs[i] == -1)
            {
                find_buy_sigs(i);
            }
        }
    }

    void find_buy_sigs(int pos)
    {
        for (int i = pos; i < length; ++i)
        {
            if (wave_sigs[i] == 0.5 || wave_sigs[i] == 1)
            {
                break;
            }
            EntrypointType signal = SignalUtils::is_buy_signal(
                i, high, low, open, close, vol, wave_sigs, std_bars, ma5, macd);

            if (signal != EntrypointType::ENTRYPOINT_UNKNOWN)
            {
                inner_result[i] = 100 + static_cast<int>(signal);
                break;
            }
        }
    }

    void find_sell_sigs(int pos)
    {
        for (int i = pos; i < length; ++i)
        {
            if (wave_sigs[i] == -0.5 || wave_sigs[i] == -1)
            {
                break;
            }
            EntrypointType signal = SignalUtils::is_sell_signal(
                i, high, low, open, close, vol, wave_sigs, std_bars, ma5, macd);

            if (signal != EntrypointType::ENTRYPOINT_UNKNOWN)
            {
                inner_result[i] = -100 - static_cast<int>(signal);
                break;
            }
        }
    }

public:
    S0000_Calculator(
        const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
        const std::vector<float> &vol,
        int switch_opt, const ChanOptions &options) : BaseCalculator(high, low, open, close, vol, switch_opt, options)
    {
        calculate();
    }
};

std::vector<int> F_S0000(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options)
{
    S0000_Calculator calculator(high, low, open, close, vol, switch_opt, options);
    return calculator.result();
}
