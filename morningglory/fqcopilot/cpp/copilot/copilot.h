#pragma once

#include <vector>
#include <map>
#include <algorithm>
#include <iterator>
#include <atomic>
#include <iostream>
#include "../chanlun/czsc.h"

#pragma pack(push, 1)

// 参数类型
enum class ParamType
{
    PARAM_UNKNOWN = 0,     // 未知
    PARAM_HIGH = 1,        // 最高价
    PARAM_LOW = 2,         // 最低价
    PARAM_OPEN = 3,        // 开盘价
    PARAM_CLOSE = 4,       // 收盘价
    PARAM_VOLUME = 5,      // 成交量
    PARAM_WAVE_OPT = 6,    // 笔参数，如1560
    PARAM_STRETCH_OPT = 7, // 线段参数
    PARAM_TREND_OPT = 8,   // 走势参数
    PARAM_MODEL_OPT = 9    // 模式参数
};

// 计算类型
enum class CalcType
{
    CALC_S0000 = 0,
    CALC_S0001 = 1,
    CALC_S0002 = 2,
    CALC_S0003 = 3,
    CALC_S0004 = 4,
    CALC_S0005 = 5,
    CALC_S0006 = 6,
    CALC_S0007 = 7,
    CALC_S0008 = 8,
    CALC_S0009 = 9,
    CALC_S0010 = 10,
    CALC_S0011 = 11,
    CALC_S0012 = 12,
};

extern std::map<int, CalcType> calcTypeMap;

// 定制模式的计算类型
enum class TailoredCalcType
{
    TAILORED_CALC_UNKNOWN = 0,
    TAILORED_CALC_S0001 = 1,
};

extern std::map<int, TailoredCalcType> tailoredCalcTypeMap;

// 买卖点类型
enum class EntrypointType
{
    ENTRYPOINT_UNKNOWN = 0,
    ENTRYPOINT_BUY_OPEN_1 = 1,
    ENTRYPOINT_BUY_OPEN_2 = 2,
    ENTRYPOINT_BUY_OPEN_3 = 3,
    ENTRYPOINT_BUY_OPEN_4 = 4,
    ENTRYPOINT_BUY_OPEN_5 = 5,
    ENTRYPOINT_BUY_OPEN_6 = 6,
    ENTRYPOINT_BUY_OPEN_7 = 7,
    ENTRYPOINT_BUY_OPEN_8 = 8,
    ENTRYPOINT_BUY_OPEN_9 = 9,
    ENTRYPOINT_SELL_OPEN_1 = -1,
    ENTRYPOINT_SELL_OPEN_2 = -2,
    ENTRYPOINT_SELL_OPEN_3 = -3,
    ENTRYPOINT_SELL_OPEN_4 = -4,
    ENTRYPOINT_SELL_OPEN_5 = -5,
    ENTRYPOINT_SELL_OPEN_6 = -6,
    ENTRYPOINT_SELL_OPEN_7 = -7,
    ENTRYPOINT_SELL_OPEN_8 = -8,
    ENTRYPOINT_SELL_OPEN_9 = -9,
};

// 极点类型
enum class ExtremePointType
{
    EXTREME_POINT_UNKNOWN = 0,
    EXTREME_POINT_PEAK = 1,
    EXTREME_POINT_VALLEY = -1
};

// 方向类型
enum class DirectionType
{
    DIRECTION_UNKNOWN = 0,
    DIRECTION_UP = 1,
    DIRECTION_DOWN = -1
};

// 关键Bar，概念上的Bar，记录笔的起点和终点信息
struct KeyBar
{
    ExtremePointType type = ExtremePointType::EXTREME_POINT_UNKNOWN;
    long pos = -1;
    float high; // 最高价
    float low;  // 最低价
    float neck; // 颈线
};

// 分型笔
struct Swing
{
    long No = 0; // 序号从1开始计数
    DirectionType direction = DirectionType::DIRECTION_UNKNOWN;
    long start = -1; // 开始位置
    long end = -1;   // 结束位置
};

// 笔
struct Wave
{
    long No = 0;                                                // 序号从1开始计数
    DirectionType direction = DirectionType::DIRECTION_UNKNOWN; // 笔方向
    long start = -1;                                            // 笔开始
    long end = -1;                                              // 笔结束
};

// 线段
struct Stretch
{
    long No = 0;                                                // 序号从1开始计数
    DirectionType direction = DirectionType::DIRECTION_UNKNOWN; // 段方向
    long start = -1;                                            // 段开始
    long end = -1;                                              // 段结束
};

// 走势
struct Trend
{
    long No = 0;                                                // 序号从1开始计数
    DirectionType direction = DirectionType::DIRECTION_UNKNOWN; // 趋势方向
    long start = -1;                                            // 趋势开始
    long end = -1;                                              // 趋势结束
};

// 缠论对象
class Copilot
{
private:
    std::map<ParamType, std::vector<float>> params;

public:
    Copilot();
    virtual ~Copilot();
    void SetParam(ParamType paramType, std::vector<float> param);
    bool ExistParam(ParamType paramType);
    std::vector<float> &GetParam(ParamType paramType);
    std::vector<int> Calc(CalcType calcType);
    std::vector<int> TailoredCalc(TailoredCalcType calcType);
    void Reset();
};

// Copilot对象的代理，单例模式
class CopilotProxy
{
private:
    CopilotProxy();
    virtual ~CopilotProxy();
    thread_local static CopilotProxy *instance;
    Copilot *copilot;

public:
    static CopilotProxy &GetInstance();
    void SetParam(ParamType paramType, std::vector<float> param);
    bool ExistParam(ParamType paramType);
    std::vector<float> &GetParam(ParamType paramType);
    std::vector<int> Calc(CalcType calcType);
    std::vector<int> TailoredCalc(TailoredCalcType calcType);
    void Reset();
};

// 选股函数 - 公共的
std::vector<int> F_S0000(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options);
std::vector<int> F_S0001(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options);
std::vector<int> F_S0002(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options);
std::vector<int> F_S0003(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options);
std::vector<int> F_S0004(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options);
std::vector<int> F_S0005(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options);
std::vector<int> F_S0006(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options);
std::vector<int> F_S0007(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options);
std::vector<int> F_S0008(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options);
std::vector<int> F_S0009(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options);
std::vector<int> F_S0010(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options);
std::vector<int> F_S0011(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options);
std::vector<int> F_S0012(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options);

// 选股函数 - 定制的
std::vector<int> TAILORED_F_S0001(
    const std::vector<float> &high, const std::vector<float> &low, const std::vector<float> &open, const std::vector<float> &close,
    const std::vector<float> &vol, int switch_opt, const ChanOptions &options);

#pragma pack(pop)
