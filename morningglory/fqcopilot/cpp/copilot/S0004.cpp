#include "copilot.h"
#include "../common/log.h"
#include "../common/common.h"
#include "../chanlun/czsc.h"
#include "s.h"
#include "../indicator/indicator.h"
#include "signal_utils.h"
#include "base_calculator.h"

class S0004_Calculator : public BaseCalculator
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

    void find_buy_signals(int i)
    {
        // 第一种情况是针对下跌线段中的最后一个下跌中枢的三买
        // 传进来的i是线段的低点坐标
        // 先找到i前面的线段高点坐标
        int h = -1;
        for (int j = i - 1; j > -1; j--)
        {
            if (stretch_sigs[j] == 1)
            {
                h = j;
                break;
            }
        }
        // h > -1 说明找到了线段的高点坐标
        if (h > -1)
        {
            std::vector<Pivot> pivots = locate_pivots(wave_sigs, high, low, -1, h, i);
            if (pivots.size() > 0)
            {
                // 线段有笔中枢
                Pivot &pivot = pivots.back();
                // 找出线段低点为起点的后面两个向下笔的低点的坐标
                int v[2] = {-1, -1};
                int x = 0;
                for (int j = i + 1; j < length; j++)
                {
                    if (wave_sigs[j] == -1)
                    {
                        v[x] = j;
                        x++;
                        if (x == 2)
                        {
                            break;
                        }
                    }
                }
                // 判断这两个低点是否符合买点条件
                for (int j = 0; j < 2; j++)
                {
                    if (v[j] > -1 && low[v[j]] >= pivot.zg)
                    {
                        for (int n = v[j]; n < length; n++)
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
        // 第二种情况是针对第一个上涨中枢的三买
        // 找到j，i后面的第一个线段高点坐标
        int j = -1;
        for (int k = i + 1; k < length; k++)
        {
            if (stretch_sigs[k] == 1)
            {
                j = k;
                break;
            }
        }
        if (j > -1)
        {
            std::vector<Pivot> pivots = locate_pivots(wave_sigs, high, low, 1, i, j);
            if (pivots.size() > 0)
            {
                Pivot &pivot = pivots.front();
                int v[2] = {-1, -1};
                int x = 0;
                for (int k = pivot.end + 1; k < length; k++)
                {
                    if (wave_sigs[k] == -1)
                    {
                        v[x] = k;
                        x++;
                        if (x == 2)
                        {
                            break;
                        }
                    }
                }
                // 判断这两个低点是否符合买点条件
                for (int m = 0; m < 2; m++)
                {
                    if (v[m] > -1 && low[v[m]] >= pivot.zg)
                    {
                        for (int n = v[m]; n < length; n++)
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

    void find_sell_signals(int i)
    {
        // 第一种情况是针对上涨线段中的最后一个上涨中枢的三卖
        // 传进来的i是线段的高点坐标
        // 先找到i前面的线段低点坐标
        int l = -1;
        for (int j = i - 1; j > -1; j--)
        {
            if (stretch_sigs[j] == -1)
            {
                l = j;
                break;
            }
        }
        // l > -1 说明找到了线段的低点坐标
        if (l > -1)
        {
            std::vector<Pivot> pivots = locate_pivots(wave_sigs, high, low, 1, l, i);
            if (pivots.size() > 0)
            {
                // 线段有笔中枢
                Pivot &pivot = pivots.back();
                // 找出线段高点为起点的后面两个向上笔的高点的坐标
                int v[2] = {-1, -1};
                int x = 0;
                for (int j = i + 1; j < length; j++)
                {
                    if (wave_sigs[j] == 1)
                    {
                        v[x] = j;
                        x++;
                        if (x == 2)
                        {
                            break;
                        }
                    }
                }
                // 判断这两个高点是否符合卖点条件
                for (int j = 0; j < 2; j++)
                {
                    if (v[j] > -1 && high[v[j]] <= pivot.zd)
                    {
                        for (int n = v[j]; n < length; n++)
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
        // 第二种情况是针对第一个下跌中枢的三卖
        // 找到j，i后面的第一个线段低点坐标
        int j = -1;
        for (int k = i + 1; k < length; k++)
        {
            if (stretch_sigs[k] == -1)
            {
                j = k;
                break;
            }
        }
        if (j > -1)
        {
            std::vector<Pivot> pivots = locate_pivots(wave_sigs, high, low, -1, i, j);
            if (pivots.size() > 0)
            {
                Pivot &pivot = pivots.front();
                int v[2] = {-1, -1};
                int x = 0;
                for (int k = pivot.end + 1; k < length; k++)
                {
                    if (wave_sigs[k] == 1)
                    {
                        v[x] = k;
                        x++;
                        if (x == 2)
                        {
                            break;
                        }
                    }
                }
                // 判断这两个高点是否符合卖点条件
                for (int m = 0; m < 2; m++)
                {
                    if (v[m] > -1 && high[v[m]] <= pivot.zd)
                    {
                        for (int n = v[m]; n < length; n++)
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
    S0004_Calculator(
        const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
        const std::vector<float> &vol,
        int switch_opt, const ChanOptions &options) : BaseCalculator(high, low, open, close, vol, switch_opt, options)
    {
        calculate();
    }

};

std::vector<int> F_S0004(const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options)
{
    S0004_Calculator calculator(high, low, open, close, vol, switch_opt, options);
    return calculator.result();
}
