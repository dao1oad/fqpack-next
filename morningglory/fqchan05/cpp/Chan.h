#ifndef __CHAN_H__
#define __CHAN_H__

#include <vector>
#include <algorithm>
#include <iterator>
#include <atomic>

#pragma pack(push, 1)

enum class ParamType
{
    UNKNOWN = 0, // 未知
    HIGH = 1,    // 最高价
    LOW = 2,     // 最低价
    OPEN = 3,    // 开盘价
    CLOSE = 4,   // 收盘价
    VOLUME = 5,  // 成交量
    SWING = 10,          // 分型笔端点
    WAVE = 20,          // 笔端点
};

// 极点类型
enum class ExtremePointType
{
    UNKNOWN = 0,
    PEAK = 1,
    VALLEY = -1
};

// 方向类型
enum class DirectionType
{
    UNKNOWN = 0,
    UP = 1,
    DOWN = -1
};

// Bar
struct Bar
{
    long No = 0;    // 序号从1开始计数
    long i = -1;    // 位置
    float high = 0; // 最高价
    float low = 0;  // 最低价
};

// 合并Bar
struct MergedBar
{
    long No = 0;                                      // 序号从1开始计数
    long peekPos = -1;                                // 最高K线位置
    long valleyPos = -1;                              // 最低K线位置
    DirectionType direction = DirectionType::UNKNOWN; // K线方向
    long start = -1;                                  // 开始坐标
    long end = -1;                                    // 结束坐标
    float high = 0;                                   // 合并后最高价
    float low = 0;                                    // 合并后最低价
    float top = 0;                                    // 最高价
    float bottom = 0;                                 // 最低价
    std::vector<Bar> bars;                            // 笔中的原始K线
};

// 关键Bar，概念上的Bar，记录笔的起点和终点信息
struct KeyBar
{
    ExtremePointType type = ExtremePointType::UNKNOWN;
    long pos = -1;
    float high; // 最高价
    float low;  // 最低价
    float neck; // 颈线
};

struct Pivot
{
    long No = 0; // 序号从1开始计数
    DirectionType direction = DirectionType::UNKNOWN;
    long start = -1; // 开始位置
    long end = -1;   // 结束位置
    float zg = 0;    // 中枢高
    float zd = 0;    // 中枢低
    float gg = 0;    // 中枢高高
    float dd = 0;    // 中枢低低
};

// 分型笔
struct Swing
{
    long No = 0; // 序号从1开始计数
    DirectionType direction = DirectionType::UNKNOWN;
    long start = -1; // 开始位置
    long end = -1;   // 结束位置
};

// 笔
struct Wave
{
    long No = 0;                                      // 序号从1开始计数
    DirectionType direction = DirectionType::UNKNOWN; // 笔方向
    KeyBar startKeyBar;                               // 开始关键Bar
    KeyBar endKeyBar;                                 // 结束关键Bar
    std::vector<MergedBar> mergedBars;                // 笔中的合并K线
    std::vector<Pivot> pivots;                        // 分型中枢
};

// 线段
struct Stretch
{
    long No = 0;                                      // 序号从1开始计数
    DirectionType direction = DirectionType::UNKNOWN; // 段方向
    long start = -1;                                  // 段开始
    long end = -1;                                    // 段结束
    std::vector<Wave> waves;                          // 段包含的笔
    std::vector<Pivot> pivots;                        // 笔中枢
};

// 走势
struct Trend
{
    long No = 0;                                      // 序号从1开始计数
    DirectionType direction = DirectionType::UNKNOWN; // 趋势方向
    long start = -1;                                  // 趋势开始
    long end = -1;                                    // 趋势结束
    std::vector<Stretch> stretches;                   // 趋势包含的段
    std::vector<Pivot> pivots;                        // 中枢
};

// 缠论对象
class Chan
{
private:
    std::vector<float> highs;
    std::vector<float> lows;
    std::vector<float> opens;
    std::vector<float> closes;
    std::vector<float> volumes;
    std::vector<Bar> bars;          // K线
    std::vector<Swing> swings;      // 分型笔
    std::vector<Wave> waves;        // 笔
    std::vector<Stretch> stretches; // 段
    std::vector<Trend> trends;      // 趋势
    Wave ripple;                    // 和当前笔相反的为成型笔
    void OnBar(Bar &bar);
    void OnBarWhenFirst(Bar &bar);
    void OnBarWhenUnknownDirection(Bar &bar);
    void OnBarWhenKnownDirection(Bar &bar);

public:
    Chan();
    virtual ~Chan();
    void SetHighs(std::vector<float> &highs);
    std::vector<float> &GetHighs();
    void SetLows(std::vector<float> &lows);
    std::vector<float> &GetLows();
    void SetOpens(std::vector<float> &opens);
    std::vector<float> &GetOpens();
    void SetCloses(std::vector<float> &closes);
    std::vector<float> &GetCloses();
    void SetVolumes(std::vector<float> &volumes);
    std::vector<float> &GetVolumes();
    void Append(float high, float low, float open, float close, float volume);
    size_t Proceed();
    std::vector<Bar> &GetBars();
    std::vector<Swing> &GetSwings();
    std::vector<Wave> &GetWaves();
    std::vector<Stretch> &GetStretches();
    std::vector<Trend> &GetTrends();
    void Reset();
};

// Chan对象的代理，单例模式
class ChanProxy
{
private:
    ChanProxy();
    virtual ~ChanProxy();
    thread_local static ChanProxy *instance;
    Chan *chan;

public:
    static ChanProxy &GetInstance();
    void SetHighs(std::vector<float> &highs);
    std::vector<float> &GetHighs();
    void SetLows(std::vector<float> &lows);
    std::vector<float> &GetLows();
    void SetOpens(std::vector<float> &opens);
    std::vector<float> &GetOpens();
    void SetCloses(std::vector<float> &closes);
    std::vector<float> &GetCloses();
    void SetVolumes(std::vector<float> &volumes);
    std::vector<float> &GetVolumes();
    void Append(float high, float low, float open, float close, float volume);
    size_t Proceed();
    std::vector<Bar> &GetBars();
    std::vector<Swing> &GetSwings();
    std::vector<Wave> &GetWaves();
    std::vector<Stretch> &GetStretches();
    std::vector<Trend> &GetTrends();
    void Reset();
};

#pragma pack(pop)

#endif
