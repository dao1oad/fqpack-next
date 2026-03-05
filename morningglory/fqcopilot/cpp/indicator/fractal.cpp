#include <vector>
#include <map>
#include "indicator.h"
#include "../chanlun/czsc.h"

std::vector<float> STRONG_FACTAL(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &bi, const std::vector<StdBar> &std_bars)
{
    auto result = std::vector<float>(high.size(), 0);
    // 创建一个map，保存每个原始K线的索引对应到哪个标准K线的索引
    std::map<int, int> raw_to_std_map;
    int std_bars_num = static_cast<int>(std_bars.size());
    for (int i = 0; i < std_bars_num; i++)
    {
        for (int j = std_bars[i].start; j <= std_bars[i].end; j++)
        {
            raw_to_std_map[j] = i;
        }
    }
    int size = static_cast<int>(high.size());
    int bi_num = static_cast<int>(bi.size());
    for (int i = 0; i < bi_num; i++)
    {
        if (bi[i] == 1)
        {
            int std_bar_index = raw_to_std_map[i];
            if (std_bar_index > 0 && i + 1 < size)
            {
                float prev_low = std_bars[std_bar_index - 1].low;
                if (close[i + 1] < prev_low)
                {
                    result[i + 1] = -1;
                }
            }
        }
        else if (bi[i] == -1)
        {
            int std_bar_index = raw_to_std_map[i];
            if (std_bar_index > 0 && i + 1 < size)
            {
                float prev_high = std_bars[std_bar_index - 1].high;
                if (close[i + 1] > prev_high)
                {
                    result[i + 1] = 1;
                }
            }
        }
    }
    return result;
}

std::vector<float> NORMAL_FACTAL(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &bi, const std::vector<StdBar> &std_bars)
{
    auto result = std::vector<float>(high.size(), 0);
    // 创建一个map，保存每个原始K线的索引对应到哪个标准K线的索引
    std::map<int, int> raw_to_std_map;
    int std_bars_num = static_cast<int>(std_bars.size());
    for (int i = 0; i < std_bars_num; i++)
    {
        for (int j = std_bars[i].start; j <= std_bars[i].end; j++)
        {
            raw_to_std_map[j] = i;
        }
    }
    int size = static_cast<int>(high.size());
    int bi_num = static_cast<int>(bi.size());
    for (int i = 0; i < bi_num; i++)
    {
        if (bi[i] == 1)
        {
            int std_bar_index = raw_to_std_map[i];
            if (std_bar_index > 0 && i + 1 < size)
            {
                float prev_low = std_bars[std_bar_index].low;
                if (close[i + 1] < prev_low)
                {
                    result[i + 1] = -1;
                }
            }
        }
        else if (bi[i] == -1)
        {
            int std_bar_index = raw_to_std_map[i];
            if (std_bar_index > 0 && i + 1 < size)
            {
                float prev_high = std_bars[std_bar_index].high;
                if (close[i + 1] > prev_high)
                {
                    result[i + 1] = 1;
                }
            }
        }
    }
    return result;
}
