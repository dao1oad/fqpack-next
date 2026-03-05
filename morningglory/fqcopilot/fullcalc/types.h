// Unified data structures for fullcalc module.
#pragma once

#include <string>
#include <vector>

struct PivotOut {
    int start = -1;
    int end = -1;
    float zg = 0.0f;
    float zd = 0.0f;
    float gg = 0.0f;
    float dd = 0.0f;
    int direction = 0;
};

struct ClxSignalOut {
    int model = 0;
    int index = -1;
    float close = 0.0f;
    float stop_loss = 0.0f; // 0 表示缺失
    int signal = 0;         // >0 买点，<0 卖点
};

struct FullCalcResult {
    bool ok = false;
    std::string error;
    std::vector<int> bi;        // 1/-1
    std::vector<int> duan;      // 1/-1
    std::vector<int> duan_high; // 高阶段信号（由段再识别）
    std::vector<PivotOut> pivots;      // 基础中枢（段/笔级）
    std::vector<PivotOut> pivots_high; // 高阶中枢（趋势级）
    std::vector<ClxSignalOut> signals;
};

