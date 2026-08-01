#pragma once

#include <vector>

std::vector<float> clxs(
    int length,
    std::vector<float> &high, std::vector<float> &low, std::vector<float> &open, std::vector<float> &close,
    std::vector<float> &vol,
    int wave_opt, int stretch_opt, int trend_opt, int model_opt);

// 批量计算全部 18 个模型
std::vector<std::vector<float>> clxs_all(
    int length,
    std::vector<float> &high, std::vector<float> &low,
    std::vector<float> &open, std::vector<float> &close,
    std::vector<float> &vol,
    int wave_opt, int stretch_opt, int trend_opt);

std::vector<std::vector<float>> clxs_all(
    int length,
    std::vector<float> &high, std::vector<float> &low,
    std::vector<float> &open, std::vector<float> &close,
    std::vector<float> &vol,
    int wave_opt, int stretch_opt, int trend_opt, int switch_opt);

std::vector<int> clxs_s0002_entrypoint3_evidence(
    int length,
    std::vector<float> &high, std::vector<float> &low,
    std::vector<float> &open, std::vector<float> &close,
    std::vector<float> &vol,
    int wave_opt, int stretch_opt, int trend_opt, int switch_opt);
