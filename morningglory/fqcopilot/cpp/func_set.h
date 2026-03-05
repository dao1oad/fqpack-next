#pragma once

#include <vector>

std::vector<float> clxs(
    int length,
    std::vector<float> &high, std::vector<float> &low, std::vector<float> &open, std::vector<float> &close,
    std::vector<float> &vol,
    int wave_opt, int stretch_opt, int trend_opt, int model_opt);
