#pragma once

#include <vector>
#include "chan_context.h"
#include "../chanlun/czsc.h"

struct DetailedBatchResult
{
    std::vector<std::vector<int>> signals;
    std::vector<int> buy_base_trigger_masks;
    std::vector<int> sell_base_trigger_masks;
};

struct DetailedModelResult
{
    std::vector<int> signals;
    std::vector<int> buy_base_trigger_masks;
    std::vector<int> sell_base_trigger_masks;
};

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

    // 复用已计算的 ChanContext，只计算一个模型。
    std::vector<int> calc_model(int model_id);

    // 复用同一个 ChanContext，同时返回模型原始信号和逐 bar 基础触发掩码。
    DetailedBatchResult calc_all_detailed();

    // 通达信主图使用：一次计算选定模型及逐 bar 基础触发掩码。
    DetailedModelResult calc_model_detailed(int model_id);

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
