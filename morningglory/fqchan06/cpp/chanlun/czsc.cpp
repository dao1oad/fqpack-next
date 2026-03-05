#include <chrono>
#include <unordered_map>
#include "../common/log.h"
#include "chan.h"
#include "czsc.h"

static const std::chrono::time_point<std::chrono::system_clock> expiry_time = std::chrono::system_clock::from_time_t(EXPIRY_TIME);

bool is_expired() {
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
    if (i < 0 || j >= sigs_num || i >= j) {
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

void update_factor_high_low(std::vector<StdBar>& std_bars) {
    if (std_bars.empty()) return;
    
    StdBar& last_bar = std_bars.back();
    
    if (std_bars.size() == 1) {
        // 第一个std_bar的分型高和分型低都是自己的高和低
        last_bar.factor_high = last_bar.high;
        last_bar.factor_low = last_bar.low;
    } else {
        const StdBar& prev_bar = std_bars[std_bars.size() - 2];
        
        if (last_bar.direction == 1) {
            // 方向向上的std_bar
            last_bar.factor_low = prev_bar.low;
            last_bar.factor_high = last_bar.high;
        } else if (last_bar.direction == -1) {
            // 方向向下的std_bar
            last_bar.factor_high = prev_bar.high;
            last_bar.factor_low = last_bar.low;
        }
    }
}

std::vector<StdBar> recognise_std_bars(int length, std::vector<float> &high, std::vector<float> &low)
{
    std::vector<StdBar> std_bars;
    if (length == 0)
    {
        return std_bars;
    }
    std::vector<StdBar> factors;
    // 开始的时候，我们先找出原始K柱的初始方向
    for (int i = 1; i < length; i++)
    {
        if ((high[i] > high[i - 1] && low[i] > low[i - 1]) ||
            (high[i] < high[i - 1] && low[i] < low[i - 1]))
        {
            // 第一个柱的方向取决于条件
            float dir1 = (high[i] > high[i - 1]) ? -1.0f : 1.0f;
            float dir2 = -dir1; // 第二个柱的方向相反
            
            // 创建第一个柱
            StdBar bar1;
            bar1.direction = dir1;
            bar1.start = i-1;
            bar1.end = i-1;
            bar1.high_vertex_raw_pos = i-1;
            bar1.low_vertex_raw_pos = i-1;
            bar1.high = high[i-1];
            bar1.low = low[i-1];
            bar1.high_high = high[i-1];
            bar1.low_low = low[i-1];
            bar1.pos = 0;
            std_bars.push_back(bar1);
            update_factor_high_low(std_bars);
            
            // 创建第二个柱
            StdBar bar2;
            bar2.direction = dir2;
            bar2.start = i;
            bar2.end = i;
            bar2.high_vertex_raw_pos = i;
            bar2.low_vertex_raw_pos = i;
            bar2.high = high[i];
            bar2.low = low[i];
            bar2.high_high = high[i];
            bar2.low_low = low[i];
            bar2.pos = 1;
            std_bars.push_back(bar2);
            update_factor_high_low(std_bars);
            break;
        }
    }
    if (std_bars.empty())
    {
        return std_bars;
    }
    int i = std_bars.back().end + 1;
    for (; i < length; i++)
    {
        // 先记录一下处理之前一共有几个标准化K柱
        size_t last_std_bars_size = std_bars.size();
        if (high[i] > std_bars.at(last_std_bars_size - 1).high && low[i] > std_bars.at(last_std_bars_size - 1).low)
        {
            // 进入这里的时候，K柱是上涨排列的，这里就产生了一个新的上涨的K柱
            StdBar bar;
            bar.direction = 1;
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
        else if (high[i] < std_bars.at(last_std_bars_size - 1).high && low[i] < std_bars.at(last_std_bars_size - 1).low)
        {
            // 进入这里的时候，K柱是下跌排列的，这里就产生了一个新的下跌的K柱
            StdBar bar;
            bar.direction = -1;
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
        else if (high[i] <= std_bars.at(last_std_bars_size - 1).high && low[i] >= std_bars.at(last_std_bars_size - 1).low) // 前包含
        {
            // 进入这里的时候，K柱和前一个K柱是前包含的关系
            if (std_bars.at(last_std_bars_size - 1).direction == 1)
            {
                // 这里是向上方向的前包含处理
                std_bars.at(last_std_bars_size - 1).high = std::max(std_bars.at(last_std_bars_size - 1).high, high[i]);
                std_bars.at(last_std_bars_size - 1).low = std::max(std_bars.at(last_std_bars_size - 1).low, low[i]);
                std_bars.at(last_std_bars_size - 1).end = i;
            }
            else
            {
                // 这里是向下方向的前包含处理
                std_bars.at(last_std_bars_size - 1).high = std::min(std_bars.at(last_std_bars_size - 1).high, high[i]);
                std_bars.at(last_std_bars_size - 1).low = std::min(std_bars.at(last_std_bars_size - 1).low, low[i]);
                std_bars.at(last_std_bars_size - 1).end = i;
            }
            if (high[i] > std_bars.at(last_std_bars_size - 1).high_high)
            {
                // 这里处理最高K柱的位置是否有变化
                std_bars.at(last_std_bars_size - 1).high_vertex_raw_pos = i;
            }
            if (low[i] < std_bars.at(last_std_bars_size - 1).low_low)
            {
                // 这里处理最低K柱的位置是否有变化
                std_bars.at(last_std_bars_size - 1).low_vertex_raw_pos = i;
            }
            // 更新标准K柱的最高最低价
            std_bars.at(last_std_bars_size - 1).high_high = std::max(std_bars.at(last_std_bars_size - 1).high_high, high[i]);
            std_bars.at(last_std_bars_size - 1).low_low = std::min(std_bars.at(last_std_bars_size - 1).low_low, low[i]);
        }
        else
        {
            int direction = 0;
            for (int j = i - 1; j >= 0; j--) {
                if (high[j] > high[i] && low[j] > low[i]) {
                    direction = -1;
                    break;
                } else if (high[j] < high[i] && low[j] < low[i]) {
                    direction = 1;
                    break;
                }
            }
            bool kbar = false;
            if (std_bars.at(last_std_bars_size - 1).direction != direction) {
                kbar = true;
            }
            if (kbar)
            {
                // 虽然是有包含的K柱，我们也认为他出现了一个新的标准K柱
                // 这种标准K柱就是K型
                StdBar bar;
                bar.direction = -std_bars.at(last_std_bars_size - 1).direction;
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
                // 不是K形的时候就是一个普通的后包含处理
                int direction = std_bars.at(last_std_bars_size - 1).direction;
                if (direction == 1)
                {
                    std_bars.at(last_std_bars_size - 1).high = std::max(std_bars.at(last_std_bars_size - 1).high, high[i]);
                    std_bars.at(last_std_bars_size - 1).low = std::max(std_bars.at(last_std_bars_size - 1).low, low[i]);
                }
                else
                {
                    std_bars.at(last_std_bars_size - 1).high = std::min(std_bars.at(last_std_bars_size - 1).high, high[i]);
                    std_bars.at(last_std_bars_size - 1).low = std::min(std_bars.at(last_std_bars_size - 1).low, low[i]);
                }
                std_bars.at(last_std_bars_size - 1).end = i;
                if (high[i] > std_bars.at(last_std_bars_size - 1).high_high)
                {
                    // 更新标准K柱的最高价位置
                    std_bars.at(last_std_bars_size - 1).high_vertex_raw_pos = i;
                }
                if (low[i] < std_bars.at(last_std_bars_size - 1).low_low)
                {
                    // 更新标准K柱的最低价位置
                    std_bars.at(last_std_bars_size - 1).low_vertex_raw_pos = i;
                }
                // 更新标准K柱的最高价和最低价
                std_bars.at(last_std_bars_size - 1).high_high = std::max(std_bars.at(last_std_bars_size - 1).high_high, high[i]);
                std_bars.at(last_std_bars_size - 1).low_low = std::min(std_bars.at(last_std_bars_size - 1).low_low, low[i]);
            }
            update_factor_high_low(std_bars);
        }
        size_t cur_std_bars_size = std_bars.size();
        // 第二步判断是否分型
        if (cur_std_bars_size > 2)
        {
            StdBar &bar0 = std_bars.at(cur_std_bars_size - 3);
            StdBar &bar1 = std_bars.at(cur_std_bars_size - 2);
            StdBar &bar2 = std_bars.at(cur_std_bars_size - 1);
            if (bar1.direction != 0 && bar2.direction != 0 && bar1.direction != bar2.direction)
            {
                if (bar1.factor == 0)
                {
                    // bar1出现了新的分型
                    if (bar1.direction == 1)
                    {
                        bar1.factor = 1;
                    }
                    else
                    {
                        bar1.factor = -1;
                    }
                    factors.push_back(bar1);
                }
            }
        }
        else
        {
            StdBar &bar1 = std_bars.at(cur_std_bars_size - 2);
            StdBar &bar2 = std_bars.at(cur_std_bars_size - 1);
            if (bar1.direction != 0 && bar2.direction != 0 && bar1.direction != bar2.direction)
            {
                if (bar1.factor == 0)
                {
                    // bar1出现了新的分型
                    if (bar1.direction == 1)
                    {
                        bar1.factor = 1;
                    }
                    else
                    {
                        bar1.factor = -1;
                    }
                    factors.push_back(bar1);
                }
            }
        }
    }
    return std_bars;
}

std::vector<float> recognise_swing(int length, std::vector<float> &high, std::vector<float> &low)
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
    std::vector<StdBar> std_bars = recognise_std_bars(length, high, low);
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
