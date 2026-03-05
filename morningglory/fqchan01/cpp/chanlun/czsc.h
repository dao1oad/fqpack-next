#pragma once

#include <vector>
#include <algorithm>
#include <iterator>
#include <unordered_map>
#include "config.h"
#include "chan.h"

struct Bar
{
    int pos = -1;           // K柱的索引
    float timestamp = 0.0f; // 时间戳
    float high = 0.0f;      // 最高价
    float low = 0.0f;       // 最低价
    float open = 0.0f;      // 开盘价
    float close = 0.0f;     // 收盘价
};

struct Factor
{
    int type;        // 1=顶分型，-1=底分型
    int start;       // 分型开始位置
    int end;         // 分型结束位置
    int highPos;     // 分型高点位置
    int lowPos;      // 分型低点位置
    float rangeHigh; // 分型区间高点
    float rangeLow;  // 分型区间低点
    float mostHigh;  // 分型区间高点
    float mostLow;   // 分型区间低点
    float strong;    // 是否强分型，0=不是强分型，1=强分型
};

struct StdBar
{
    int pos = -1;                 // 本身是第几个合并K线
    int start = -1;               // 包含K线中最前一根的索引
    int end = -1;                 // 包含K线中最后一根的索引
    int high_vertex_raw_pos = -1; // 最高点索引
    int low_vertex_raw_pos = -1;  // 最低点索引
    float high = 0;               // 合并K线的最高价
    float low = 0;                // 合并K线的最低价
    float high_high = 0;          // 包含K线中的最高价
    float low_low = 0;            // 包含K线中的最低价
    float direction = 0;          // K线方向
    float factor = 0;             // -1=底分型的底，1=顶分型顶，0=不是分型
    float factor_high = 0;        // 分型区间高
    float factor_low = 0;         // 分形区间低
    int factor_strong = 0;        // 是否强分型，0=不是强分型，1=强分型
};

struct Segment
{
    int start = -1;             // 原始K线中的起始位置
    int end = -1;               // 原始K线中的结束位置
    float direction = 0;        // 线段方向
    int comprehensive_pos = -1; // 原始K线中的成立线段的位置
    int vertexPosStart = -1;    // 笔端点中的起始位置
    int vertexPosEnd = -1;      // 笔端点中的结束位置
    bool confirmed = 0;         // 是否确认线段
};

struct Pivot
{
    int start = -1;
    int end = -1;
    float zg = 0;
    float zd = 0;
    float gg = 0;
    float dd = 0;
    float direction = 0;
    bool is_comprehensive = false;
};

struct Vertex
{
    int pos = -1;     // 顶点在原始K线中的位置
    float type = 0;   // 顶点类型，1=顶点，-1=底点
    int logicPos = 0; // 第几个顶点
};

struct Entanglement
{
    std::vector<Vertex> vertexes; // 高低低点的顶点
    float high = 0;               // 纠缠区域的的高点
    float low = 0;                // 纠缠区域的低点
    float most_high = 0;          // 纠缠区域的最高点
    int most_high_pos = -1;       // 纠缠区域的最高点的位置
    float most_low = 0;           // 纠缠区域的最低点
    int most_low_pos = -1;        // 纠缠区域的最低点的位置
    int type = 0;                 // 向上(1)中枢的纠缠还是向下(-1)中枢的纠缠
    bool overlap = 0;             // 纠缠是否重叠
};

// 走势类型
struct TrendSegment
{
    int start = -1;            // 走势类型开始
    int end = -1;              // 走势类型结束
    float direction = 0;       // 走势类型方向
    std::vector<Pivot> pivots; // 中枢
};

int count_vertexes(std::vector<float> &vertexes, int i, int j); // 弃用
std::vector<Pivot> locate_pivots(std::vector<float> &vertexes, std::vector<float> &high, std::vector<float> &low, int direction, int i, int j);

std::vector<Bar> recognise_bars(int length, std::vector<float> &high, std::vector<float> &low);
std::vector<StdBar> recognise_std_bars(int length, std::vector<float> &high, std::vector<float> &low, ChanOptions &options);
std::vector<float> recognise_swing(int length, std::vector<float> &high, std::vector<float> &low, ChanOptions &options);
std::vector<float> recognise_bi(int length, std::vector<float> &high, std::vector<float> &low, ChanOptions &options);
std::vector<float> recognise_duan(int length, std::vector<float> &bi, std::vector<float> &high, std::vector<float> &low);
std::vector<Pivot> recognise_pivots(
    int length, std::vector<float> &higher_level_sigs, std::vector<float> &sigs,
    std::vector<float> &high, std::vector<float> &low, ChanOptions &options);
std::vector<float> recognise_trend(int length, std::vector<float> &duan, std::vector<float> &high, std::vector<float> &low);

std::vector<float> factor_confirm_sigs(int length, std::vector<StdBar> &std_bars);

std::unordered_map<float, int> count_values_float(
    const std::vector<float> &values,
    const std::vector<float> &values_to_count,
    int i, int j,
    bool include);
int sum_counts(const std::unordered_map<float, int> &counts);

bool is_expired(); // 检查是否过期
