#include <chrono>
#include <unordered_map>
#include "../common/log.h"
#include "chan.h"
#include "czsc.h"

static const std::chrono::time_point<std::chrono::system_clock> expiry_time = std::chrono::system_clock::from_time_t(EXPIRY_TIME);

bool is_expired()
{
    std::chrono::time_point<std::chrono::system_clock> current_time = std::chrono::system_clock::now();
    return current_time > expiry_time;
}

// 计算两个K线中间有几个笔顶点，不包含i和j本身
int count_vertexes(std::vector<float> &vertexes, int i, int j)
{
    int count = 0;
    if (i > j)
    {
        std::swap(i, j);
    }
    for (int k = i + 1; k < j; k++)
    {
        if (vertexes[k] == 1 || vertexes[k] == -1)
        {
            count++;
        }
    }
    return count;
}

std::unordered_map<float, int> count_values_float(
    const std::vector<float> &values,
    const std::vector<float> &values_to_count,
    int i, int j,
    bool include)
{
    std::unordered_map<float, int> counts;

    // Initialize counts for all values we want to track
    for (float val : values_to_count)
    {
        counts[val] = 0;
    }

    // Handle index bounds
    if (i > j)
    {
        std::swap(i, j);
    }

    // Adjust indices based on include flag
    int start = include ? i : i + 1;
    int end = include ? j : j - 1;

    // Count occurrences
    for (int k = start; k <= end; k++)
    {
        float val = values[k];
        if (counts.find(val) != counts.end())
        {
            counts[val]++;
        }
    }

    return counts;
}

// 计算所有值的总次数
int sum_counts(const std::unordered_map<float, int> &counts)
{
    int total = 0;
    for (const auto &pair : counts)
    {
        total += pair.second;
    }
    return total;
}

// 寻找i和j两个端点之间的中枢
std::vector<Pivot> locate_pivots(std::vector<float> &sigs, std::vector<float> &high, std::vector<float> &low, int direction, int i, int j)
{
    std::vector<Pivot> pivots;
    int sigs_num = static_cast<int>(sigs.size());
    if (i < 0 || j >= sigs_num || i >= j)
    {
        return pivots;
    }
    if (direction == 1)
    {
        // 向上段
        for (int m = i; m <= j; m++)
        {
            if (sigs.at(m) == 1)
            {
                for (int n = m + 1; n <= j; n++)
                {
                    if (sigs.at(n) == -1)
                    {
                        Pivot pivot;
                        pivot.direction = 1;
                        pivot.start = m;
                        pivot.end = n;
                        pivot.zg = high.at(m);
                        pivot.gg = high.at(m);
                        pivot.zd = low.at(n);
                        pivot.dd = low.at(n);
                        int pivots_num = static_cast<int>(pivots.size());
                        if (pivots_num > 0)
                        {
                            if (pivot.zg >= pivots.at(pivots_num - 1).zd && pivot.zd <= pivots.at(pivots_num - 1).zg)
                            {
                                // 有重叠区间，合并
                                if (!pivots.at(pivots_num - 1).is_comprehensive)
                                {
                                    pivots.at(pivots_num - 1).zd = std::max(pivots.at(pivots_num - 1).zd, pivot.zd);
                                    pivots.at(pivots_num - 1).zg = std::min(pivots.at(pivots_num - 1).zg, pivot.zg);
                                    pivots.at(pivots_num - 1).is_comprehensive = true;
                                }
                                pivots.at(pivots_num - 1).dd = std::min(pivots.at(pivots_num - 1).dd, pivot.dd);
                                pivots.at(pivots_num - 1).gg = std::max(pivots.at(pivots_num - 1).gg, pivot.gg);
                                pivots.at(pivots_num - 1).end = pivot.end;
                            }
                            else
                            {
                                // 没有重合区间
                                pivots.push_back(pivot);
                            }
                        }
                        else
                        {
                            pivots.push_back(pivot);
                        }
                        m = n;
                        break;
                    }
                }
            }
        }
    }
    else if (direction == -1)
    {
        // 向下段
        for (int m = i; m <= j; m++)
        {
            if (sigs.at(m) == -1)
            {
                for (int n = m + 1; n <= j; n++)
                {
                    if (sigs.at(n) == 1)
                    {
                        Pivot pivot;
                        pivot.direction = -1;
                        pivot.start = m;
                        pivot.end = n;
                        pivot.zd = low.at(m);
                        pivot.dd = low.at(m);
                        pivot.zg = high.at(n);
                        pivot.gg = high.at(n);
                        int pivots_num = static_cast<int>(pivots.size());
                        if (pivots_num > 0)
                        {
                            if (pivot.zg >= pivots.at(pivots_num - 1).zd && pivot.zd <= pivots.at(pivots_num - 1).zg)
                            {
                                // 有重叠区间，合并
                                if (!pivots.at(pivots_num - 1).is_comprehensive)
                                {
                                    pivots.at(pivots_num - 1).zd = std::max(pivots.at(pivots_num - 1).zd, pivot.zd);
                                    pivots.at(pivots_num - 1).zg = std::min(pivots.at(pivots_num - 1).zg, pivot.zg);
                                    pivots.at(pivots_num - 1).is_comprehensive = true;
                                }
                                pivots.at(pivots_num - 1).dd = std::min(pivots.at(pivots_num - 1).dd, pivot.dd);
                                pivots.at(pivots_num - 1).gg = std::max(pivots.at(pivots_num - 1).gg, pivot.gg);
                                pivots.at(pivots_num - 1).end = pivot.end;
                            }
                            else
                            {
                                // 没有重合区间
                                pivots.push_back(pivot);
                            }
                        }
                        else
                        {
                            pivots.push_back(pivot);
                        }
                        m = n;
                        break;
                    }
                }
            }
        }
    }
    return pivots;
}

std::vector<Bar> recognise_bars(int length, std::vector<float> &high, std::vector<float> &low)
{
    std::vector<Bar> bars(length);
    if (length == 0)
    {
        return bars;
    }
    for (int i = 0; i < length; ++i)
    {
        bars[i] = Bar{i, 0.0f, high[i], low[i], 0.0f, 0.0f};
    }
    return bars;
}

void update_factor_high_low(std::vector<StdBar> &std_bars)
{
    if (std_bars.empty())
        return;

    StdBar &last_bar = std_bars.back();

    if (std_bars.size() == 1)
    {
        // 第一个std_bar的分型高和分型低都是自己的高和低
        last_bar.factor_high = last_bar.high;
        last_bar.factor_low = last_bar.low;
    }
    else
    {
        const StdBar &prev_bar = std_bars[std_bars.size() - 2];

        if (last_bar.direction == 1)
        {
            // 方向向上的std_bar
            last_bar.factor_low = prev_bar.low;
            last_bar.factor_high = last_bar.high;
        }
        else if (last_bar.direction == -1)
        {
            // 方向向下的std_bar
            last_bar.factor_high = prev_bar.high;
            last_bar.factor_low = last_bar.low;
        }
    }
}

std::vector<StdBar> recognise_std_bars(int length, std::vector<float> &high, std::vector<float> &low, ChanOptions &options)
{
    std::vector<StdBar> std_bars;
    if (length == 0)
    {
        return std_bars;
    }
    std::vector<StdBar> factors;
    // 确定初始方向：查找第一个与K0无包含关系的K线
    for (int x = 1; x < length; x++)
    {
        bool is_up = (high[x] < high[0] && low[x] < low[0]);   // 向上方向
        bool is_down = (high[x] > high[0] && low[x] > low[0]); // 向下方向

        if (is_up || is_down)
        {
            StdBar bar;
            bar.direction = is_down ? -1.0f : 1.0f; // 向下为-1，向上为1
            bar.start = 0;
            bar.end = 0;
            bar.high_vertex_raw_pos = 0;
            bar.low_vertex_raw_pos = 0;
            bar.high = high[0];
            bar.low = low[0];
            bar.high_high = high[0];
            bar.low_low = low[0];
            bar.pos = 0;
            std_bars.push_back(bar);
            update_factor_high_low(std_bars);
            break;
        }
    }
    if (std_bars.empty())
    {
        return std_bars;
    }
    for (int i = 1; i < length; i++)
    {
        // 先记录一下处理之前一共有几个标准化K柱
        size_t current_std_bars_size = std_bars.size();
        StdBar &last_std_bar = std_bars.at(current_std_bars_size - 1);
        // 向上
        bool is_up = high[i] > last_std_bar.high && low[i] > last_std_bar.low;
        // 向下
        bool is_down = high[i] < last_std_bar.high && low[i] < last_std_bar.low;
        // 前包含
        bool is_prior_inclusion = high[i] <= last_std_bar.high && low[i] >= last_std_bar.low;
        if (is_up || is_down)
        {
            // 向上和向下都产生新的标准K线
            StdBar bar;
            bar.direction = is_down ? -1.0f : 1.0f; // 向下为-1，向上为1
            bar.start = i;
            bar.end = i;
            bar.high_vertex_raw_pos = i;
            bar.low_vertex_raw_pos = i;
            bar.high = high[i];
            bar.low = low[i];
            bar.high_high = high[i];
            bar.low_low = low[i];
            bar.pos = static_cast<int>(std_bars.size());
            std_bars.push_back(bar);
            update_factor_high_low(std_bars);
        }
        else if (is_prior_inclusion)
        {
            // 进入这里的时候，K柱和前一个K柱是前包含的关系
            if (last_std_bar.direction == 1)
            {
                // 这里是向上方向的前包含处理
                last_std_bar.high = std::max(last_std_bar.high, high[i]);
                last_std_bar.low = std::max(last_std_bar.low, low[i]);
                last_std_bar.end = i;
            }
            else
            {
                // 这里是向下方向的前包含处理
                last_std_bar.high = std::min(last_std_bar.high, high[i]);
                last_std_bar.low = std::min(last_std_bar.low, low[i]);
                last_std_bar.end = i;
            }
            if (high[i] > last_std_bar.high_high)
            {
                // 这里处理最高K柱的位置是否有变化
                last_std_bar.high_vertex_raw_pos = i;
            }
            if (low[i] < last_std_bar.low_low)
            {
                // 这里处理最低K柱的位置是否有变化
                last_std_bar.low_vertex_raw_pos = i;
            }
            // 更新标准K柱的最高最低价
            last_std_bar.high_high = std::max(last_std_bar.high_high, high[i]);
            last_std_bar.low_low = std::min(last_std_bar.low_low, low[i]);
            update_factor_high_low(std_bars);
        }
        else
        {
            // 后包含的处理逻辑
            int inclusion_num = 0;
            float direction = 0;
            for (int x = static_cast<int>(current_std_bars_size) - 1; x >= 0; x--)
            {
                if (high[i] >= std_bars.at(x).high && low[i] <= std_bars.at(x).low)
                {
                    inclusion_num++;
                    continue;
                }
                if (high[i] > std_bars.at(x).high)
                {
                    direction = 1;
                }
                else
                {
                    direction = -1;
                }
                break;
            }
            if (inclusion_num > 1 && options.inclusion_mode == 1)
            {
                if (last_std_bar.direction == direction) // 方向一致，那就沿着方向出路就可以了
                {
                    if (direction == 1)
                    {
                        // 作向上包含处理
                        last_std_bar.high = std::max(last_std_bar.high, high[i]);
                        last_std_bar.low = std::max(last_std_bar.low, low[i]);
                        last_std_bar.end = i;
                    }
                    else
                    {
                        // 作向下包含处理
                        last_std_bar.high = std::min(last_std_bar.high, high[i]);
                        last_std_bar.low = std::min(last_std_bar.low, low[i]);
                        last_std_bar.end = i;
                    }
                    if (high[i] > last_std_bar.high_high)
                    {
                        // 这里处理最高K柱的位置是否有变化
                        last_std_bar.high_vertex_raw_pos = i;
                    }
                    if (low[i] < last_std_bar.low_low)
                    {
                        // 这里处理最低K柱的位置是否有变化
                        last_std_bar.low_vertex_raw_pos = i;
                    }
                    // 更新标准K柱的最高最低价
                    last_std_bar.high_high = std::max(last_std_bar.high_high, high[i]);
                    last_std_bar.low_low = std::min(last_std_bar.low_low, low[i]);
                }
                else // 方向不一致就当成独立K
                {
                    StdBar bar;
                    bar.direction = -last_std_bar.direction;
                    bar.start = i;
                    bar.end = i;
                    bar.high_vertex_raw_pos = i;
                    bar.low_vertex_raw_pos = i;
                    bar.high = high[i];
                    bar.low = low[i];
                    bar.high_high = high[i];
                    bar.low_low = low[i];
                    bar.pos = static_cast<int>(std_bars.size());
                    std_bars.push_back(bar);
                }
            }
            else if (inclusion_num > 1 && options.inclusion_mode == 2)
            {
                if (direction == 0)
                {
                    StdBar bar;
                    bar.direction = -last_std_bar.direction;
                    bar.start = i;
                    bar.end = i;
                    bar.high_vertex_raw_pos = i;
                    bar.low_vertex_raw_pos = i;
                    bar.high = high[i];
                    bar.low = low[i];
                    bar.high_high = high[i];
                    bar.low_low = low[i];
                    bar.pos = static_cast<int>(std_bars.size());
                    std_bars.push_back(bar);
                }
                else
                {
                    // 删除inclusion_num个标准K柱
                    for (int x = 0; x < inclusion_num; x++)
                    {
                        if (!std_bars.empty())
                        {
                            std_bars.pop_back();
                        }
                    }
                    // 添加新的标准K柱
                    StdBar bar;
                    bar.direction = direction;
                    bar.start = std_bars.back().end + 1;
                    bar.end = i;
                    bar.high_high = high[i];
                    bar.low_low = low[i];
                    bar.high_vertex_raw_pos = i;
                    bar.low_vertex_raw_pos = i;
                    bar.pos = static_cast<int>(std_bars.size());
                    for (int x = bar.start; x <= bar.end; x++)
                    {
                        if (direction == 1)
                        {
                            bar.high = std::max(bar.high, high[x]);
                            bar.low = std::max(bar.low, low[x]);
                        }
                        else
                        {
                            bar.high = std::min(bar.high, high[x]);
                            bar.low = std::min(bar.low, low[x]);
                        }
                    }
                    std_bars.push_back(bar);
                }
            }
            else
            {
                if (last_std_bar.direction == 1)
                {
                    // 这里是向上方向的前包含处理
                    last_std_bar.high = std::max(last_std_bar.high, high[i]);
                    last_std_bar.low = std::max(last_std_bar.low, low[i]);
                    last_std_bar.end = i;
                }
                else
                {
                    // 这里是向下方向的前包含处理
                    last_std_bar.high = std::min(last_std_bar.high, high[i]);
                    last_std_bar.low = std::min(last_std_bar.low, low[i]);
                    last_std_bar.end = i;
                }
                if (high[i] > last_std_bar.high_high)
                {
                    // 这里处理最高K柱的位置是否有变化
                    last_std_bar.high_vertex_raw_pos = i;
                }
                if (low[i] < last_std_bar.low_low)
                {
                    // 这里处理最低K柱的位置是否有变化
                    last_std_bar.low_vertex_raw_pos = i;
                }
                // 更新标准K柱的最高最低价
                last_std_bar.high_high = std::max(last_std_bar.high_high, high[i]);
                last_std_bar.low_low = std::min(last_std_bar.low_low, low[i]);
            }
            update_factor_high_low(std_bars);
        }
    }
    for (size_t i = 1; i < std_bars.size(); i++)
    {
        if (std_bars.at(i).direction != std_bars.at(i - 1).direction)
        {
            std_bars.at(i - 1).factor = std_bars.at(i - 1).direction;
        }
    }
    return std_bars;
}

std::vector<float> recognise_swing(int length, std::vector<float> &high, std::vector<float> &low, ChanOptions &options)
{
    std::vector<float> swing(length, 0.0f);
    if (length == 0)
    {
        return swing;
    }
    if (is_expired())
    {
        return swing;
    }
    // 获取标准化K线
    std::vector<StdBar> std_bars = recognise_std_bars(length, high, low, options);
    if (std_bars.empty())
    {
        return swing;
    }
    // 遍历标准化K线，识别摆动点
    for (size_t i = 0; i < std_bars.size(); i++)
    {
        const StdBar &bar = std_bars.at(i);
        if (bar.factor == -1)
        {
            swing[bar.low_vertex_raw_pos] = -1; // 低点摆动
        }
        else if (bar.factor == 1)
        {
            swing[bar.high_vertex_raw_pos] = 1; // 高点摆动
        }
    }
    // 处理最后一个K线
    const StdBar &last_bar = std_bars.back();
    if (last_bar.factor != -1 && last_bar.factor != 1)
    {
        if (last_bar.direction == 1)
        {
            swing[last_bar.high_vertex_raw_pos] = 1; // 最后一个高点
        }
        else if (last_bar.direction == -1)
        {
            swing[last_bar.low_vertex_raw_pos] = -1; // 最后一个低点
        }
    }

    // Find first 0 in swing array and set it to -2
    for (int i = 0; i < length; i++)
    {
        if (swing[i] == 0)
        {
            swing[i] = -2;
            break;
        }
    }
    return swing;
}

int check_gap(std::vector<Bar> &raw_bars, StdBar &s_bar, StdBar &e_bar, int dir)
{
    int gap_count = 0;
    if (gapCountAsOneBar)
    {
        if (dir == 1)
        {
            for (int i = s_bar.low_vertex_raw_pos; i < e_bar.high_vertex_raw_pos; i++)
            {
                if (raw_bars.at(i + 1).low > raw_bars.at(i).high)
                {
                    Bar &hb = *std::max_element(
                        raw_bars.begin() + s_bar.low_vertex_raw_pos,
                        raw_bars.begin() + i + 1,
                        [](Bar a, Bar b)
                        { return a.high < b.high; });
                    Bar &lb = *std::min_element(
                        raw_bars.begin() + i + 1,
                        raw_bars.begin() + e_bar.high_vertex_raw_pos + 1,
                        [](Bar a, Bar b)
                        { return a.low < b.low; });
                    if (lb.low > hb.high)
                    {
                        gap_count = 1;
                        break;
                    }
                }
            }
        }
        else if (dir == -1)
        {
            for (int i = s_bar.high_vertex_raw_pos; i < e_bar.low_vertex_raw_pos; i++)
            {
                if (raw_bars.at(i + 1).high < raw_bars.at(i).low)
                {
                    Bar &lb = *std::min_element(
                        raw_bars.begin() + s_bar.high_vertex_raw_pos,
                        raw_bars.begin() + i + 1,
                        [](Bar a, Bar b)
                        { return a.low < b.low; });
                    Bar &hb = *std::max_element(
                        raw_bars.begin() + i + 1,
                        raw_bars.begin() + e_bar.low_vertex_raw_pos + 1,
                        [](Bar a, Bar b)
                        { return a.high < b.high; });
                    if (hb.high < lb.low)
                    {
                        gap_count = 1;
                        break;
                    }
                }
            }
        }
    }
    return gap_count;
}

// 判断2个合并K线之间是否成立一笔
bool check_bi(std::vector<Bar> &raw_bars, std::vector<StdBar> &bars, std::vector<StdBar> &factors, size_t s, size_t e, ChanOptions &options)
{
    float bi_min_stick_count = 5;
    bool bi_special_strict_mode = true;
    if (options.bi_mode == 4)
    {
        bi_min_stick_count = 4;
        bi_special_strict_mode = false;
    }
    else if (options.bi_mode == 5)
    {
        bi_min_stick_count = 5;
        bi_special_strict_mode = false;
    }
    else if (options.bi_mode == 6)
    {
        bi_min_stick_count = 5;
        bi_special_strict_mode = true;
    }

    if (e > s)
    {
        StdBar &bar1 = bars.at(s);
        StdBar &bar2 = bars.at(e);
        if (bar2.direction == 1 && bar1.factor == -1)
        {
            // 检查是不是向上笔
            // 起笔不限K线数量
            if (factors.size() == 1)
            {
                return true;
            }
            // 结束K是从起点K以来最高的
            StdBar hb = bars.at(s + 1);
            for (size_t i = s + 2; i < e; i++)
            {
                if (bars.at(i).high_high > hb.high_high)
                {
                    hb = bars.at(i);
                }
            }
            if (bar2.high_high <= hb.high_high)
            {
                return false;
            }
            // 前一笔不够标准的时候
            if (factors.size() >= 4)
            {
                StdBar &f1 = factors.at(factors.size() - 4);
                StdBar &f3 = factors.at(factors.size() - 2);
                StdBar &f4 = factors.at(factors.size() - 1);
                int gapCount = check_gap(raw_bars, f3, f4, -1);
                if (f4.low_vertex_raw_pos - f3.high_vertex_raw_pos + gapCount < bi_min_stick_count - 1 && bar2.pos - bar1.pos < 8 && f1.high_high > f3.high_high && bar2.high_high < f3.high_high)
                {
                    return false;
                }
            }
            bool fractal_satisfied = false;
            if (bi_special_strict_mode)
            {
                if (bar2.factor_low > bar1.factor_high)
                {
                    // 分型没有重叠，并且有1根独立K线不同时和顶底重叠
                    for (size_t j = s + 2; j < e - 1; j++)
                    {
                        if (bars.at(j).high > bar1.factor_high && bars.at(j).low < bar2.factor_low)
                        {
                            fractal_satisfied = true;
                            break;
                        }
                    }
                }
            }
            else
            {
                if (bar2.high > bar1.factor_high)
                {
                    fractal_satisfied = true;
                }
            }
            if (fractal_satisfied)
            {
                // 存在缺口没有回补计数1根K线
                int gapCount = check_gap(raw_bars, bar1, bar2, 1);
                if (bar2.pos - bar1.pos + gapCount >= bi_min_stick_count - 1 && bar2.high_vertex_raw_pos - bar1.low_vertex_raw_pos + gapCount >= 4)
                {
                    return true;
                }
                else if (factors.size() > 1 && bar2.high > factors.at(factors.size() - 2).high && bar2.pos - bar1.pos > 1)
                {
                    return true;
                }
            }
            int count = 0;
            for (size_t j = s + 1; j < e; j++)
            {
                if (bars.at(j).factor == 1)
                {
                    count++;
                }
            }
            if (count >= 2)
            {
                return true;
            }
        }
        else if (bar2.direction == -1 && bar1.factor == 1)
        {
            // 检查是不是向下笔
            // 起笔不限K线数量
            if (factors.size() == 1)
            {
                return true;
            }
            // 结束K是从起点K以来最低的
            StdBar lb = bars.at(s + 1);
            for (size_t i = s + 2; i < e; i++)
            {
                if (bars.at(i).low_low < lb.low_low)
                {
                    lb = bars.at(i);
                }
            }
            if (bar2.low_low >= lb.low_low)
            {
                return false;
            }
            // 前一笔不够标准的时候
            if (factors.size() >= 4)
            {
                StdBar &f1 = factors.at(factors.size() - 4);
                StdBar &f3 = factors.at(factors.size() - 2);
                StdBar &f4 = factors.at(factors.size() - 1);
                int gapCount = check_gap(raw_bars, f3, f4, 1);
                if (f4.high_vertex_raw_pos - f3.low_vertex_raw_pos + gapCount < bi_min_stick_count - 1 && bar2.pos - bar1.pos < 8 && f1.low_low < f3.low_low && bar2.low_low > f3.low_low)
                {
                    return false;
                }
            }
            bool fractal_satisfied = false;
            if (bi_special_strict_mode)
            {
                if (bar2.factor_high < bar1.factor_low)
                {
                    // 分型没有重叠，并且有1根独立K线不同时和顶底重叠
                    for (size_t j = s + 2; j < e - 1; j++)
                    {
                        if (bars.at(j).low < bar1.factor_low && bars.at(j).high > bar2.factor_high)
                        {
                            fractal_satisfied = true;
                            break;
                        }
                    }
                }
            }
            else
            {
                if (bar2.low < bar1.factor_low)
                {
                    fractal_satisfied = true;
                }
            }
            if (fractal_satisfied)
            {
                // 存在缺口没有回补计数1根K线
                int gapCount = check_gap(raw_bars, bar1, bar2, -1);
                if (bar2.pos - bar1.pos + gapCount >= bi_min_stick_count - 1 && bar2.low_vertex_raw_pos - bar1.high_vertex_raw_pos + gapCount >= 4)
                {
                    return true;
                }
                else if (factors.size() > 1 && bar2.low < factors.at(factors.size() - 2).low && bar2.pos - bar1.pos > 1)
                {
                    return true;
                }
            }
            int count = 0;
            for (size_t j = s + 1; j < e; j++)
            {
                if (bars.at(j).factor == -1)
                {
                    count++;
                }
            }
            if (count >= 2)
            {
                return true;
            }
        }
        // 处理特殊缺口, 跳空破高点或者低点
        if (factors.size() > 1)
        {
            if (factors.back().factor == 1 && bar2.factor == -1)
            {
                int count = 0;
                for (int i = bar2.pos; i < bar2.pos + 5 && i < static_cast<int>(bars.size()); i++)
                {
                    if (bars.at(i).high_high < factors.at(factors.size() - 2).low_low)
                    {
                        count++;
                    }
                }
                if (count >= 5)
                {
                    return true;
                }
            }
            if (factors.back().factor == -1 && bar2.factor == 1)
            {
                int count = 0;
                for (int i = bar2.pos; i < bar2.pos + 5 && i < static_cast<int>(bars.size()); i++)
                {
                    if (bars.at(i).low_low > factors.at(factors.size() - 2).high_high)
                    {
                        count++;
                    }
                }
                if (count >= 5)
                {
                    return true;
                }
            }
        }
    }
    return false;
}

std::vector<float> recognise_bi(int length, std::vector<float> &high, std::vector<float> &low, ChanOptions &options)
{
    std::vector<float> bi(length, 0.0f);
    if (length == 0)
    {
        return bi;
    }
    if (is_expired())
    {
        return bi;
    }
    float bi_min_stick_count = 5;
    if (options.bi_mode == 4)
    {
        bi_min_stick_count = 4;
    }
    else if (options.bi_mode == 5)
    {
        bi_min_stick_count = 5;
    }
    else if (options.bi_mode == 6)
    {
        bi_min_stick_count = 5;
    }
    std::vector<Bar> raw_bars = recognise_bars(length, high, low);
    std::vector<StdBar> std_bars = recognise_std_bars(length, high, low, options);
    std::vector<StdBar> factors; // 笔的端点
    for (int i = 0; i < static_cast<int>(std_bars.size()); i++)
    {
        if (factors.size() == 0)
        {
            if (std_bars.at(i).factor == -1 || std_bars.at(i).factor == 1)
            {
                if (std_bars.at(i).factor == -1)
                {
                    bi[std_bars.at(i).low_vertex_raw_pos] = -0.5;
                }
                else if (std_bars.at(i).factor == 1)
                {
                    bi[std_bars.at(i).high_vertex_raw_pos] = 0.5;
                }
                factors.push_back(std_bars.at(i));
            }
            continue;
        }

        if (std_bars.at(i).direction == 1)
        {
            if (factors.back().factor == -1)
            {
                if (check_bi(raw_bars, std_bars, factors, factors.back().pos, i, options))
                {
                    if (options.merge_non_complehensive_wave == 1)
                    {
                        // 合并小转大笔
                        if (factors.size() > 3)
                        {
                            StdBar &f1 = factors.at(factors.size() - 4);
                            StdBar &f2 = factors.at(factors.size() - 3);
                            StdBar &f3 = factors.at(factors.size() - 2);
                            StdBar &f4 = factors.at(factors.size() - 1);
                            int gapCount = check_gap(raw_bars, f3, f4, -1);
                            if (f4.low_vertex_raw_pos - f3.high_vertex_raw_pos + gapCount < bi_min_stick_count - 1 && f1.high > f3.high && f2.low > f4.low)
                            {
                                bi[f2.high_vertex_raw_pos] = -0.5;
                                bi[f4.high_vertex_raw_pos] = -0.5;
                                factors.pop_back();
                                factors.pop_back();
                                factors.pop_back();
                                factors.push_back(f4);
                            }
                        }
                    }
                    bi[std_bars.at(i).high_vertex_raw_pos] = 0.5;
                    factors.push_back(std_bars.at(i));
                    continue;
                }
                else if (factors.size() > 1)
                {
                    // 成立非完备笔
                    if (std_bars.at(i).high_high > factors.at(factors.size() - 2).high_high)
                    {
                        factors.push_back(std_bars.at(i));
                        continue;
                    }
                }
            }
            else if (factors.back().direction == 1)
            {
                // 笔继续延申
                if (std_bars.at(i).high_high > factors.back().high_high)
                {
                    bi[factors.back().high_vertex_raw_pos] = 0.5;
                    factors.pop_back();
                    factors.push_back(std_bars.at(i));
                    continue;
                }
            }
        }
        else if (std_bars.at(i).direction == -1)
        {
            if (factors.back().factor == 1)
            {
                if (check_bi(raw_bars, std_bars, factors, factors.back().pos, i, options))
                {
                    if (options.merge_non_complehensive_wave == 1)
                    {
                        // 合并小转大笔
                        if (factors.size() > 3)
                        {
                            StdBar &f1 = factors.at(factors.size() - 4);
                            StdBar &f2 = factors.at(factors.size() - 3);
                            StdBar &f3 = factors.at(factors.size() - 2);
                            StdBar &f4 = factors.at(factors.size() - 1);
                            int gapCount = check_gap(raw_bars, f3, f4, 1);
                            if (f4.high_vertex_raw_pos - f3.low_vertex_raw_pos + gapCount < bi_min_stick_count - 1 && f1.low < f3.low && f2.high < f4.high)
                            {
                                bi[f2.low_vertex_raw_pos] = 0.5;
                                bi[f4.low_vertex_raw_pos] = 0.5;
                                factors.pop_back();
                                factors.pop_back();
                                factors.pop_back();
                                factors.push_back(f4);
                            }
                        }
                    }
                    bi[std_bars.at(i).low_vertex_raw_pos] = -0.5;
                    factors.push_back(std_bars.at(i));
                    continue;
                }
                else if (factors.size() > 1)
                {
                    // 成立非完备笔
                    if (std_bars.at(i).low_low < factors.at(factors.size() - 2).low_low)
                    {
                        factors.push_back(std_bars.at(i));
                        continue;
                    }
                }
            }
            else if (factors.back().direction == -1)
            {
                // 笔继续延申
                if (std_bars.at(i).low_low < factors.back().low_low)
                {
                    bi[factors.back().low_vertex_raw_pos] = -0.5;
                    factors.pop_back();
                    factors.push_back(std_bars.at(i));
                    continue;
                }
            }
        }
        // 达到15根K线了必须强制成笔
        if (options.force_wave_stick_count >= 15)
        {
            if (i - factors.back().pos >= options.force_wave_stick_count)
            {
                if (factors.back().factor == -1)
                {
                    float hh = factors.back().high;
                    int hh_pos = factors.back().pos;
                    for (int j = factors.back().pos + 1; j < i; j++)
                    {
                        if (std_bars.at(j).factor == 1 && std_bars.at(j).high_high > hh)
                        {
                            hh = std_bars.at(j).high_high;
                            hh_pos = j;
                        }
                    }
                    if (hh_pos - factors.back().pos > 0)
                    {
                        factors.push_back(std_bars.at(hh_pos));
                        i = hh_pos;
                        continue;
                    }
                }
                else if (factors.back().factor == 1)
                {
                    float ll = factors.back().low;
                    int ll_pos = factors.back().pos;
                    for (int j = factors.back().pos + 1; j < i; j++)
                    {
                        if (std_bars.at(j).factor == -1 && std_bars.at(j).low_low < ll)
                        {
                            ll = std_bars.at(j).low_low;
                            ll_pos = j;
                        }
                    }
                    if (ll_pos - factors.back().pos > 0)
                    {
                        factors.push_back(std_bars.at(ll_pos));
                        i = ll_pos;
                        continue;
                    }
                }
            }
        }
    }
    for (size_t i = 0; i < factors.size(); i++)
    {
        if (factors.at(i).direction == 1)
        {
            bi[factors.at(i).high_vertex_raw_pos] = 1;
        }
        else if (factors.at(i).direction == -1)
        {
            bi[factors.at(i).low_vertex_raw_pos] = -1;
        }
    }
    // Find first 0 in bi array and set it to -3
    for (int i = 0; i < length; i++)
    {
        if (bi[i] == 0)
        {
            bi[i] = -3;
            break;
        }
    }
    return bi;
}

// 判断两个点之间是不是成立线段
bool check_duan(std::vector<Segment> &segments, std::vector<Vertex> &vertexes, std::vector<float> &bi, std::vector<Vertex> &pendings, int start, int end, std::vector<float> &high, std::vector<float> &low, int direction)
{
    if (segments.size() > 0 && segments.back().vertexPosEnd - segments.back().vertexPosStart >= 3)
    {
        if (direction == -1 && segments.back().direction == 1)
        {
            float h = high[vertexes.at(segments.back().vertexPosStart + 1).pos];
            for (int i = segments.back().vertexPosStart + 1; i < segments.back().vertexPosEnd; i++)
            {
                if (high[vertexes.at(i).pos] > h)
                {
                    h = high[vertexes.at(i).pos];
                }
            }
            // 存在缺口
            if (low[pendings.at(end).pos] > h)
            {
                if (pendings.size() >= 6 && low[pendings.at(end).pos] < low[pendings.at(start + 1).pos] && low[pendings.at(end).pos] < low[pendings.at(start + 3).pos])
                {
                    return true;
                }
                else
                {
                    return false;
                }
            }
        }
        else if (direction == 1 && segments.back().direction == -1)
        {
            float l = low[vertexes.at(segments.back().vertexPosStart + 1).pos];
            for (int i = segments.back().vertexPosStart + 1; i < segments.back().vertexPosEnd; i++)
            {
                if (low[vertexes.at(i).pos] < l)
                {
                    l = low[vertexes.at(i).pos];
                }
            }
            // 存在缺口
            if (high[pendings.at(end).pos] < l)
            {
                if (pendings.size() >= 6 && high[pendings.at(end).pos] > high[pendings.at(start + 1).pos] && high[pendings.at(end).pos] > high[pendings.at(start + 3).pos])
                {
                    return true;
                }
                else
                {
                    return false;
                }
            }
        }
    }
    if (end - start >= 3 && pendings.at(start).type == -direction && pendings.at(end).type == direction)
    {
        if (direction == 1)
        {
            auto pivots = locate_pivots(bi, high, low, direction, segments.back().start, segments.back().end);
            if (pivots.size() > 0)
            {
                if (low[pendings.at(end - 1).pos] > pivots.back().zg)
                {
                    return true;
                }
            }
            if (allow_second_high_low_swell)
            {
                for (int i = start + 1; i < end; i = i + 2)
                {
                    if (high[pendings.at(end).pos] > high[pendings.at(i).pos])
                    {
                        return true;
                    }
                }
            }
            else
            {
                if (high[pendings.at(end).pos] > high[pendings.at(start + 1).pos])
                {
                    return true;
                }
            }
        }
        else if (direction == -1)
        {
            auto pivots = locate_pivots(bi, high, low, direction, segments.back().start, segments.back().end);
            if (pivots.size() > 0)
            {
                if (high[pendings.at(end - 1).pos] < pivots.back().zd)
                {
                    return true;
                }
            }
            if (allow_second_high_low_swell)
            {
                for (int i = start + 1; i < end; i = i + 2)
                {
                    if (low[pendings.at(end).pos] < low[pendings.at(i).pos])
                    {
                        return true;
                    }
                }
            }
            else
            {
                if (low[pendings.at(end).pos] < low[pendings.at(start + 1).pos])
                {
                    return true;
                }
            }
        }
    }

    return false;
}

std::vector<float> recognise_duan(int length, std::vector<float> &bi, std::vector<float> &high, std::vector<float> &low)
{
    std::vector<float> duan(length, 0);
    if (length == 0)
    {
        return duan;
    }
    if (is_expired())
    {
        return duan;
    }
    std::vector<Vertex> vertexes;
    for (int i = 0; i < length; i++)
    {
        if (bi[i] == 1)
        {
            Vertex vertex;
            vertex.pos = i;
            vertex.type = 1;
            vertex.logicPos = static_cast<int>(vertexes.size());
            vertexes.push_back(vertex);
        }
        else if (bi[i] == -1)
        {
            Vertex vertex = Vertex();
            vertex.pos = i;
            vertex.type = -1;
            vertex.logicPos = static_cast<int>(vertexes.size());
            vertexes.push_back(vertex);
        }
    }
    std::vector<Segment> segments;
    std::vector<Vertex> pending;
    int vertexes_num = static_cast<int>(vertexes.size());
    // 第一次循环是找第一个段的成立
    for (int i = 0; i < vertexes_num; i++)
    {
        if (vertexes.at(i).type == 1)
        {
            int k = -1;
            for (int j = i - 1; j >= 0; j--)
            {
                if (vertexes.at(j).type == -1)
                {
                    if (k == -1 || low[vertexes.at(j).pos] < low[vertexes.at(k).pos])
                    {
                        k = j;
                    }
                }
                else if (vertexes.at(j).type == 1)
                {
                    if (high[vertexes.at(j).pos] > high[vertexes.at(i).pos])
                    {
                        break;
                    }
                }
            }
            if (k >= 0 && i - k >= 2)
            {
                Segment d = Segment();
                d.start = vertexes.at(k).pos;
                d.end = vertexes.at(i).pos;
                d.vertexPosStart = k;
                d.vertexPosEnd = i;
                d.comprehensive_pos = d.end;
                d.direction = 1;
                segments.push_back(d);
                pending.push_back(vertexes.at(i));
                break;
            }
        }
        else if (vertexes.at(i).type == -1)
        {
            int k = -1;
            for (int j = i - 1; j >= 0; j--)
            {
                if (vertexes.at(j).type == 1)
                {
                    if (k == -1 || high[vertexes.at(j).pos] > high[vertexes.at(k).pos])
                    {
                        k = j;
                    }
                }
                else if (vertexes.at(j).type == -1)
                {
                    if (low[vertexes.at(j).pos] < low[vertexes.at(i).pos])
                    {
                        break;
                    }
                }
            }
            if (k >= 0 && i - k >= 2)
            {
                Segment d = Segment();
                d.start = vertexes.at(k).pos;
                d.end = vertexes.at(i).pos;
                d.vertexPosStart = k;
                d.vertexPosEnd = i;
                d.comprehensive_pos = d.end;
                d.direction = -1;
                segments.push_back(d);
                pending.push_back(vertexes.at(i));
                break;
            }
        }
    }
    if (segments.size() == 0)
    {
        return duan;
    }
    for (int i = segments.back().vertexPosEnd; i < vertexes_num; i++)
    {
        // 这里统一处理段是不是需要合并
        if (segments.size() > 2)
        {
            if (!segments.back().confirmed)
            {
                if (segments.back().vertexPosEnd - segments.back().vertexPosStart >= 3)
                {
                    segments.back().confirmed = true;
                }
                else
                {
                    if (segments.back().direction == 1)
                    {
                        bool merge = true;
                        if (!(high[segments.at(segments.size() - 1).end] > high[segments.at(segments.size() - 3).end] &&
                              low[segments.at(segments.size() - 1).start] > low[segments.at(segments.size() - 3).start]))
                        {
                            merge = false;
                        }
                        else
                        {
                            if (segments.at(segments.size() - 2).vertexPosEnd - segments.at(segments.size() - 2).vertexPosStart >= 5)
                            {
                                int pos1 = segments.at(segments.size() - 2).vertexPosStart + 1;
                                // int pos2 = segments.at(segments.size() - 2).vertexPosStart + 2;
                                int pos3 = segments.at(segments.size() - 2).vertexPosStart + 3;
                                int pos4 = segments.at(segments.size() - 2).vertexPosStart + 4;
                                float p1 = low[vertexes.at(pos1).pos];
                                // float p2 = high[vertexes.at(pos2).pos];
                                float p3 = low[vertexes.at(pos3).pos];
                                float p4 = high[vertexes.at(pos4).pos];
                                if (p4 < p1)
                                {
                                    merge = false;
                                }
                                else
                                {
                                    float p = std::max(p1, p3);
                                    for (int j = segments.at(segments.size() - 2).vertexPosEnd - 1; j >= pos4 + 2; j = j - 2)
                                    {
                                        if (high[vertexes.at(j).pos] < p)
                                        {
                                            merge = false;
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                        if (merge)
                        {
                            segments.at(segments.size() - 3).end = segments.back().end;
                            segments.at(segments.size() - 3).vertexPosEnd = segments.back().vertexPosEnd;
                            segments.pop_back();
                            segments.pop_back();
                        }
                        else
                        {
                            segments.back().confirmed = true;
                        }
                    }
                    else if (segments.back().direction == -1)
                    {
                        bool merge = true;
                        if (!(low[segments.at(segments.size() - 1).end] < low[segments.at(segments.size() - 3).end] &&
                              high[segments.at(segments.size() - 1).start] < high[segments.at(segments.size() - 3).start]))
                        {
                            merge = false;
                        }
                        else
                        {
                            if (segments.at(segments.size() - 2).vertexPosEnd - segments.at(segments.size() - 2).vertexPosStart >= 5)
                            {
                                int pos1 = segments.at(segments.size() - 2).vertexPosStart + 1;
                                // int pos2 = segments.at(segments.size() - 2).vertexPosStart + 2;
                                int pos3 = segments.at(segments.size() - 2).vertexPosStart + 3;
                                int pos4 = segments.at(segments.size() - 2).vertexPosStart + 4;
                                float p1 = high[vertexes.at(pos1).pos];
                                // float p2 = low[vertexes.at(pos2).pos];
                                float p3 = high[vertexes.at(pos3).pos];
                                float p4 = low[vertexes.at(pos4).pos];
                                if (p4 > p1)
                                {
                                    merge = false;
                                }
                                else
                                {
                                    float p = std::min(p1, p3);
                                    for (int j = segments.at(segments.size() - 2).vertexPosEnd - 1; j >= pos4 + 2; j = j - 2)
                                    {
                                        if (low[vertexes.at(j).pos] > p)
                                        {
                                            merge = false;
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                        if (merge)
                        {
                            segments.at(segments.size() - 3).end = segments.back().end;
                            segments.at(segments.size() - 3).vertexPosEnd = segments.back().vertexPosEnd;
                            segments.pop_back();
                            segments.pop_back();
                        }
                        else
                        {
                            segments.back().confirmed = true;
                        }
                    }
                }
            }
        }
        Vertex &v = vertexes.at(i);
        if (v.type == 1)
        {
            if (segments.back().direction == 1)
            {
                // 前一段是向上段
                if (high[v.pos] > high[segments.back().end])
                {
                    if (pending.size() > 1)
                    {
                        // 这里实际上发生了一笔成段的处理方法
                        // 以后要考虑要不要这种处理方法
                        size_t pos = 1;
                        for (size_t j = 1; j < pending.size(); j = j + 2)
                        {
                            if (low[pending.at(j).pos] < low[pending.at(pos).pos])
                            {
                                pos = j;
                            }
                        }
                        if (low[pending.at(pos).pos] < low[segments.back().start])
                        {
                            Segment d = Segment();
                            d.start = pending.at(0).pos;
                            d.end = pending.at(pos).pos;
                            d.vertexPosStart = pending.at(0).logicPos;
                            d.vertexPosEnd = pending.at(pos).logicPos;
                            d.comprehensive_pos = d.end;
                            d.direction = -1;
                            segments.push_back(d);
                            i = pending.at(pos).logicPos;
                            Vertex &s = pending.at(pos);
                            pending.clear();
                            pending.push_back(s);
                            continue;
                        }
                    }
                    segments.back().end = v.pos;
                    segments.back().vertexPosEnd = v.logicPos;
                    pending.clear();
                    pending.push_back(v);
                    continue;
                }
                // 程序运行到这里的时候，是前一段是向上段，当前的高点没有创新高。
                pending.push_back(v);
                if (!allow_second_high_low_swell)
                {
                    // 这里也会发生一笔成段的划分
                    // 要考虑以后是不是要修改
                    if (pending.size() >= 7 && high[pending.at(2).pos] < low[pending.at(5).pos])
                    {
                        // 强制向下段
                        size_t pos = 1;
                        for (size_t j = 1; j < pending.size(); j = j + 2)
                        {
                            if (low[pending.at(j).pos] <= low[pending.at(pos).pos])
                            {
                                pos = j;
                            }
                        }
                        Segment d = Segment();
                        d.start = pending.at(0).pos;
                        d.end = pending.at(pos).pos;
                        d.vertexPosStart = pending.at(0).logicPos;
                        d.vertexPosEnd = pending.at(pos).logicPos;
                        d.comprehensive_pos = d.end;
                        d.direction = -1;
                        segments.push_back(d);
                        i = pending.at(pos).logicPos;
                        Vertex &s = pending.at(pos);
                        pending.clear();
                        pending.push_back(s);
                    }
                }
            }
            else
            {
                // 前一段是向下段
                pending.push_back(v);
                if (pending.size() >= 4 && check_duan(segments, vertexes, bi,pending, 0, static_cast<int>(pending.size()) - 1, high, low, 1))
                {
                    Segment d = Segment();
                    d.start = pending.at(0).pos;
                    d.end = pending.back().pos;
                    d.vertexPosStart = pending.at(0).logicPos;
                    d.vertexPosEnd = pending.back().logicPos;
                    d.comprehensive_pos = d.end;
                    d.direction = 1;
                    segments.push_back(d);
                    pending.clear();
                    pending.push_back(v);
                }
                else
                {
                    // 9笔了必须强势升段
                    if (forceSwellWhen9Wave)
                    {
                        if (pending.size() >= 9)
                        {
                            // 强制向上段
                            size_t pos = 1;
                            for (size_t j = 1; j < pending.size(); j = j + 2)
                            {
                                if (high[pending.at(j).pos] >= high[pending.at(pos).pos])
                                {
                                    pos = j;
                                }
                            }
                            Segment d = Segment();
                            d.start = pending.at(0).pos;
                            d.end = pending.at(pos).pos;
                            d.vertexPosStart = pending.at(0).logicPos;
                            d.vertexPosEnd = pending.at(pos).logicPos;
                            d.comprehensive_pos = d.end;
                            d.direction = 1;
                            segments.push_back(d);
                            i = pending.at(pos).logicPos;
                            Vertex &s = pending.at(pos);
                            pending.clear();
                            pending.push_back(s);
                        }
                    }
                }
            }
        }
        else if (v.type == -1)
        {
            if (segments.back().direction == -1)
            {
                // 前一段是向下段
                if (low[v.pos] < low[segments.back().end])
                {
                    if (pending.size() > 1)
                    {
                        size_t pos = 1;
                        for (size_t j = 1; j < pending.size(); j = j + 2)
                        {
                            if (high[pending.at(j).pos] > high[pending.at(pos).pos])
                            {
                                pos = j;
                            }
                        }
                        if (high[pending.at(pos).pos] > high[segments.back().start])
                        {
                            Segment d = Segment();
                            d.start = pending.at(0).pos;
                            d.end = pending.at(pos).pos;
                            d.vertexPosStart = pending.at(0).logicPos;
                            d.vertexPosEnd = pending.at(pos).logicPos;
                            d.comprehensive_pos = d.end;
                            d.direction = 1;
                            segments.push_back(d);
                            i = pending.at(pos).logicPos;
                            Vertex &s = pending.at(pos);
                            pending.clear();
                            pending.push_back(s);
                            continue;
                        }
                    }
                    segments.back().end = v.pos;
                    segments.back().vertexPosEnd = v.logicPos;
                    pending.clear();
                    pending.push_back(v);
                    continue;
                }
                pending.push_back(v);
                if (!allow_second_high_low_swell)
                {
                    if (pending.size() >= 7 && low[pending.at(2).pos] > high[pending.at(5).pos])
                    {
                        // 强制向上段
                        size_t pos = 1;
                        for (size_t j = 1; j < pending.size(); j = j + 2)
                        {
                            if (high[pending.at(j).pos] >= high[pending.at(pos).pos])
                            {
                                pos = j;
                            }
                        }
                        Segment d = Segment();
                        d.start = pending.at(0).pos;
                        d.end = pending.at(pos).pos;
                        d.vertexPosStart = pending.at(0).logicPos;
                        d.vertexPosEnd = pending.at(pos).logicPos;
                        d.comprehensive_pos = d.end;
                        d.direction = 1;
                        segments.push_back(d);
                        i = pending.at(pos).logicPos;
                        Vertex &s = pending.at(pos);
                        pending.clear();
                        pending.push_back(s);
                    }
                }
            }
            else
            {
                // 前一段是向上段
                pending.push_back(v);
                if (pending.size() >= 4 && check_duan(segments, vertexes, bi, pending, 0, static_cast<int>(pending.size()) - 1, high, low, -1))
                {
                    Segment d = Segment();
                    d.start = pending.at(0).pos;
                    d.end = pending.back().pos;
                    d.vertexPosStart = pending.at(0).logicPos;
                    d.vertexPosEnd = pending.back().logicPos;
                    d.comprehensive_pos = d.end;
                    d.direction = -1;
                    segments.push_back(d);
                    pending.clear();
                    pending.push_back(v);
                }
                else
                {
                    // 9笔了必须强势升段
                    if (forceSwellWhen9Wave)
                    {
                        if (pending.size() >= 9)
                        {
                            // 强制向下段
                            size_t pos = 1;
                            for (size_t j = 1; j < pending.size(); j = j + 2)
                            {
                                if (low[pending.at(j).pos] <= low[pending.at(pos).pos])
                                {
                                    pos = j;
                                }
                            }
                            Segment d = Segment();
                            d.start = pending.at(0).pos;
                            d.end = pending.at(pos).pos;
                            d.vertexPosStart = pending.at(0).logicPos;
                            d.vertexPosEnd = pending.at(pos).logicPos;
                            d.comprehensive_pos = d.end;
                            d.direction = -1;
                            segments.push_back(d);
                            i = pending.at(pos).logicPos;
                            Vertex &s = pending.at(pos);
                            pending.clear();
                            pending.push_back(s);
                        }
                    }
                }
            }
        }
    }

    int size = static_cast<int>(segments.size());
    for (int i = 0; i < size; i++)
    {
        Segment &d = segments.at(i);
        if (d.direction == 1)
        {
            duan[d.comprehensive_pos] = 0.5;
            float hi = high[d.comprehensive_pos];
            for (int x = d.comprehensive_pos + 1; x < d.end; x++)
            {
                if (bi[x] == 1.0 && high[x] >= hi)
                {
                    duan[x] = 0.5;
                    hi = high[x];
                }
            }
            if (i == 0)
            {
                duan[d.start] = -1;
                duan[d.end] = 1;
            }
            else
            {
                duan[d.end] = 1;
            }
        }
        else if (d.direction == -1)
        {
            duan[d.comprehensive_pos] = -0.5;
            float lo = low[d.comprehensive_pos];
            for (int x = d.comprehensive_pos + 1; x < d.end; x++)
            {
                if (bi[x] == -1.0 && low[x] <= lo)
                {
                    duan[x] = -0.5;
                    lo = low[x];
                }
            }
            if (i == 0)
            {
                duan[d.start] = 1;
                duan[d.end] = -1;
            }
            else
            {
                duan[d.end] = -1;
            }
        }
    }
    // Find first 0 in duan array and set it to -4
    for (int i = 0; i < length; i++)
    {
        if (duan[i] == 0)
        {
            duan[i] = -4;
            break;
        }
    }
    return duan;
}

std::vector<Pivot> recognise_pivots(
    int length, std::vector<float> &higher_level_sigs, std::vector<float> &sigs,
    std::vector<float> &high, std::vector<float> &low, ChanOptions &options)
{
    std::vector<Pivot> pivots;
    if (length == 0)
    {
        return pivots;
    }
    if (is_expired())
    {
        return pivots;
    }
    for (int i = 0; i < length; i++)
    {
        if (higher_level_sigs[i] == 1 || higher_level_sigs[i] == -1)
        {
            int direction = -static_cast<int>(higher_level_sigs[i]);
            int higher_level_next_sig = -static_cast<int>(higher_level_sigs[i]);
            for (int j = i + 1; j < length; j++)
            {
                if (higher_level_sigs[j] == higher_level_next_sig)
                {
                    auto inner_pivots = locate_pivots(sigs, high, low, direction, i, j);
                    // 把inner_pivots中is_comprehensive的加入到pivots中
                    for (const auto &pivot : inner_pivots)
                    {
                        if (pivot.is_comprehensive)
                        {
                            pivots.push_back(pivot);
                        }
                    }
                    i = j - 1;
                    break;
                }
            }
        }
    }

    if (options.allow_pivot_across == 1)
    {
        // 先找出来最后一个线段，我们要对最后一个线段开始重新画中枢
        int v[2] = {-1, -1};
        int x = 1;
        int direction = 0;
        for (int i = length - 1; i > -1; i--)
        {
            if (higher_level_sigs[i] == 1 || higher_level_sigs[i] == -1)
            {
                v[x] = i;
                x--;
                if (x <= -1)
                {
                    break;
                }
            }
        }
        if (v[0] > -1)
        {
            std::vector<Pivot> last_pivots;
            direction = static_cast<int>(higher_level_sigs[v[1]]);
            if (direction == 1)
            {
                last_pivots = locate_pivots(sigs, high, low, direction, v[0], v[1]);
                int pivots_num = static_cast<int>(last_pivots.size());
                if (pivots_num > 0)
                {
                    // 看往后能不能找到中枢破坏
                    Pivot &pivot = last_pivots.at(pivots_num - 1);
                    bool has_pivot_break = false;
                    for (int i = v[1] + 1; i < length; i++)
                    {
                        if (sigs[i] == -1 && low[i] > pivot.zg)
                        {
                            // 有顺着方向的中枢破坏
                            has_pivot_break = true;
                            last_pivots = locate_pivots(sigs, high, low, direction, v[0], length - 1);
                            while (pivots.size() > 0)
                            {
                                if (pivots.back().start > v[0])
                                {
                                    pivots.pop_back();
                                }
                                else
                                {
                                    break;
                                }
                            }
                            for (const auto &last_pivot : last_pivots)
                            {
                                if (last_pivot.is_comprehensive)
                                {
                                    pivots.push_back(last_pivot);
                                }
                            }
                            break;
                        }
                        else if (sigs[i] == 1 && high[i] < pivot.zd)
                        {
                            for (int j = i + 1; j < length; j++)
                            {
                                if (sigs[j] == -1)
                                {
                                    has_pivot_break = true;
                                    break;
                                }
                            }
                            // 有反向的中枢破坏
                            if (has_pivot_break)
                            {
                                last_pivots = locate_pivots(sigs, high, low, -direction, v[1], length - 1);
                                for (const auto &last_pivot : last_pivots)
                                {
                                    if (last_pivot.is_comprehensive)
                                    {
                                        pivots.push_back(last_pivot);
                                    }
                                }
                            }
                            break;
                        }
                    }
                    if (!has_pivot_break)
                    {
                        last_pivots = locate_pivots(sigs, high, low, direction, v[0], length - 1);
                        while (pivots.size() > 0)
                        {
                            if (pivots.back().start > v[0])
                            {
                                pivots.pop_back();
                            }
                            else
                            {
                                break;
                            }
                        }
                        for (const auto &last_pivot : last_pivots)
                        {
                            if (last_pivot.is_comprehensive)
                            {
                                pivots.push_back(last_pivot);
                            }
                        }
                    }
                }
            }
            else if (direction == -1)
            {
                last_pivots = locate_pivots(sigs, high, low, direction, v[0], v[1]);
                int pivots_num = static_cast<int>(last_pivots.size());
                if (pivots_num > 0)
                {
                    // 看往后能不能找到中枢破坏
                    Pivot &pivot = last_pivots.at(pivots_num - 1);
                    bool has_pivot_break = false;
                    for (int i = v[1] + 1; i < length; i++)
                    {
                        if (sigs[i] == 1 && high[i] < pivot.zd)
                        {
                            // 有顺着方向的中枢破坏
                            has_pivot_break = true;
                            last_pivots = locate_pivots(sigs, high, low, direction, v[0], length - 1);
                            while (pivots.size() > 0)
                            {
                                if (pivots.back().start > v[0])
                                {
                                    pivots.pop_back();
                                }
                                else
                                {
                                    break;
                                }
                            }
                            for (const auto &last_pivot : last_pivots)
                            {
                                if (last_pivot.is_comprehensive)
                                {
                                    pivots.push_back(last_pivot);
                                }
                            }
                            break;
                        }
                        else if (sigs[i] == -1 && low[i] > pivot.zg)
                        {
                            for (int j = i + 1; j < length; j++)
                            {
                                if (sigs[j] == 1)
                                {
                                    has_pivot_break = true;
                                    break;
                                }
                            }
                            // 有反向的中枢破坏
                            if (has_pivot_break)
                            {
                                last_pivots = locate_pivots(sigs, high, low, -direction, v[1], length - 1);
                                for (const auto &last_pivot : last_pivots)
                                {
                                    if (last_pivot.is_comprehensive)
                                    {
                                        pivots.push_back(last_pivot);
                                    }
                                }
                            }
                            break;
                        }
                    }
                    if (!has_pivot_break)
                    {
                        last_pivots = locate_pivots(sigs, high, low, direction, v[0], length - 1);
                        while (pivots.size() > 0)
                        {
                            if (pivots.back().start > v[0])
                            {
                                pivots.pop_back();
                            }
                            else
                            {
                                break;
                            }
                        }
                        for (const auto &last_pivot : last_pivots)
                        {
                            if (last_pivot.is_comprehensive)
                            {
                                pivots.push_back(last_pivot);
                            }
                        }
                    }
                }
            }
        }
    }
    return pivots;
}

// 识别缠中说缠走势类型
std::vector<float> recognise_trend(int length, std::vector<float> &duan, std::vector<float> &high, std::vector<float> &low)
{
    // 时间限制，过期无效
    std::vector<float> trend(length, 0);
    if (length == 0)
    {
        return trend;
    }
    if (is_expired())
    {
        return trend;
    }
    std::vector<TrendSegment> trend_segments;
    // 一开始我们先找出第一段走势在哪里
    // 这里要找的第一段走势要一个5段的走势
    for (int i = 0; i < length; i++)
    {
        if (duan[i] == 1)
        {
            int bot_vertex_pos = -1;
            for (int j = i - 1; j > -1; j--)
            {
                if (duan[j] == -1)
                {
                    if (bot_vertex_pos == -1 || low[j] < low[bot_vertex_pos])
                    {
                        bot_vertex_pos = j;
                    }
                }
                else if (duan[j] == 1 && high[j] > high[i])
                {
                    break;
                }
            }
            // 判断bot_vertex_pos和i之前是否成走势
            if (bot_vertex_pos > -1)
            {
                auto pivots = locate_pivots(duan, high, low, 1, bot_vertex_pos, i);
                if (pivots.size() > 1 || (pivots.size() == 1 && pivots.back().is_comprehensive))
                {
                    TrendSegment trend;
                    trend.start = bot_vertex_pos;
                    trend.end = i;
                    trend.direction = 1;
                    trend.pivots = pivots;
                    trend_segments.push_back(trend);
                    break;
                }
            }
        }
        else if (duan[i] == -1)
        {
            int top_vertex_pos = -1;
            for (int j = i - 1; j > -1; j--)
            {
                if (duan[j] == 1)
                {
                    if (top_vertex_pos == -1 || high[j] > high[top_vertex_pos])
                    {
                        top_vertex_pos = j;
                    }
                }
                else if (duan[j] == -1 && low[j] < low[i])
                {
                    break;
                }
            }
            // 判断top_vertex_pos和i之前是否成走势
            if (top_vertex_pos > -1)
            {
                auto pivots = locate_pivots(duan, high, low, -1, top_vertex_pos, i);
                if (pivots.size() > 1 || (pivots.size() == 1 && pivots.back().is_comprehensive))
                {
                    TrendSegment trend;
                    trend.start = top_vertex_pos;
                    trend.end = i;
                    trend.direction = -1;
                    trend.pivots = pivots;
                    trend_segments.push_back(trend);
                    break;
                }
            }
        }
    }

    if (trend_segments.size() == 0)
    {
        return trend;
    }
    // 然后再反推在第一段之前是否还可以成一个3段的走势
    if (trend_segments.back().direction == 1)
    {
        int top_vertex_pos = -1;
        for (int i = trend_segments.back().start - 1; i > -1; i--)
        {
            if (duan[i] == 1)
            {
                if (top_vertex_pos == -1 || high[i] > high[top_vertex_pos])
                {
                    top_vertex_pos = i;
                }
            }
        }
        if (top_vertex_pos > -1)
        {
            auto pivots = locate_pivots(duan, high, low, -1, top_vertex_pos, trend_segments.back().start);
            if (pivots.size() > 0)
            {
                TrendSegment trend;
                trend.start = top_vertex_pos;
                trend.end = trend_segments.back().start;
                trend.direction = -1;
                trend.pivots = pivots;
                trend_segments.insert(trend_segments.begin(), trend);
            }
        }
    }
    else
    {
        int bot_vertex_pos = -1;
        for (int i = trend_segments.back().start - 1; i > -1; i--)
        {
            if (duan[i] == -1)
            {
                if (bot_vertex_pos == -1 || low[i] < low[bot_vertex_pos])
                {
                    bot_vertex_pos = i;
                }
            }
        }
        if (bot_vertex_pos > -1)
        {
            auto pivots = locate_pivots(duan, high, low, 1, bot_vertex_pos, trend_segments.back().start);
            if (pivots.size() > 0)
            {
                TrendSegment trend;
                trend.start = bot_vertex_pos;
                trend.end = trend_segments.back().start;
                trend.direction = 1;
                trend.pivots = pivots;
                trend_segments.insert(trend_segments.begin(), trend);
            }
        }
    }
    // 寻找第一段走势类型之后的走势类型
    for (int i = trend_segments.back().end + 1; i < length; i++)
    {
        if (duan[i] == 1)
        {
            if (trend_segments.back().direction == 1)
            {
                // 如果是同方向新高，原走势类型继续
                if (high[i] > high[trend_segments.back().end])
                {
                    // 走势结束点后移
                    trend_segments.back().end = i;
                    // 重新计算中枢
                    trend_segments.back().pivots = locate_pivots(duan, high, low, 1, trend_segments.back().start, i);
                }
            }
            else
            {
                // 找前面一个低点是否产生了走势终结
                bool is_new_trend = false;
                for (int j = i - 1; j > trend_segments.back().end; j--)
                {
                    if (duan[j] == -1)
                    {
                        if (low[j] > trend_segments.back().pivots.back().zg)
                        {
                            is_new_trend = true;
                            // 产生了新的走势
                            TrendSegment trend;
                            trend.start = trend_segments.back().end;
                            trend.end = i;
                            trend.direction = 1;
                            trend.pivots = locate_pivots(duan, high, low, 1, trend_segments.back().end, i);
                            trend_segments.push_back(trend);
                        }
                        break;
                    }
                }
                // 是不是有新的5段走势出现
                if (!is_new_trend)
                {
                    bool is_new_high = true;
                    for (int j = i - 1; j > trend_segments.back().end; j--)
                    {
                        if (duan[j] == 1)
                        {
                            if (high[j] >= high[i])
                            {
                                is_new_high = false;
                                break;
                            }
                        }
                    }
                    if (is_new_high)
                    {
                        auto pivots = locate_pivots(duan, high, low, 1, trend_segments.back().end, i);
                        if (pivots.size() > 1 || (pivots.size() == 1 && pivots.back().is_comprehensive))
                        {
                            is_new_trend = true;
                            TrendSegment trend;
                            trend.start = trend_segments.back().end;
                            trend.end = i;
                            trend.direction = 1;
                            trend.pivots = pivots;
                            trend_segments.push_back(trend);
                        }
                    }
                }
                // 是否反向破了前个向下走势的起点高
                if (!is_new_trend)
                {
                    if (high[i] > high[trend_segments.back().start])
                    {
                        int num = count_vertexes(duan, trend_segments.back().end, i);
                        if (num >= 2)
                        {
                            is_new_trend = true;
                            TrendSegment trend;
                            trend.start = trend_segments.back().end;
                            trend.end = i;
                            trend.direction = 1;
                            trend.pivots = locate_pivots(duan, high, low, 1, trend_segments.back().end, i);
                            trend_segments.push_back(trend);
                        }
                        else
                        {
                            // 做走势合并
                            int sz = static_cast<int>(trend_segments.size());
                            if (sz >= 2)
                            {
                                if (low[trend_segments.at(sz - 2).start] < low[trend_segments.at(sz - 1).end])
                                {
                                    bool merge = true;
                                    auto pivots = locate_pivots(duan, high, low, static_cast<int>(trend_segments.at(sz - 2).direction), trend_segments.at(sz - 2).start, i);
                                    for (int x = 1; x < static_cast<int>(pivots.size()); x++)
                                    {
                                        if (pivots.at(x).zg < pivots.at(x - 1).zg)
                                        {
                                            merge = false;
                                            break;
                                        }
                                    }
                                    if (merge)
                                    {
                                        trend_segments.at(sz - 2).end = i;
                                        trend_segments.at(sz - 2).pivots = pivots;
                                        trend_segments.pop_back();
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        else if (duan[i] == -1)
        {
            if (trend_segments.back().direction == -1)
            {
                // 如果是同方向新低，原走势类型继续
                if (low[i] < low[trend_segments.back().end])
                {
                    // 走势结束点后移
                    trend_segments.back().end = i;
                    // 重新计算中枢
                    trend_segments.back().pivots = locate_pivots(duan, high, low, -1, trend_segments.back().start, i);
                }
            }
            else
            {
                // 找前面一个高点是否产生了走势终结
                bool is_new_trend = false;
                for (int j = i - 1; j > trend_segments.back().end; j--)
                {
                    if (duan[j] == 1)
                    {
                        if (high[j] < trend_segments.back().pivots.back().zd)
                        {
                            is_new_trend = true;
                            // 产生了新的走势
                            TrendSegment trend;
                            trend.start = trend_segments.back().end;
                            trend.end = i;
                            trend.direction = -1;
                            trend.pivots = locate_pivots(duan, high, low, -1, trend_segments.back().end, i);
                            trend_segments.push_back(trend);
                        }
                        break;
                    }
                }
                // 是不是有新的5段走势出现
                if (!is_new_trend)
                {
                    bool is_new_low = true;
                    for (int j = i - 1; j > trend_segments.back().end; j--)
                    {
                        if (duan[j] == -1)
                        {
                            if (low[j] <= low[i])
                            {
                                is_new_low = false;
                                break;
                            }
                        }
                    }
                    if (is_new_low)
                    {
                        auto pivots = locate_pivots(duan, high, low, -1, trend_segments.back().end, i);
                        if (pivots.size() > 1 || (pivots.size() == 1 && pivots.back().is_comprehensive))
                        {
                            is_new_trend = true;
                            TrendSegment trend;
                            trend.start = trend_segments.back().end;
                            trend.end = i;
                            trend.direction = -1;
                            trend.pivots = pivots;
                            trend_segments.push_back(trend);
                        }
                    }
                }
                // 是否反向破了前个向上走势的起点低
                if (!is_new_trend)
                {
                    if (low[i] < low[trend_segments.back().start])
                    {
                        int num = count_vertexes(duan, trend_segments.back().end, i);
                        if (num >= 2)
                        {
                            is_new_trend = true;
                            TrendSegment trend;
                            trend.start = trend_segments.back().end;
                            trend.end = i;
                            trend.direction = -1;
                            trend.pivots = locate_pivots(duan, high, low, -1, trend_segments.back().end, i);
                            trend_segments.push_back(trend);
                        }
                        else
                        {
                            // 做走势合并
                            int sz = static_cast<int>(trend_segments.size());
                            if (sz >= 2)
                            {
                                if (high[trend_segments.at(sz - 2).start] > high[trend_segments.at(sz - 1).end])
                                {
                                    bool merge = true;
                                    auto pivots = locate_pivots(duan, high, low, static_cast<int>(trend_segments.at(sz - 2).direction), trend_segments.at(sz - 2).start, i);
                                    for (size_t x = 1; x < pivots.size(); x++)
                                    {
                                        if (pivots.at(x).zd > pivots.at(x - 1).zd)
                                        {
                                            merge = false;
                                            break;
                                        }
                                    }
                                    if (merge)
                                    {
                                        trend_segments.at(sz - 2).end = i;
                                        trend_segments.at(sz - 2).pivots = pivots;
                                        trend_segments.pop_back();
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    for (size_t x = 0; x < trend_segments.size(); x++)
    {
        TrendSegment e = trend_segments.at(x);
        if (e.direction == 1)
        {
            trend[e.start] = -1;
            trend[e.end] = 1;
        }
        else
        {
            trend[e.start] = 1;
            trend[e.end] = -1;
        }
    }
    // Find first 0 in trend array and set it to -5
    for (int i = 0; i < length; i++)
    {
        if (trend[i] == 0)
        {
            trend[i] = -5;
            break;
        }
    }
    return trend;
}

std::vector<float> factor_confirm_sigs(int length, std::vector<StdBar> &std_bars)
{
    std::vector<float> sigs = std::vector<float>(length, 0);
    if (length == 0)
    {
        return sigs;
    }
    for (size_t i = 0; i < std_bars.size() - 1; i++)
    {
        StdBar b = std_bars.at(i);
        if (b.factor == -1)
        {
            sigs[std_bars.at(i + 1).start] = -1;
        }
        else if (b.factor == 1)
        {
            sigs[std_bars.at(i + 1).start] = 1;
        }
    }
    return sigs;
}
