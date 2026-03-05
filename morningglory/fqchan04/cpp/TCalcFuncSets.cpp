#include "stdafx.h"
#include "TCalcFuncSets.h"
#include "chanlun/czsc.h"
#include "common/log.h"
#include "chanlun/chan.h"

//=============================================================================
// 输出函数1号：输出分型笔端点
//=============================================================================
void Func1(int count, float *out, float *high, float *low, float *ignore)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(float));
    std::vector<float> h(high, high + count);
    std::vector<float> l(low, low + count);
    std::vector<float> sw = recognise_swing(count, h, l);
    for (size_t i = 0; i < sw.size(); i++)
    {
        out[i] = sw[i];
    }
}

//=============================================================================
// 输出函数2号：输出笔顶底端点
//=============================================================================
void Func2(int count, float *out, float *high, float *low, float *ignore)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(float));
    std::vector<float> h(high, high + count);
    std::vector<float> l(low, low + count);
    ChanProxy &chan = ChanProxy::get_instance();
    std::vector<float> bi = recognise_bi(count, h, l, chan.get_options());
    for (size_t i = 0; i < bi.size(); i++)
    {
        out[i] = bi[i];
    }
}

//=============================================================================
// 输出函数3号：输出段的端点
//=============================================================================
void Func3(int count, float *out, float *bi, float *high, float *low)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(float));
    std::vector<float> b(bi, bi + count);
    std::vector<float> h(high, high + count);
    std::vector<float> l(low, low + count);
    std::vector<float> duan = recognise_duan(count, b, h, l);
    for (size_t i = 0; i < duan.size(); i++)
    {
        out[i] = duan[i];
    }
}

//=============================================================================
// 输出函数4号：输出走势端点
//=============================================================================
void Func4(int count, float *out, float *duan, float *high, float *low)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(float));
    std::vector<float> d(duan, duan + count);
    std::vector<float> h(high, high + count);
    std::vector<float> l(low, low + count);
    std::vector<float> trend = recognise_trend(count, d, h, l);
    for (size_t i = 0; i < trend.size(); i++)
    {
        out[i] = trend[i];
    }
}

//=============================================================================
// 输出函数5号：中枢高点（ZG）数据
//=============================================================================
void Func5(int count, float *out, float *sig_list, float *high, float *low)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(float));
    std::vector<float> sig_vector(sig_list, sig_list + count);
    std::vector<float> h(high, high + count);
    std::vector<float> l(low, low + count);
    std::vector<float> trend = std::vector<float>(count, 0);
    ChanProxy &chan = ChanProxy::get_instance();
    for (size_t i = 0; i < sig_vector.size(); i++)
    {
        if (sig_vector[i] == -2)
        {
            trend = recognise_bi(count, h, l, chan.get_options());
        }
        else if (sig_vector[i] == -3)
        {
            trend = recognise_duan(count, sig_vector, h, l);
        }
        else if (sig_vector[i] == -4 || sig_vector[i] == -5)
        {
            trend = recognise_trend(count, sig_vector, h, l);
        }
    }
    std::vector<Pivot> pivots = recognise_pivots(count, trend, sig_vector, h, l, chan.get_options());
    for (size_t x = 0; x < pivots.size(); x++)
    {
        Pivot e = pivots.at(x);
        for (int y = e.start; y <= e.end; y++)
        {
            out[y] = e.zg;
        }
    }
}

//=============================================================================
// 输出函数6号：中枢高点（GG）数据
//=============================================================================
void Func6(int count, float *out, float *sig_list, float *high, float *low)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(float));
    std::vector<float> sig_vector(sig_list, sig_list + count);
    std::vector<float> h(high, high + count);
    std::vector<float> l(low, low + count);
    std::vector<float> trend = std::vector<float>(count, 0);
    ChanProxy &chan = ChanProxy::get_instance();
    for (size_t i = 0; i < sig_vector.size(); i++)
    {
        if (sig_vector[i] == -2)
        {
            trend = recognise_bi(count, h, l, chan.get_options());
        }
        else if (sig_vector[i] == -3)
        {
            trend = recognise_duan(count, sig_vector, h, l);
        }
        else if (sig_vector[i] == -4 || sig_vector[i] == -5)
        {
            trend = recognise_trend(count, sig_vector, h, l);
        }
    }
    std::vector<Pivot> pivots = recognise_pivots(count, trend, sig_vector, h, l, chan.get_options());
    for (size_t x = 0; x < pivots.size(); x++)
    {
        Pivot e = pivots.at(x);
        for (int y = e.start; y <= e.end; y++)
        {
            out[y] = e.gg;
        }
    }
}

//=============================================================================
// 输出函数7号：中枢低点（ZD）数据
//=============================================================================
void Func7(int count, float *out, float *sig_list, float *high, float *low)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(float));
    std::vector<float> sig_vector(sig_list, sig_list + count);
    std::vector<float> h(high, high + count);
    std::vector<float> l(low, low + count);
    std::vector<float> trend = std::vector<float>(count, 0);
    ChanProxy &chan = ChanProxy::get_instance();
    for (size_t i = 0; i < sig_vector.size(); i++)
    {
        if (sig_vector[i] == -2)
        {
            trend = recognise_bi(count, h, l, chan.get_options());
        }
        else if (sig_vector[i] == -3)
        {
            trend = recognise_duan(count, sig_vector, h, l);
        }
        else if (sig_vector[i] == -4 || sig_vector[i] == -5)
        {
            trend = recognise_trend(count, sig_vector, h, l);
        }
    }
    std::vector<Pivot> pivots = recognise_pivots(count, trend, sig_vector, h, l, chan.get_options());
    for (size_t x = 0; x < pivots.size(); x++)
    {
        Pivot e = pivots.at(x);
        for (int y = e.start; y <= e.end; y++)
        {
            out[y] = e.zd;
        }
    }
}

//=============================================================================
// 输出函数8号：中枢低点（DD）数据
//=============================================================================
void Func8(int count, float *out, float *sig_list, float *high, float *low)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(float));
    std::vector<float> sig_vector(sig_list, sig_list + count);
    std::vector<float> h(high, high + count);
    std::vector<float> l(low, low + count);
    std::vector<float> trend = std::vector<float>(count, 0);
    ChanProxy &chan = ChanProxy::get_instance();
    for (size_t i = 0; i < sig_vector.size(); i++)
    {
        if (sig_vector[i] == -2)
        {
            trend = recognise_bi(count, h, l, chan.get_options());
        }
        else if (sig_vector[i] == -3)
        {
            trend = recognise_duan(count, sig_vector, h, l);
        }
        else if (sig_vector[i] == -4 || sig_vector[i] == -5)
        {
            trend = recognise_trend(count, sig_vector, h, l);
        }
    }
    std::vector<Pivot> pivots = recognise_pivots(count, trend, sig_vector, h, l, chan.get_options());
    for (size_t x = 0; x < pivots.size(); x++)
    {
        Pivot e = pivots.at(x);
        for (int y = e.start; y <= e.end; y++)
        {
            out[y] = e.dd;
        }
    }
}

//=============================================================================
// 输出函数9号：中枢起点、终点信号 1是开始 2是结束
//=============================================================================
void Func9(int count, float *p_out_values, float *p_sigs, float *p_highs, float *p_lows)
{
    if (count == 0)
        return;
    memset(p_out_values, 0, count * sizeof(float));
    std::vector<float> sigs(p_sigs, p_sigs + count);
    std::vector<float> highs(p_highs, p_highs + count);
    std::vector<float> lows(p_lows, p_lows + count);
    std::vector<float> high_level_sigs = std::vector<float>(count, 0);
    ChanProxy &chan = ChanProxy::get_instance();
    for (size_t i = 0; i < sigs.size(); i++)
    {
        if (sigs[i] == -2)
        {
            ChanProxy &chan = ChanProxy::get_instance();
            high_level_sigs = recognise_bi(count, highs, lows, chan.get_options());
        }
        else if (sigs[i] == -3)
        {
            high_level_sigs = recognise_duan(count, sigs, highs, lows);
        }
        else if (sigs[i] == -4 || sigs[i] == -5)
        {
            high_level_sigs = recognise_trend(count, sigs, highs, lows);
        }
    }
    std::vector<Pivot> pivots = recognise_pivots(count, high_level_sigs, sigs, highs, lows, chan.get_options());
    int pivots_num = static_cast<int>(pivots.size());
    for (size_t x = 0; x < pivots_num; x++)
    {
        Pivot &e = pivots.at(x);
        if (e.end > e.start)
        {
            p_out_values[e.start] = 1;
            p_out_values[e.end] = 2;
        }
    }
}

//=============================================================================
// 输出函数10号：中枢方向
//=============================================================================
void Func10(int count, float *out, float *sig_list, float *high, float *low)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(float));
    std::vector<float> sig_vector(sig_list, sig_list + count);
    std::vector<float> h(high, high + count);
    std::vector<float> l(low, low + count);
    std::vector<float> trend = std::vector<float>(count, 0);
    ChanProxy &chan = ChanProxy::get_instance();
    for (size_t i = 0; i < sig_vector.size(); i++)
    {
        if (sig_vector[i] == -2)
        {
            trend = recognise_bi(count, h, l, chan.get_options());
        }
        else if (sig_vector[i] == -3)
        {
            trend = recognise_duan(count, sig_vector, h, l);
        }
        else if (sig_vector[i] == -4 || sig_vector[i] == -5)
        {
            trend = recognise_trend(count, sig_vector, h, l);
        }
    }
    std::vector<Pivot> pivots = recognise_pivots(count, trend, sig_vector, h, l, chan.get_options());
    for (size_t x = 0; x < pivots.size(); x++)
    {
        Pivot e = pivots.at(x);
        for (int y = e.start; y <= e.end; y++)
        {
            out[y] = e.direction;
        }
    }
}

//=============================================================================
// 输出函数11号：中枢个数
//=============================================================================
void Func11(int count, float *out, float *sig_list, float *high, float *low)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(float));
    std::vector<float> sig_vector(sig_list, sig_list + count);
    std::vector<float> h(high, high + count);
    std::vector<float> l(low, low + count);
    std::vector<float> trend = std::vector<float>(count, 0);
    ChanProxy &chan = ChanProxy::get_instance();
    for (size_t i = 0; i < sig_vector.size(); i++)
    {
        if (sig_vector[i] == -2)
        {
            trend = recognise_bi(count, h, l, chan.get_options());
        }
        else if (sig_vector[i] == -3)
        {
            trend = recognise_duan(count, sig_vector, h, l);
        }
        else if (sig_vector[i] == -4 || sig_vector[i] == -5)
        {
            trend = recognise_trend(count, sig_vector, h, l);
        }
    }
    std::vector<Pivot> pivot_list = recognise_pivots(count, trend, sig_vector, h, l, chan.get_options());
    for (size_t i = 0; i < pivot_list.size(); i++)
    {
        Pivot &e = pivot_list.at(i);
        float c = 1;
        for (int j = static_cast<int>(i) - 1; j >= 0; j--)
        {
            if (pivot_list.at(j).direction == pivot_list.at(i).direction)
            {
                c++;
            }
            else
            {
                break;
            }
        }
        for (int j = e.start; j <= e.end; j++)
        {
            out[j] = c;
        }
    }
}

// 重置参数
void Func12(int count, float *out, float *in1, float *in2, float *in3)
{
    ChanProxy &chan = ChanProxy::get_instance();
    chan.reset();
}

// 传入参数
void Func13(int count, float *out_values, float *p_param_keys, float *p_param_values, float *p_ignore)
{
    if (count == 0)
        return;
    ChanProxy &chan = ChanProxy::get_instance();
    ChanParamType paramType = static_cast<ChanParamType>(static_cast<int>(p_param_keys[0]));
    int option = int(p_param_values[0]);
    
    switch (paramType) {
        case ChanParamType::WAVE_OPT:
            // 4K笔还是5K笔还是大笔
            chan.set_bi_mode(option / 10 % 10);
            // 是否15K后允许次高次低成笔
            chan.set_force_wave_stick_count(option / 100 % 100);
            // 是否合并未完备的笔
            chan.set_merge_non_complehensive_wave(option / 10000 % 10);
            break;
        case ChanParamType::PIVOT_OPT:
            chan.set_allow_pivot_across(option % 10);
            break;
        default:
            // No action for other param types
            break;
    }
}

void Func14(int count, float *out, float *in1, float *in2, float *in3)
{
}

//=============================================================================
// 输出函数15号：中枢高点（ZG）数据
//=============================================================================
void Func15(int count, float *out, float *duan, float *high, float *low)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(float));
    std::vector<float> d(duan, duan + count);
    std::vector<float> h(high, high + count);
    std::vector<float> l(low, low + count);
    ChanProxy &chan = ChanProxy::get_instance();
    std::vector<float> trend = recognise_trend(count, d, h, l);
    std::vector<Pivot> pivots = recognise_pivots(count, trend, d, h, l, chan.get_options());
    for (size_t x = 0; x < pivots.size(); x++)
    {
        Pivot e = pivots.at(x);
        for (int y = e.start; y <= e.end; y++)
        {
            out[y] = e.zg;
        }
    }
}

//=============================================================================
// 输出函数16号：中枢高点（GG）数据
//=============================================================================
void Func16(int count, float *out, float *duan, float *high, float *low)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(float));
    std::vector<float> d(duan, duan + count);
    std::vector<float> h(high, high + count);
    std::vector<float> l(low, low + count);
    ChanProxy &chan = ChanProxy::get_instance();
    std::vector<float> trend = recognise_trend(count, d, h, l);
    std::vector<Pivot> pivots = recognise_pivots(count, trend, d, h, l, chan.get_options());
    for (size_t x = 0; x < pivots.size(); x++)
    {
        Pivot e = pivots.at(x);
        for (int y = e.start; y <= e.end; y++)
        {
            out[y] = e.gg;
        }
    }
}

//=============================================================================
// 输出函数17号：中枢低点（ZD）数据
//=============================================================================
void Func17(int count, float *out, float *duan, float *high, float *low)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(float));
    std::vector<float> d(duan, duan + count);
    std::vector<float> h(high, high + count);
    std::vector<float> l(low, low + count);
    ChanProxy &chan = ChanProxy::get_instance();
    std::vector<float> trend = recognise_trend(count, d, h, l);
    std::vector<Pivot> pivots = recognise_pivots(count, trend, d, h, l, chan.get_options());
    for (size_t x = 0; x < pivots.size(); x++)
    {
        Pivot e = pivots.at(x);
        for (int y = e.start; y <= e.end; y++)
        {
            out[y] = e.zd;
        }
    }
}

//=============================================================================
// 输出函数18号：中枢低点（DD）数据
//=============================================================================
void Func18(int count, float *out, float *duan, float *high, float *low)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(float));
    std::vector<float> d(duan, duan + count);
    std::vector<float> h(high, high + count);
    std::vector<float> l(low, low + count);
    ChanProxy &chan = ChanProxy::get_instance();
    std::vector<float> trend = recognise_trend(count, d, h, l);
    std::vector<Pivot> pivots = recognise_pivots(count, trend, d, h, l, chan.get_options());
    for (size_t x = 0; x < pivots.size(); x++)
    {
        Pivot e = pivots.at(x);
        for (int y = e.start; y <= e.end; y++)
        {
            out[y] = e.dd;
        }
    }
}

//=============================================================================
// 输出函数19号：中枢起点、终点信号 1是开始 2是结束
//=============================================================================
void Func19(int count, float *out, float *duan, float *high, float *low)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(float));
    std::vector<float> d(duan, duan + count);
    std::vector<float> h(high, high + count);
    std::vector<float> l(low, low + count);
    ChanProxy &chan = ChanProxy::get_instance();
    std::vector<float> trend = recognise_trend(count, d, h, l);
    std::vector<Pivot> pivots = recognise_pivots(count, trend, d, h, l, chan.get_options());
    for (size_t x = 0; x < pivots.size(); x++)
    {
        Pivot e = pivots.at(x);
        out[e.start] = 1;
        out[e.end] = 2;
    }
}

//=============================================================================
// 输出K柱的方向
//=============================================================================
void Func20(int count, float *out, float *high, float *low, float *ignore)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(float));
    std::vector<float> h(high, high + count);
    std::vector<float> l(low, low + count);
    std::vector<StdBar> std_bars = recognise_std_bars(count, h, l);
    for (size_t i = 0; i < std_bars.size(); i++)
    {
        StdBar e = std_bars.at(i);
        if (e.direction == 1)
        {
            out[e.high_vertex_raw_pos] = 1;
        }
        else if (e.direction == -1)
        {
            out[e.low_vertex_raw_pos] = -1;
        }
    }
}

PluginTCalcFuncInfo g_CalcFuncSets[] = {
    {1, (pPluginFUNC)&Func1},
    {2, (pPluginFUNC)&Func2},
    {3, (pPluginFUNC)&Func3},
    {4, (pPluginFUNC)&Func4},
    {5, (pPluginFUNC)&Func5},
    {6, (pPluginFUNC)&Func6},
    {7, (pPluginFUNC)&Func7},
    {8, (pPluginFUNC)&Func8},
    {9, (pPluginFUNC)&Func9},
    {10, (pPluginFUNC)&Func10},
    {11, (pPluginFUNC)&Func11},
    {12, (pPluginFUNC)&Func12},
    {13, (pPluginFUNC)&Func13},
    {14, (pPluginFUNC)&Func14},
    {15, (pPluginFUNC)&Func15},
    {16, (pPluginFUNC)&Func16},
    {17, (pPluginFUNC)&Func17},
    {18, (pPluginFUNC)&Func18},
    {19, (pPluginFUNC)&Func19},
    {20, (pPluginFUNC)&Func20},
    {0, NULL},
};

BOOL RegisterTdxFunc(PluginTCalcFuncInfo **pFun)
{
    if (*pFun == NULL)
    {
        (*pFun) = g_CalcFuncSets;
        return TRUE;
    }
    return FALSE;
}

/********************************************************************/
//************************交易师 大智慧******************************//
/********************************************************************/
// --- 大智慧输出函数 --- //
int WINAPI RUNMODE()
{
    return 1;
}

int WINAPI SW(CALCINFO *pData)
{
    int nDataLen = pData->m_nNumData;
    if (nDataLen == 0)
        return 0;
    std::vector<float> high(nDataLen);
    std::vector<float> low(nDataLen);
    for (int i = 0; i < nDataLen; i++)
    {
        high[i] = pData->m_pData[i].m_fHigh;
        low[i] = pData->m_pData[i].m_fLow;
        pData->m_pResultBuf[i] = 0;
    }
    std::vector<float> out = recognise_swing(nDataLen, high, low);
    for (int i = 0; i < nDataLen; i++)
    {
        pData->m_pResultBuf[i] = out[i];
    }
    return 0;
}

int WINAPI BI(CALCINFO *pData)
{
    int nDataLen = pData->m_nNumData;
    if (nDataLen == 0)
        return 0;
    std::vector<float> high(nDataLen);
    std::vector<float> low(nDataLen);
    for (int i = 0; i < nDataLen; i++)
    {
        high[i] = pData->m_pData[i].m_fHigh;
        low[i] = pData->m_pData[i].m_fLow;
        pData->m_pResultBuf[i] = 0;
    }
    ChanOptions options;
    if (pData->m_nParam1Start < 0)
    {
        // 参数1是笔控制参数
        int option = static_cast<int>(*pData->m_pfParam1);
        // 4K笔还是5K笔还是大笔
        options.bi_mode = option / 10 % 10;
        // 是否15K后允许次高次低成笔
        options.force_wave_stick_count = option / 100 % 100;
        // 是否合并未完备的笔
        options.merge_non_complehensive_wave = option / 10000 % 10;
    }
    std::vector<float> out = recognise_bi(nDataLen, high, low, options);
    for (int i = 0; i < nDataLen; i++)
    {
        pData->m_pResultBuf[i] = out[i];
    }
    return 0;
}

int WINAPI DUANVAR(CALCINFO *pData)
{
    int nDataLen = pData->m_nNumData;
    if (nDataLen == 0)
        return 0;
    if (pData->m_pfParam1 && pData->m_nParam1Start >= 0)
    {
        int nDataLen = pData->m_nNumData;
        std::vector<float> bi(nDataLen);
        std::vector<float> high(nDataLen);
        std::vector<float> low(nDataLen);
        for (int i = 0; i < nDataLen; i++)
        {
            bi[i] = pData->m_pfParam1[i];
            high[i] = pData->m_pData[i].m_fHigh;
            low[i] = pData->m_pData[i].m_fLow;
            pData->m_pResultBuf[i] = 0;
        }
        std::vector<float> out = recognise_duan(nDataLen, bi, high, low);
        for (int i = 0; i < nDataLen; i++)
        {
            pData->m_pResultBuf[i] = out[i];
        }
        return 0;
    }
    return -1;
}

int WINAPI TRENDVAR(CALCINFO *pData)
{
    int nDataLen = pData->m_nNumData;
    if (nDataLen == 0)
        return 0;
    if (pData->m_pfParam1 && pData->m_nParam1Start >= 0)
    {
        int nDataLen = pData->m_nNumData;
        std::vector<float> duan(nDataLen);
        std::vector<float> high(nDataLen);
        std::vector<float> low(nDataLen);
        for (int i = 0; i < nDataLen; i++)
        {
            duan[i] = pData->m_pfParam1[i];
            high[i] = pData->m_pData[i].m_fHigh;
            low[i] = pData->m_pData[i].m_fLow;
            pData->m_pResultBuf[i] = 0;
        }
        std::vector<float> out = recognise_trend(nDataLen, duan, high, low);
        for (int i = 0; i < nDataLen; i++)
        {
            pData->m_pResultBuf[i] = out[i];
        }
        return 0;
    }
    return -1;
}

int WINAPI ZSZGVAR(CALCINFO *pData)
{
    int nDataLen = pData->m_nNumData;
    if (nDataLen == 0)
        return 0;
    std::vector<float> sig_vector(nDataLen);
    std::vector<float> high(nDataLen);
    std::vector<float> low(nDataLen);
    for (int i = 0; i < nDataLen; i++)
    {
        sig_vector[i] = pData->m_pfParam1[i];
        high[i] = pData->m_pData[i].m_fHigh;
        low[i] = pData->m_pData[i].m_fLow;
        pData->m_pResultBuf[i] = 0;
    }
    ChanOptions options;
    if (pData->m_pfParam2)
    {
        // 参数2是笔控制参数
        int option = static_cast<int>(*pData->m_pfParam2);
        // 4K笔还是5K笔还是大笔
        options.bi_mode = option / 10 % 10;
        // 是否15K后允许次高次低成笔
        options.force_wave_stick_count = option / 100 % 100;
        // 是否合并未完备的笔
        options.merge_non_complehensive_wave = option / 10000 % 10;
    }
    if (pData->m_pfParam4)
    {
        int option = static_cast<int>(*pData->m_pfParam4);
        options.allow_pivot_across = option % 10;
    }
    std::vector<float> trend = std::vector<float>(nDataLen, 0);
    for (size_t i = 0; i < sig_vector.size(); i++)
    {
        if (sig_vector[i] == -2)
        {
            trend = recognise_bi(nDataLen, high, low, options);
        }
        else if (sig_vector[i] == -3)
        {
            trend = recognise_duan(nDataLen, sig_vector, high, low);
        }
        else if (sig_vector[i] == -4 || sig_vector[i] == -5)
        {
            trend = recognise_trend(nDataLen, sig_vector, high, low);
        }
    }
    std::vector<Pivot> ZhongShuList = recognise_pivots(nDataLen, trend, sig_vector, high, low, options);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        for (int j = ZhongShuOne.start; j <= ZhongShuOne.end; j++)
        {
            pData->m_pResultBuf[j] = ZhongShuOne.zg;
        }
    }
    return 0;
}

int WINAPI ZSZDVAR(CALCINFO *pData)
{
    int nDataLen = pData->m_nNumData;
    if (nDataLen == 0)
        return 0;
    std::vector<float> sig_vector(nDataLen);
    std::vector<float> high(nDataLen);
    std::vector<float> low(nDataLen);
    for (int i = 0; i < nDataLen; i++)
    {
        sig_vector[i] = pData->m_pfParam1[i];
        high[i] = pData->m_pData[i].m_fHigh;
        low[i] = pData->m_pData[i].m_fLow;
        pData->m_pResultBuf[i] = 0;
    }
    ChanOptions options;
    if (pData->m_pfParam2)
    {
        // 参数2是笔控制参数
        int option = static_cast<int>(*pData->m_pfParam2);
        // 4K笔还是5K笔还是大笔
        options.bi_mode = option / 10 % 10;
        // 是否15K后允许次高次低成笔
        options.force_wave_stick_count = option / 100 % 100;
        // 是否合并未完备的笔
        options.merge_non_complehensive_wave = option / 10000 % 10;
    }
    if (pData->m_pfParam4)
    {
        int option = static_cast<int>(*pData->m_pfParam4);
        options.allow_pivot_across = option % 10;
    }
    std::vector<float> trend = std::vector<float>(nDataLen, 0);
    for (size_t i = 0; i < sig_vector.size(); i++)
    {
        if (sig_vector[i] == -2)
        {
            trend = recognise_bi(nDataLen, high, low, options);
        }
        else if (sig_vector[i] == -3)
        {
            trend = recognise_duan(nDataLen, sig_vector, high, low);
        }
        else if (sig_vector[i] == -4 || sig_vector[i] == -5)
        {
            trend = recognise_trend(nDataLen, sig_vector, high, low);
        }
    }
    std::vector<Pivot> ZhongShuList = recognise_pivots(nDataLen, trend, sig_vector, high, low, options);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        for (int j = ZhongShuOne.start; j <= ZhongShuOne.end; j++)
        {
            pData->m_pResultBuf[j] = ZhongShuOne.zd;
        }
    }
    return 0;
}

int WINAPI ZSGGVAR(CALCINFO *pData)
{
    int nDataLen = pData->m_nNumData;
    if (nDataLen == 0)
        return 0;
    std::vector<float> sig_vector(nDataLen);
    std::vector<float> high(nDataLen);
    std::vector<float> low(nDataLen);
    for (int i = 0; i < nDataLen; i++)
    {
        sig_vector[i] = pData->m_pfParam1[i];
        high[i] = pData->m_pData[i].m_fHigh;
        low[i] = pData->m_pData[i].m_fLow;
        pData->m_pResultBuf[i] = 0;
    }
    ChanOptions options;
    if (pData->m_pfParam2)
    {
        // 参数2是笔控制参数
        int option = static_cast<int>(*pData->m_pfParam2);
        // 4K笔还是5K笔还是大笔
        options.bi_mode = option / 10 % 10;
        // 是否15K后允许次高次低成笔
        options.force_wave_stick_count = option / 100 % 100;
        // 是否合并未完备的笔
        options.merge_non_complehensive_wave = option / 10000 % 10;
    }
    if (pData->m_pfParam4)
    {
        int option = static_cast<int>(*pData->m_pfParam4);
        options.allow_pivot_across = option % 10;
    }
    std::vector<float> trend = std::vector<float>(nDataLen, 0);
    for (size_t i = 0; i < sig_vector.size(); i++)
    {
        if (sig_vector[i] == -2)
        {
            trend = recognise_bi(nDataLen, high, low, options);
        }
        else if (sig_vector[i] == -3)
        {
            trend = recognise_duan(nDataLen, sig_vector, high, low);
        }
        else if (sig_vector[i] == -4 || sig_vector[i] == -5)
        {
            trend = recognise_trend(nDataLen, sig_vector, high, low);
        }
    }
    std::vector<Pivot> ZhongShuList = recognise_pivots(nDataLen, trend, sig_vector, high, low, options);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        for (int j = ZhongShuOne.start; j <= ZhongShuOne.end; j++)
        {
            pData->m_pResultBuf[j] = ZhongShuOne.gg;
        }
    }
    return 0;
}

int WINAPI ZSDDVAR(CALCINFO *pData)
{
    int nDataLen = pData->m_nNumData;
    if (nDataLen == 0)
        return 0;
    std::vector<float> sig_vector(nDataLen);
    std::vector<float> high(nDataLen);
    std::vector<float> low(nDataLen);
    for (int i = 0; i < nDataLen; i++)
    {
        sig_vector[i] = pData->m_pfParam1[i];
        high[i] = pData->m_pData[i].m_fHigh;
        low[i] = pData->m_pData[i].m_fLow;
        pData->m_pResultBuf[i] = 0;
    }
    ChanOptions options;
    if (pData->m_pfParam2)
    {
        // 参数2是笔控制参数
        int option = static_cast<int>(*pData->m_pfParam2);
        // 4K笔还是5K笔还是大笔
        options.bi_mode = option / 10 % 10;
        // 是否15K后允许次高次低成笔
        options.force_wave_stick_count = option / 100 % 100;
        // 是否合并未完备的笔
        options.merge_non_complehensive_wave = option / 10000 % 10;
    }
    if (pData->m_pfParam4)
    {
        int option = static_cast<int>(*pData->m_pfParam4);
        options.allow_pivot_across = option % 10;
    }
    std::vector<float> trend = std::vector<float>(nDataLen, 0);
    for (size_t i = 0; i < sig_vector.size(); i++)
    {
        if (sig_vector[i] == -2)
        {
            trend = recognise_bi(nDataLen, high, low, options);
        }
        else if (sig_vector[i] == -3)
        {
            trend = recognise_duan(nDataLen, sig_vector, high, low);
        }
        else if (sig_vector[i] == -4 || sig_vector[i] == -5)
        {
            trend = recognise_trend(nDataLen, sig_vector, high, low);
        }
    }
    std::vector<Pivot> ZhongShuList = recognise_pivots(nDataLen, trend, sig_vector, high, low, options);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        for (int j = ZhongShuOne.start; j <= ZhongShuOne.end; j++)
        {
            pData->m_pResultBuf[j] = ZhongShuOne.dd;
        }
    }
    return 0;
}

int WINAPI ZSSEVAR(CALCINFO *pData)
{
    int nDataLen = pData->m_nNumData;
    if (nDataLen == 0)
        return 0;
    std::vector<float> sig_vector(nDataLen);
    std::vector<float> high(nDataLen);
    std::vector<float> low(nDataLen);
    for (int i = 0; i < nDataLen; i++)
    {
        sig_vector[i] = pData->m_pfParam1[i];
        high[i] = pData->m_pData[i].m_fHigh;
        low[i] = pData->m_pData[i].m_fLow;
        pData->m_pResultBuf[i] = 0;
    }
    ChanOptions options;
    if (pData->m_pfParam2)
    {
        // 参数2是笔控制参数
        int option = static_cast<int>(*pData->m_pfParam2);
        // 4K笔还是5K笔还是大笔
        options.bi_mode = option / 10 % 10;
        // 是否15K后允许次高次低成笔
        options.force_wave_stick_count = option / 100 % 100;
        // 是否合并未完备的笔
        options.merge_non_complehensive_wave = option / 10000 % 10;
    }
    if (pData->m_pfParam4)
    {
        int option = static_cast<int>(*pData->m_pfParam4);
        options.allow_pivot_across = option % 10;
    }
    std::vector<float> trend = std::vector<float>(nDataLen, 0);
    for (size_t i = 0; i < sig_vector.size(); i++)
    {
        if (sig_vector[i] == -2)
        {
            trend = recognise_bi(nDataLen, high, low, options);
        }
        else if (sig_vector[i] == -3)
        {
            trend = recognise_duan(nDataLen, sig_vector, high, low);
        }
        else if (sig_vector[i] == -4 || sig_vector[i] == -5)
        {
            trend = recognise_trend(nDataLen, sig_vector, high, low);
        }
    }
    std::vector<Pivot> ZhongShuList = recognise_pivots(nDataLen, trend, sig_vector, high, low, options);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        pData->m_pResultBuf[ZhongShuOne.start] = 1;
        pData->m_pResultBuf[ZhongShuOne.end] = 2;
    }
    return 0;
}

// 中枢方向
int WINAPI ZSFXVAR(CALCINFO *pData)
{
    int nDataLen = pData->m_nNumData;
    if (nDataLen == 0)
        return 0;
    std::vector<float> sig_vector(nDataLen);
    std::vector<float> high(nDataLen);
    std::vector<float> low(nDataLen);
    for (int i = 0; i < nDataLen; i++)
    {
        sig_vector[i] = pData->m_pfParam1[i];
        high[i] = pData->m_pData[i].m_fHigh;
        low[i] = pData->m_pData[i].m_fLow;
        pData->m_pResultBuf[i] = 0;
    }
    ChanOptions options;
    if (pData->m_pfParam2)
    {
        // 参数2是笔控制参数
        int option = static_cast<int>(*pData->m_pfParam2);
        // 4K笔还是5K笔还是大笔
        options.bi_mode = option / 10 % 10;
        // 是否15K成后允许次高次次低成笔
        options.force_wave_stick_count = option / 100 % 100;
        // 是否合并未完备的笔
        options.merge_non_complehensive_wave = option / 10000 % 10;
    }
    if (pData->m_pfParam4)
    {
        int option = static_cast<int>(*pData->m_pfParam4);
        options.allow_pivot_across = option % 10;
    }
    std::vector<float> trend = std::vector<float>(nDataLen, 0);
    for (size_t i = 0; i < sig_vector.size(); i++)
    {
        if (sig_vector[i] == -2)
        {
            trend = recognise_bi(nDataLen, high, low, options);
        }
        else if (sig_vector[i] == -3)
        {
            trend = recognise_duan(nDataLen, sig_vector, high, low);
        }
        else if (sig_vector[i] == -4 || sig_vector[i] == -5)
        {
            trend = recognise_trend(nDataLen, sig_vector, high, low);
        }
    }
    std::vector<Pivot> ZhongShuList = recognise_pivots(nDataLen, trend, sig_vector, high, low, options);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        for (int j = ZhongShuOne.start; j <= ZhongShuOne.end; j++)
        {
            pData->m_pResultBuf[j] = (float)ZhongShuOne.direction;
        }
    }
    return 0;
}

// 中枢个数
int WINAPI ZSGSVAR(CALCINFO *pData)
{
    int nDataLen = pData->m_nNumData;
    if (nDataLen == 0)
        return 0;
    std::vector<float> sig_vector(nDataLen);
    std::vector<float> high(nDataLen);
    std::vector<float> low(nDataLen);
    for (int i = 0; i < nDataLen; i++)
    {
        sig_vector[i] = pData->m_pfParam1[i];
        high[i] = pData->m_pData[i].m_fHigh;
        low[i] = pData->m_pData[i].m_fLow;
        pData->m_pResultBuf[i] = 0;
    }
    ChanOptions options;
    if (pData->m_pfParam2)
    {
        // 参数2是笔控制参数
        int option = static_cast<int>(*pData->m_pfParam2);
        // 4K笔还是5K笔还是大笔
        options.bi_mode = option / 10 % 10;
        // 是否15K后允许次高次低成笔
        options.force_wave_stick_count = option / 100 % 100;
        // 是否合并未完备的笔
        options.merge_non_complehensive_wave = option / 10000 % 10;
    }
    if (pData->m_pfParam4)
    {
        int option = static_cast<int>(*pData->m_pfParam4);
        options.allow_pivot_across = option % 10;
    }
    std::vector<float> trend = std::vector<float>(nDataLen, 0);
    for (size_t i = 0; i < sig_vector.size(); i++)
    {
        if (sig_vector[i] == -2)
        {
            trend = recognise_bi(nDataLen, high, low, options);
        }
        else if (sig_vector[i] == -3)
        {
            trend = recognise_duan(nDataLen, sig_vector, high, low);
        }
        else if (sig_vector[i] == -4 || sig_vector[i] == -5)
        {
            trend = recognise_trend(nDataLen, sig_vector, high, low);
        }
    }
    std::vector<Pivot> ZhongShuList = recognise_pivots(nDataLen, trend, sig_vector, high, low, options);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        float c = 1;
        for (int j = static_cast<int>(i) - 1; j >= 0; j--)
        {
            if (ZhongShuList.at(j).direction == ZhongShuList.at(i).direction)
            {
                c++;
            }
            else
            {
                break;
            }
        }
        for (int j = ZhongShuOne.start; j <= ZhongShuOne.end; j++)
        {
            pData->m_pResultBuf[j] = c;
        }
    }
    return 0;
}

//=============================================================================
// FQCHAN 通用：缠论笔输出（MT5/Python 等可直接调）
//=============================================================================
void WINAPI FQ_BI(int count, double *out, const double *high, const double *low, int bi_mode)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(double));

    // 显式转换 double* → float* vector
    std::vector<float> h(count);
    std::vector<float> l(count);
    for(int i = 0; i < count; i++) {
        h[i] = static_cast<float>(high[i]);
        l[i] = static_cast<float>(low[i]);
    }

    ChanOptions options;
    options.bi_mode = bi_mode;
    std::vector<float> bi = recognise_bi(count, h, l, options);
    for (size_t i = 0; i < bi.size(); i++)
    {
        out[i] = static_cast<double>(bi[i]);
    }
}

//=============================================================================
// FQCHAN 通用：缠论段输出（MT5/Python 等可直接调）
//=============================================================================
void WINAPI FQ_DUAN(int count, double *out, const double *high, const double *low, const double *bi)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(double));

    // 显式转换 double* → float* vector
    std::vector<float> h(count);
    std::vector<float> l(count);
    std::vector<float> b(count);
    for(int i = 0; i < count; i++) {
        h[i] = static_cast<float>(high[i]);
        l[i] = static_cast<float>(low[i]);
        b[i] = static_cast<float>(bi[i]);
    }

    std::vector<float> duan = recognise_duan(count, b, h, l);

    // DLL 返回原始信号值，不做价格转换（由 MQL5 端处理）
    for (size_t i = 0; i < duan.size(); i++)
    {
        out[i] = static_cast<double>(duan[i]);
    }
}

//=============================================================================
// FQCHAN 通用：缠论中枢高点输出（MT5/Python 等可直接调）
//=============================================================================
void WINAPI FQ_ZSZG(int count, double *out, const double *duan, const double *bi, const double *high, const double *low, int bi_mode)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(double));

    // 显式转换 double* → float* vector
    std::vector<float> h(count);
    std::vector<float> l(count);
    std::vector<float> d(count);
    std::vector<float> b(count);
    for(int i = 0; i < count; i++) {
        h[i] = static_cast<float>(high[i]);
        l[i] = static_cast<float>(low[i]);
        d[i] = static_cast<float>(duan[i]);
        b[i] = static_cast<float>(bi[i]);
    }

    ChanOptions options;
    options.bi_mode = bi_mode;

    // 识别中枢（需要段和笔）
    std::vector<Pivot> pivots = recognise_pivots(count, d, b, h, l, options);

    // 输出中枢高点
    for (size_t i = 0; i < pivots.size(); i++)
    {
        Pivot e = pivots.at(i);
        for (int j = e.start; j <= e.end; j++)
        {
            out[j] = e.zg;
        }
    }
}

//=============================================================================
// FQCHAN 通用：缠论中枢低点输出（MT5/Python 等可直接调）
//=============================================================================
void WINAPI FQ_ZSZD(int count, double *out, const double *duan, const double *bi, const double *high, const double *low, int bi_mode)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(double));

    // 显式转换 double* → float* vector
    std::vector<float> h(count);
    std::vector<float> l(count);
    std::vector<float> d(count);
    std::vector<float> b(count);
    for(int i = 0; i < count; i++) {
        h[i] = static_cast<float>(high[i]);
        l[i] = static_cast<float>(low[i]);
        d[i] = static_cast<float>(duan[i]);
        b[i] = static_cast<float>(bi[i]);
    }

    ChanOptions options;
    options.bi_mode = bi_mode;

    // 识别中枢（需要段和笔）
    std::vector<Pivot> pivots = recognise_pivots(count, d, b, h, l, options);

    // 输出中枢低点
    for (size_t i = 0; i < pivots.size(); i++)
    {
        Pivot e = pivots.at(i);
        for (int j = e.start; j <= e.end; j++)
        {
            out[j] = e.zd;
        }
    }
}

//=============================================================================
// FQCHAN 通用：缠论中枢起止点输出（MT5/Python 等可直接调）
// 起点输出 1，终点输出 2
//=============================================================================
void WINAPI FQ_ZSSE(int count, double *out, const double *duan, const double *bi, const double *high, const double *low, int bi_mode)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(double));

    // 显式转换 double* → float* vector
    std::vector<float> h(count);
    std::vector<float> l(count);
    std::vector<float> d(count);
    std::vector<float> b(count);
    for(int i = 0; i < count; i++) {
        h[i] = static_cast<float>(high[i]);
        l[i] = static_cast<float>(low[i]);
        d[i] = static_cast<float>(duan[i]);
        b[i] = static_cast<float>(bi[i]);
    }

    ChanOptions options;
    options.bi_mode = bi_mode;

    // 识别中枢（需要段和笔）
    std::vector<Pivot> pivots = recognise_pivots(count, d, b, h, l, options);

    // 输出中枢起止点：起点=1，终点=2
    for (size_t i = 0; i < pivots.size(); i++)
    {
        Pivot e = pivots.at(i);
        out[e.start] = 1;  // 中枢起点
        out[e.end] = 2;   // 中枢终点
    }
}

//=============================================================================
// FQCHAN 通用：缠论走势类型输出（MT5/Python 等可直接调）
//=============================================================================
void WINAPI FQ_TREND(int count, double *out, const double *duan, const double *high, const double *low)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(double));

    // 显式转换 double* → float* vector
    std::vector<float> h(count);
    std::vector<float> l(count);
    std::vector<float> d(count);
    for(int i = 0; i < count; i++) {
        h[i] = static_cast<float>(high[i]);
        l[i] = static_cast<float>(low[i]);
        d[i] = static_cast<float>(duan[i]);
    }

    // 识别走势类型（基于段信号）
    std::vector<float> trend = recognise_trend(count, d, h, l);

    // 输出走势信号（1=高点，-1=低点，-5=无效标记）
    for (size_t i = 0; i < trend.size(); i++)
    {
        out[i] = static_cast<double>(trend[i]);
    }
}
