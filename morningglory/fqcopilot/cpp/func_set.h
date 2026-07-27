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

// 新增研究接口：前 18 行为模型原始信号，第 18/19 行分别为买/卖
// 基础触发掩码。原有 clxs/clxs_all ABI 保持不变。
std::vector<std::vector<int>> clxs_all_detailed(
    int length,
    std::vector<float> &high, std::vector<float> &low,
    std::vector<float> &open, std::vector<float> &close,
    std::vector<float> &vol,
    int wave_opt, int stretch_opt, int trend_opt);
