#include "copilot.h"
#include "../common/log.h"
#include "../common/common.h"
#include "../chanlun/czsc.h"
#include "../indicator/indicator.h"
#include "s.h"
#include "signal_utils.h"
#include "base_calculator.h"

class S0001_Calculator : public BaseCalculator
{
private:
    void calculate() override
    {
        if (switch_opt == 1)
        {
            std::vector<Trend> trends = find_trends(trend_sigs, 0, length - 1);
            for (size_t i = 0; i < trends.size(); i++)
            {
                if (trends[i].direction == DirectionType::DIRECTION_DOWN)
                {
                    // 在向下走势中找买点
                    std::vector<Stretch> stretches = find_stretches(stretch_sigs, trends[i].start, trends[i].end);
                    find_buy_sigs(stretches);
                }
                else if (trends[i].direction == DirectionType::DIRECTION_UP)
                {
                    // 在向上走势中找卖点
                    std::vector<Stretch> stretches = find_stretches(stretch_sigs, trends[i].start, trends[i].end);
                    find_sell_sigs(stretches);
                }
            }
        }
        else
        {
            std::vector<Stretch> stretches = find_stretches(stretch_sigs, 0, length - 1);
            // 在向下线段中找买点
            find_buy_sigs(stretches);
            // 在向上线段中找卖点
            find_sell_sigs(stretches);
        }
    }

    void find_buy_sigs(std::vector<Stretch> &stretches)
    {
        int stretchCount = 0;
        float stretchLow = 0;
        for (size_t k = 0; k < stretches.size(); k++)
        {
            stretchCount++;
            if (stretches[k].direction == DirectionType::DIRECTION_DOWN)
            {
                if (switch_opt == 1)
                {
                    if (stretchLow == 0)
                    {
                        stretchLow = low[stretches[k].end];
                    }
                    if (stretchCount < 5)
                    {
                        if (low[stretches[k].end] < stretchLow)
                        {
                            stretchLow = low[stretches[k].end];
                        }
                        continue;
                    }
                    if (low[stretches[k].end] > stretchLow)
                    {
                        continue;
                    }
                    else
                    {
                        stretchLow = low[stretches[k].end];
                    }
                }
                // 在向下线段中找买点
                std::vector<Wave> waves = find_waves(wave_sigs, stretches[k].start, stretches[k].end);
                int waveCount = 0;
                float waveLow = 0;
                for (size_t m = 0; m < waves.size(); m++)
                {
                    waveCount++;
                    if (waves[m].direction == DirectionType::DIRECTION_DOWN)
                    {
                        if (waveLow == 0)
                        {
                            waveLow = low[waves[m].end];
                        }
                        if (waveCount < 5)
                        {
                            if (low[waves[m].end] < waveLow)
                            {
                                waveLow = low[waves[m].end];
                            }
                            continue;
                        }
                        if (low[waves[m].end] > waveLow)
                        {
                            continue;
                        }
                        else
                        {
                            waveLow = low[waves[m].end];
                        }
                        if (k > 1 && m > 1)
                        {
                            int s0 = waves[m].end;
                            int count = 0;
                            for (int n = s0; n < length; n++)
                            {
                                if (low[n] < low[s0])
                                {
                                    // 新低了，没有买点
                                    break;
                                }
                                if (count == 2 && wave_sigs[n] == 1)
                                {
                                    // 2次向下笔后， 向上成笔了，没有买点
                                    break;
                                }
                                if (wave_sigs[n] == -1 && n > s0)
                                {
                                    // 计算第几次向下笔
                                    count++;
                                }
                                if (count == 2)
                                {
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
        }
    }

    void find_sell_sigs(std::vector<Stretch> &stretches)
    {
        int stretchCount = 0;
        float stretchHigh = 0;
        for (size_t k = 0; k < stretches.size(); k++)
        {
            stretchCount++;
            if (stretches[k].direction == DirectionType::DIRECTION_UP)
            {
                if (switch_opt == 1)
                {
                    if (stretchHigh == 0)
                    {
                        stretchHigh = high[stretches[k].end];
                    }
                    if (stretchCount < 5)
                    {
                        if (high[stretches[k].end] > stretchHigh)
                        {
                            stretchHigh = high[stretches[k].end];
                        }
                        continue;
                    }
                    if (high[stretches[k].end] < stretchHigh)
                    {
                        continue;
                    }
                    else
                    {
                        stretchHigh = high[stretches[k].end];
                    }
                }

                // 在向上线段中找卖点
                std::vector<Wave> waves = find_waves(wave_sigs, stretches[k].start, stretches[k].end);
                int waveCount = 0;
                float waveHigh = 0;
                for (size_t m = 0; m < waves.size(); m++)
                {
                    waveCount++;
                    if (waves[m].direction == DirectionType::DIRECTION_UP)
                    {
                        if (waveHigh == 0)
                        {
                            waveHigh = high[waves[m].end];
                        }
                        if (waveCount < 5)
                        {
                            if (high[waves[m].end] > waveHigh)
                            {
                                waveHigh = high[waves[m].end];
                            }
                            continue;
                        }
                        if (high[waves[m].end] < waveHigh)
                        {
                            continue;
                        }
                        else
                        {
                            waveHigh = high[waves[m].end];
                        }
                        if (k > 1 && m > 1)
                        {
                            int s0 = waves[m].end;
                            int count = 0;
                            for (int n = s0; n < length; n++)
                            {
                                if (high[n] > high[s0])
                                {
                                    // 新高了，没有卖点
                                    break;
                                }
                                if (count == 2 && wave_sigs[n] == -1)
                                {
                                    // 2次向上笔后， 向下成笔了，没有卖点
                                    break;
                                }
                                if (wave_sigs[n] == 1 && n > s0)
                                {
                                    // 计算第几次向上笔
                                    count++;
                                }
                                if (count == 2)
                                {
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
        }
    }

public:
    S0001_Calculator(
        const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
        const std::vector<float> &vol,
        int switch_opt, const ChanOptions &options) : BaseCalculator(high, low, open, close, vol, switch_opt, options)
    {
        calculate();
    }
};

std::vector<int> F_S0001(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options)
{
    S0001_Calculator calculator(high, low, open, close, vol, switch_opt, options);
    return calculator.result();
}
