#include "copilot.h"
#include "../common/log.h"
#include "../common/common.h"
#include "../chanlun/czsc.h"
#include "s.h"
#include "../indicator/indicator.h"
#include "signal_utils.h"
#include "base_calculator.h"

class S0005_Calculator : public BaseCalculator
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
        // 立足一个线段的低点开始寻找，不是线段低点不用找
        if (stretch_sigs[origin_pos] != -1 && stretch_sigs[origin_pos] != -0.5)
        {
            return;
        }
        // 找到这个线段的起点
        int i = origin_pos - 1;
        for (; i >= 0; i--)
        {
            if (stretch_sigs[i] == 1)
            {
                break;
            }
        }
        // 没有找到线段起点就不用继续了
        if (i < 0)
        {
            return;
        }
        // 找到这个线段中的笔中枢
        std::vector<Pivot> pivots = locate_pivots(wave_sigs, high, low, -1, i, origin_pos);
        if (pivots.empty())
        {
            return;
        }
        Pivot &pivot = pivots.back();
        int hv[3] = {-1, -1, -1};
        int lv[3] = {-1, -1, -1};
        // 找向上一笔的结束点
        int j = origin_pos + 1;
        int c = 0;
        for (; j < length && c < 3; j++)
        {
            if (wave_sigs[j] == 1)
            {
                hv[c] = j;
                // switch_opt == 1 时，上一笔的高点必须大于中枢的高点
                // switch_opt == 0 时，上一笔的低点必须大于中枢的低点
                if (switch_opt == 1)
                {

                    if (!(high[hv[0]] > pivot.zg))
                    {
                        break;
                    }
                }
                else
                {
                    if (!(high[hv[0]] > pivot.zd))
                    {
                        break;
                    }
                }
                // 找下跌一笔的结束点
                int k = j + 1;
                for (; k < length; k++)
                {
                    if (wave_sigs[k] == -1)
                    {
                        // 下跌一笔起点还低了，不用找了
                        if (low[k] < low[origin_pos])
                        {
                            j = length; // 设置j=length来跳出外层循环
                            break;
                        }
                        if (c >= 2)
                        {
                            if (low[k] < std::min(low[lv[c-1]], low[lv[c - 2]]))
                            {
                                j = length;
                                break;
                            }
                        }
                        lv[c] = k;
                        c++;
                        break;
                    }
                }
            }
        }

        // 从下跌一笔的结束点开始找买点
        for (int x = 0; x < 3; x++)
        {
            for (int n = lv[x]; n < length && lv[x] > -1; n++)
            {
                if (wave_sigs[n] == 1)
                {
                    break;
                }
                EntrypointType signal = SignalUtils::is_buy_signal(
                    n, high, low, open, close, vol, wave_sigs, std_bars, ma5, macd);

                if (signal != EntrypointType::ENTRYPOINT_UNKNOWN)
                {
                    inner_result[n] = (x + 1) * 100 + static_cast<int>(signal);
                    break;
                }
            }
        }
    }

    void find_sell_signals(int origin_pos)
    {
        // 立足一个线段的高点开始寻找，不是线段高点不用找
        if (stretch_sigs[origin_pos] != 1 && stretch_sigs[origin_pos] != 0.5)
        {
            return;
        }
        // 找到这个线段的起点
        int i = origin_pos - 1;
        for (; i >= 0; i--)
        {
            if (stretch_sigs[i] == -1)
            {
                break;
            }
        }
        // 没有找到线段起点就不用继续了
        if (i < 0)
        {
            return;
        }
        // 找到这个线段中的笔中枢
        std::vector<Pivot> pivots = locate_pivots(wave_sigs, high, low, 1, i, origin_pos);
        if (pivots.empty())
        {
            return;
        }
        Pivot &pivot = pivots.back();
        int lv[3] = {-1, -1, -1};
        int hv[3] = {-1, -1, -1};
        // 找向下一笔的结束点
        int j = origin_pos + 1;
        int c = 0;
        for (; j < length && c < 3; j++)
        {
            if (wave_sigs[j] == -1)
            {
                lv[c] = j;
                // switch_opt == 1 时，上一笔的低点必须小于中枢的低点
                // switch_opt == 0 时，上一笔的高点必须小于中枢的高点
                if (switch_opt == 1)
                {
                    if (!(low[lv[0]] < pivot.zd))
                    {
                        break;
                    }
                }
                else
                {
                    if (!(low[lv[0]] < pivot.zg))
                    {
                        break;
                    }
                }
                // 找上涨一笔的结束点
                int k = j + 1;
                for (; k < length; k++)
                {
                    if (wave_sigs[k] == 1)
                    {
                        // 上涨一笔起点还高了，不用找了
                        if (high[k] > high[origin_pos])
                        {
                            j = length; // 设置j=length来跳出外层循环
                            break;
                        }
                        if (c >= 2)
                        {
                            if (high[k] > std::max(high[hv[c-1]], high[hv[c - 2]]))
                            {
                                j = length;
                                break;
                            }
                        }
                        hv[c] = k;
                        c++;
                        break;
                    }
                }
            }
        }

        // 从上涨一笔的结束点开始找卖点
        for (int x = 0; x < 3; x++)
        {
            for (int n = hv[x]; n < length && hv[x] > -1; n++)
            {
                if (wave_sigs[n] == -1)
                {
                    break;
                }
                EntrypointType signal = SignalUtils::is_sell_signal(
                    n, high, low, open, close, vol, wave_sigs, std_bars, ma5, macd);

                if (signal != EntrypointType::ENTRYPOINT_UNKNOWN)
                {
                    inner_result[n] = -(x + 1) * 100 + static_cast<int>(signal);
                    break;
                }
            }
        }
    }

public:
    S0005_Calculator(
        const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
        const std::vector<float> &vol,
        int switch_opt, const ChanOptions &options) : BaseCalculator(high, low, open, close, vol, switch_opt, options)
    {
        calculate();
    }
};

std::vector<int> F_S0005(const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
                         const std::vector<float> &vol, int switch_opt, const ChanOptions &options)
{
    S0005_Calculator calculator(high, low, open, close, vol, switch_opt, options);
    return calculator.result();
}
