#pragma once

#include <vector>
#include <algorithm>
#include <iterator>
#include <atomic>
#include <mutex>
#include <memory>

enum class ChanParamType
{
    WAVE_OPT = 0,    // 笔参数
    STRETCH_OPT = 1, // 线段参数
    TREND_OPT = 2,   // 趋势参数
    PIVOT_OPT = 3,   // 中枢参数
};

struct ChanOptions
{
    // 笔模式: 4=最少满足4个K的笔，5=最少满足5个K的笔，6=大笔
    int bi_mode = 6;
    // N等于14的时候，不强制成笔，N大于等于15的时候，要尽量寻找次高次低来成笔。
    int force_wave_stick_count = 15;
    // 在没有出现新的线段前，最后一个中枢，是否允许跨段继续延申。
    int allow_pivot_across = 0;
    // 合并未完备的笔
    int merge_non_complehensive_wave = 0;
};

class Chan
{
private:
    std::unique_ptr<ChanOptions> options;

public:
    Chan() : options(std::make_unique<ChanOptions>()) {};
    virtual ~Chan() {};
    void reset() { options = std::make_unique<ChanOptions>(); };
    void set_bi_mode(int bi_mode);
    int get_bi_mode();
    void set_force_wave_stick_count(int force_wave_stick_count);
    int get_force_wave_stick_count();
    void set_allow_pivot_across(int allow_pivot_across);
    int get_allow_pivot_across();
    void set_merge_non_complehensive_wave(int merge_non_complehensive_wave);
    int get_merge_non_complehensive_wave();
    ChanOptions &get_options();
};

class ChanProxy
{
private:
    ChanProxy();
    virtual ~ChanProxy();
    ChanProxy(const ChanProxy &) = delete;            // 禁止复制构造函数
    ChanProxy &operator=(const ChanProxy &) = delete; // 禁止赋值运算符
    thread_local static ChanProxy *instance;
    thread_local static std::mutex mutex;
    std::unique_ptr<Chan> chan;

public:
    static ChanProxy &get_instance();
    void set_bi_mode(int bi_mode);
    int get_bi_mode();
    void set_force_wave_stick_count(int force_wave_stick_count);
    int get_force_wave_stick_count();
    void set_allow_pivot_across(int allow_pivot_across);
    int get_allow_pivot_across();
    void set_merge_non_complehensive_wave(int merge_non_complehensive_wave);
    int get_merge_non_complehensive_wave();
    ChanOptions &get_options();
    void reset();
};
