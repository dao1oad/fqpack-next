#pragma once

#include "chan.h"
#include "config.h"
#include <algorithm>
#include <iterator>
#include <unordered_map>
#include <vector>


struct Bar {
  int pos = -1;           // K柱的索引
  float timestamp = 0.0f; // 时间戳
  float high = 0.0f;      // 最高价
  float low = 0.0f;       // 最低价
  float open = 0.0f;      // 开盘价
  float close = 0.0f;     // 收盘价
};

struct Factor {
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

struct StdBar {
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

struct Segment {
  int start = -1;             // 原始K线中的起始位置
  int end = -1;               // 原始K线中的结束位置
  float direction = 0;        // 线段方向
  int comprehensive_pos = -1; // 原始K线中的成立线段的位置
  int vertexPosStart = -1;    // 笔端点中的起始位置
  int vertexPosEnd = -1;      // 笔端点中的结束位置
  bool confirmed = 0;         // 是否确认线段
};

struct Pivot {
  int start = -1;
  int end = -1;
  float zg = 0;
  float zd = 0;
  float gg = 0;
  float dd = 0;
  float direction = 0;
  bool is_comprehensive = false;
};

struct Vertex {
  int pos = -1;     // 顶点在原始K线中的位置
  float type = 0;   // 顶点类型，1=顶点，-1=底点
  int logicPos = 0; // 第几个顶点
};

// ========================================
// xd_v2: 线段重构数据结构
// ========================================

// 线段方向
enum class Direction {
  UP = 1,   // 向上线段
  DOWN = -1 // 向下线段
};

// 特征序列元素（对应一根笔的完整区间）
struct FeatureElement {
  int start_pos;        // 特征元素开始位置（K线索引）
  int end_pos;          // 特征元素结束位置（K线索引）
  int start_vertex_idx; // 起始顶点索引
  int end_vertex_idx;   // 结束顶点索引
  float high;           // 区间最高价
  float low;            // 区间最低价
  Direction
      dir; // 所属线段方向（UP=向上线段的特征序列，DOWN=向下线段的特征序列）
};

// 线段状态
struct SegmentState {
  int vertex_start; // 起始顶点索引
  int vertex_end;   // 结束顶点索引
  int start_pos;    // 起始位置（K线索引）
  int end_pos;      // 结束位置（K线索引）
  Direction dir;    // 方向
  bool confirmed;   // 是否确认
};

// FractalChecker 破坏类型
enum class BreakType {
  NONE,           // 未破坏
  STANDARD,       // 标准破坏：第三根破坏第一根
  GAP_FILLED,     // 缺口填补：后续某根破坏第一根
  REVERSE_FRACTAL // 反向分型破坏：反向分型第三根破坏第一根
};

// 破坏结果
struct BreakResult {
  BreakType type;
  int break_feature_idx; // 破坏元素在特征序列中的索引
};

// 特征序列元素关系类型
enum class FeatureRelation {
  NONE,                // 无关系（不能直接比较）
  FRONT_INCLUDES_BACK, // 前包含后：前者的范围包含后者
  BACK_INCLUDES_FRONT, // 后包含前：后者的范围包含前者
  MONOTONIC_RISING,    // 单调递增：后者的高和低都高于前者
  MONOTONIC_FALLING    // 单调递减：后者的高和低都低于前者
};

// ========================================
// xd_v2: 函数声明
// ========================================

// 特征序列处理
namespace FeatureSequence {
FeatureElement extract_one(const std::vector<Vertex> &vertexes, int vertex_idx,
                           const std::vector<float> &high,
                           const std::vector<float> &low, int length);

void merge_include(std::vector<FeatureElement> &seq, Direction dir);
} // namespace FeatureSequence

// 分型与破坏判断
namespace FractalChecker {
BreakResult check_break(const std::vector<FeatureElement> &seq, Direction dir);

std::pair<int, bool> find_fractal(const std::vector<FeatureElement> &seq,
                                  int start_idx, Direction dir);

bool is_fractal(const FeatureElement &e1, const FeatureElement &e2,
                const FeatureElement &e3, Direction dir);

bool is_standard_break(const FeatureElement &first, const FeatureElement &third,
                       Direction dir);

int check_gap_filled(const std::vector<FeatureElement> &seq, int first_idx,
                     Direction dir);

BreakResult check_reverse_fractal_break(const std::vector<FeatureElement> &seq,
                                        int first_idx, Direction dir);
} // namespace FractalChecker

// 线段构建
namespace SegmentBuilder {
// 暂时禁用，依赖 extract 函数
/*
bool check_end(
    const std::vector<Vertex>& vertexes,
    const std::vector<float>& high,
    const std::vector<float>& low,
    const SegmentState& current,
    int check_vertex_idx,
    int& out_end_vertex_idx
);
*/
} // namespace SegmentBuilder

// 从指定顶点开始查找单调特征序列
// 起点为低点：查找单调递增序列，后续 LOW 不能低于起点
// 起点为高点：查找单调递减序列，后续 HIGH 不能高于起点
// 返回值：pair<SegmentState, bool>，bool 表示是否找到
std::pair<SegmentState, bool> find_monotonic_feature_sequence(
    const std::vector<Vertex>& vertexes,
    int start_vertex_idx,
    const std::vector<float>& high,
    const std::vector<float>& low,
    int length);

// 获取线段特征序列的极值价格
// 向上线段：返回特征序列的 MAX(high)
// 向下线段：返回特征序列的 MIN(low)
float get_segment_extreme_price(
    const SegmentState& seg,
    const std::vector<Vertex>& vertexes,
    const std::vector<float>& high,
    const std::vector<float>& low,
    int length);

// 主函数
std::vector<float> recognise_duan(int length, std::vector<float> &bi,
                                  std::vector<float> &high,
                                  std::vector<float> &low);

struct Entanglement {
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
struct TrendSegment {
  int start = -1;            // 走势类型开始
  int end = -1;              // 走势类型结束
  float direction = 0;       // 走势类型方向
  std::vector<Pivot> pivots; // 中枢
};

int count_vertexes(std::vector<float> &vertexes, int i, int j); // 弃用
std::vector<Pivot> locate_pivots(std::vector<float> &vertexes,
                                 std::vector<float> &high,
                                 std::vector<float> &low, int direction, int i,
                                 int j);

std::vector<Bar> recognise_bars(int length, std::vector<float> &high,
                                std::vector<float> &low);
std::vector<StdBar> recognise_std_bars(int length, std::vector<float> &high,
                                       std::vector<float> &low);
std::vector<float> recognise_swing(int length, std::vector<float> &high,
                                   std::vector<float> &low);
std::vector<float> recognise_bi(int length, std::vector<float> &high,
                                std::vector<float> &low, ChanOptions &options);
std::vector<float> recognise_duan(int length, std::vector<float> &bi,
                                  std::vector<float> &high,
                                  std::vector<float> &low);
std::vector<Pivot>
recognise_pivots(int length, std::vector<float> &higher_level_sigs,
                 std::vector<float> &sigs, std::vector<float> &high,
                 std::vector<float> &low, ChanOptions &options);
std::vector<float> recognise_trend(int length, std::vector<float> &duan,
                                   std::vector<float> &high,
                                   std::vector<float> &low);

std::vector<float> factor_confirm_sigs(int length,
                                       std::vector<StdBar> &std_bars);

std::unordered_map<float, int>
count_values_float(const std::vector<float> &values,
                   const std::vector<float> &values_to_count, int i, int j,
                   bool include);
int sum_counts(const std::unordered_map<float, int> &counts);

bool is_expired(); // 检查是否过期
