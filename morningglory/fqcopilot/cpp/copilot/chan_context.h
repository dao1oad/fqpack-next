#pragma once

#include <vector>
#include "../chanlun/czsc.h"
#include "../common/common.h"

// 共享缠论分析数据，供批量计算复用
struct ChanContext
{
    std::vector<float> swing_sigs;
    std::vector<float> wave_sigs;
    std::vector<float> stretch_sigs;
    std::vector<float> trend_sigs;
    std::vector<StdBar> std_bars;
    std::vector<float> strong_factors;
    std::vector<float> strong_swing_factors;
    std::vector<float> ma5;
    std::vector<float> macd;
    std::vector<float> dif;
    std::vector<float> dea;
    std::vector<float> atrs;
    int length = 0;
};
