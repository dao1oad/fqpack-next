#pragma once

#include <vector>
#include "chan_context.h"
#include "../chanlun/czsc.h"

class BatchCalculator
{
public:
    BatchCalculator(
        const std::vector<float> &high, const std::vector<float> &low,
        const std::vector<float> &open, const std::vector<float> &close,
        const std::vector<float> &vol,
        int switch_opt, const ChanOptions &options);

    // 一次缠论分析 + 18 个模型计算，按 model_id (0~17) 索引
    std::vector<std::vector<int>> calc_all();

private:
    ChanContext ctx;
    const std::vector<float> &high;
    const std::vector<float> &low;
    const std::vector<float> &open;
    const std::vector<float> &close;
    const std::vector<float> &vol;
    int switch_opt;
    ChanOptions options;
};
