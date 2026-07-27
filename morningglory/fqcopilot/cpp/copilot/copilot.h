#pragma once

#include <vector>
#include <map>
#include <memory>
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
    PARAM_EXT_OPT = 8,     // 模型扩展参数
    PARAM_TREND_OPT = PARAM_EXT_OPT, // 兼容既有插件入口名称
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
    CALC_S0013 = 13,
    CALC_S0014 = 14,
    CALC_S0015 = 15,
    CALC_S0016 = 16,
    CALC_S0017 = 17,
    CALC_S0101 = 101,
};

extern std::map<int, CalcType> calcTypeMap;

// 保留既有定制公式入口；CLX 批量研究接口不改变它的 ABI。
enum class TailoredCalcType
{
    TAILORED_CALC_UNKNOWN = 0,
    TAILORED_CALC_S0001 = 1,
};

extern std::map<int, TailoredCalcType> tailoredCalcTypeMap;

// 策略注册表
using CalcFn = std::vector<int>(*)(
    const std::vector<float> &, const std::vector<float> &,
    const std::vector<float> &, const std::vector<float> &,
    const std::vector<float> &, int, const ChanOptions &);

std::map<int, CalcFn> &get_calc_registry();

#define REGISTER_CALC(type_key, fn)                         \
    static bool _reg_##type_key = []                        \
    {                                                       \
        get_calc_registry()[type_key] = fn;                 \
        return true;                                        \
    }();

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

// 统一段结构（替代 Swing/Wave/Stretch/Trend 的 find_* 返回类型）
struct Seg
{
    long No = 0;
    DirectionType direction = DirectionType::DIRECTION_UNKNOWN;
    long start = -1;
    long end = -1;
};

using Segs = std::vector<Seg>;

// 关键Bar，概念上的Bar，记录笔的起点和终点信息
struct KeyBar
{
    ExtremePointType type = ExtremePointType::EXTREME_POINT_UNKNOWN;
    long pos = -1;
    float high; // 最高价
    float low;  // 最低价
    float neck; // 颈线
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

// Copilot 对象的代理，Meyer's Singleton（thread_local）
class CopilotProxy
{
private:
    CopilotProxy();
    ~CopilotProxy();
    CopilotProxy(const CopilotProxy &) = delete;
    CopilotProxy &operator=(const CopilotProxy &) = delete;
    std::unique_ptr<Copilot> copilot;

public:
    static CopilotProxy &GetInstance();
    void SetParam(ParamType paramType, std::vector<float> param);
    bool ExistParam(ParamType paramType);
    std::vector<float> &GetParam(ParamType paramType);
    std::vector<int> Calc(CalcType calcType);
    std::vector<int> TailoredCalc(TailoredCalcType calcType);
    void Reset();
};

// 策略函数声明（统一签名，S0015 通过 options.ext_opt 传递扩展参数）
std::vector<int> F_S0000(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);
std::vector<int> F_S0001(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);
std::vector<int> F_S0002(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);
std::vector<int> F_S0003(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);
std::vector<int> F_S0004(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);
std::vector<int> F_S0005(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);
std::vector<int> F_S0006(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);
std::vector<int> F_S0007(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);
std::vector<int> F_S0008(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);
std::vector<int> F_S0009(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);
std::vector<int> F_S0010(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);
std::vector<int> F_S0011(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);
std::vector<int> F_S0012(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);
std::vector<int> F_S0013(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);
std::vector<int> F_S0014(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);
std::vector<int> F_S0015(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);
std::vector<int> F_S0016(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);
std::vector<int> F_S0017(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);
std::vector<int> F_S0101(const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, const std::vector<float> &, int, const ChanOptions &);

std::vector<int> TAILORED_F_S0001(
    const std::vector<float> &, const std::vector<float> &,
    const std::vector<float> &, const std::vector<float> &,
    const std::vector<float> &, int, const ChanOptions &);

#pragma pack(pop)
