#include "stdafx.h"
#include "TCalcFuncSets.h"
#include "Comm.h"

//=============================================================================
// 输出函数1号：输出分型笔端点
//=============================================================================
void Func1(int count, float *out, float *high, float *low, float *ignore) {
    std::vector<float> h(high, high+count);
    std::vector<float> l(low, low+count);
    std::vector<float> bi = recognise_swing(count, h, l);
    for (size_t i = 0; i < bi.size(); i++)
    {
        out[i] = bi[i];
    }
}

//=============================================================================
// 输出函数2号：输出笔顶底端点
//=============================================================================
void Func2(int count, float *out, float *high, float *low, float *ignore)
{
    for (int i = 0; i < count; i++)
    {
        out[i] = 0;
    }
    std::vector<float> h(high, high+count);
    std::vector<float> l(low, low+count);
    BiData bi_data = BiData(count, h, l);
    std::vector<Bi> bi_list = bi_data.get_bi_list();
    for (size_t i = 0; i < bi_list.size(); i++)
    {
        Bi& bi = bi_list.at(i);
        if (bi.direction == 1)
        {
            if (i == 0) {
                out[bi.start] = -1;
            }
            out[bi.end] = 1;
        }
        else
        {
            if (i == 0) {
                out[bi.start] = 1;
            }
            out[bi.end] = -1;
        }
    }
}

//=============================================================================
// 输出函数3号：输出段的端点标准画法
//=============================================================================
void Func3(int count, float *duan, float *bi, float *high, float *low)
{
    for (int i = 0; i < count; i++)
    {
        duan[i] = 0;
    }
    std::vector<float> b(bi, bi+count);
    std::vector<float> h(high, high+count);
    std::vector<float> l(low, low+count);
    DuanData duan_data = DuanData(count, b, h, l);
    std::vector<Duan> duan_list = duan_data.get_duan_list();

    for (size_t i = 0; i < duan_list.size(); i++)
    {
        Duan& d = duan_list.at(i);
        if (d.direction == 1)
        {
            duan[d.start] = -1;
            duan[d.end] = 1;
        }
        else
        {
            duan[d.start] = 1;
            duan[d.end] = -1;
        }
    }
}

//=============================================================================
// 输出函数4号：输出段的端点标准画法
//=============================================================================
void Func4(int count, float *duan, float *bi, float *high, float *low)
{
    for (int i = 0; i < count; i++)
    {
        duan[i] = 0;
    }
    std::vector<float> b(bi, bi+count);
    std::vector<float> h(high, high+count);
    std::vector<float> l(low, low+count);
    DuanData duan_data = DuanData(count, b, h, l);
    std::vector<Duan> duan_list = duan_data.get_duan_list();

    for (size_t i = 0; i < duan_list.size(); i++)
    {
        Duan& d = duan_list.at(i);
        if (d.direction == 1)
        {
            duan[d.start] = -1;
            duan[d.end] = 1;
        }
        else
        {
            duan[d.start] = 1;
            duan[d.end] = -1;
        }
    }
}

//=============================================================================
// 输出函数5号：中枢高点（ZG）数据
//=============================================================================
void Func5(int count, float *out, float *bi, float *high, float *low)
{
    std::vector<float> duan(count);
    std::vector<float> b(bi, bi+count);
    std::vector<float> h(high, high+count);
    std::vector<float> l(low, low+count);
    DuanData duan_data = DuanData(count, b, h, l);
    std::vector<Duan> duan_list = duan_data.get_duan_list();
    for (size_t i = 0; i < duan_list.size(); i++)
    {
        Duan& d = duan_list.at(i);
        if (d.direction == 1)
        {
            duan[d.start] = -1;
            duan[d.end] = 1;
        }
        else
        {
            duan[d.start] = 1;
            duan[d.end] = -1;
        }
    }
    PivotData pivot_data = PivotData(count, duan, b, h, l);
    std::vector<Pivot> pivot_list = pivot_data.get_pivot_list();
    for (size_t x = 0; x < pivot_list.size(); x++)
    {
        Pivot& e = pivot_list.at(x);
        for (int y = e.start; y <= e.end; y++)
        {
            out[y] = e.zg;
        }
    }
}

//=============================================================================
// 输出函数6号：中枢高点（GG）数据
//=============================================================================
void Func6(int count, float *out, float *bi, float *high, float *low)
{
    std::vector<float> duan(count);
    std::vector<float> b(bi, bi+count);
    std::vector<float> h(high, high+count);
    std::vector<float> l(low, low+count);
    DuanData duan_data = DuanData(count, b, h, l);
    std::vector<Duan> duan_list = duan_data.get_duan_list();
    for (size_t i = 0; i < duan_list.size(); i++)
    {
        Duan& d = duan_list.at(i);
        if (d.direction == 1)
        {
            duan[d.start] = -1;
            duan[d.end] = 1;
        }
        else
        {
            duan[d.start] = 1;
            duan[d.end] = -1;
        }
    }
    PivotData pivot_data = PivotData(count, duan, b, h, l);
    std::vector<Pivot> pivot_list = pivot_data.get_pivot_list();
    for (size_t x = 0; x < pivot_list.size(); x++)
    {
        Pivot& e = pivot_list.at(x);
        for (int y = e.start; y <= e.end; y++)
        {
            out[y] = e.gg;
        }
    }
}

//=============================================================================
// 输出函数7号：中枢低点（ZD）数据
//=============================================================================
void Func7(int count, float *out, float *bi, float *high, float *low)
{
    std::vector<float> duan(count);
    std::vector<float> b(bi, bi+count);
    std::vector<float> h(high, high+count);
    std::vector<float> l(low, low+count);
    DuanData duan_data = DuanData(count, b, h, l);
    std::vector<Duan> duan_list = duan_data.get_duan_list();
    for (size_t i = 0; i < duan_list.size(); i++)
    {
        Duan& d = duan_list.at(i);
        if (d.direction == 1)
        {
            duan[d.start] = -1;
            duan[d.end] = 1;
        }
        else
        {
            duan[d.start] = 1;
            duan[d.end] = -1;
        }
    }
    PivotData pivot_data = PivotData(count, duan, b, h, l);
    std::vector<Pivot> pivot_list = pivot_data.get_pivot_list();
    for (size_t x = 0; x < pivot_list.size(); x++)
    {
        Pivot& e = pivot_list.at(x);
        for (int y = e.start; y <= e.end; y++)
        {
            out[y] = e.zd;
        }
    }
}

//=============================================================================
// 输出函数8号：中枢低点（DD）数据
//=============================================================================
void Func8(int count, float *out, float *bi, float *high, float *low)
{
    std::vector<float> duan(count);
    std::vector<float> b(bi, bi+count);
    std::vector<float> h(high, high+count);
    std::vector<float> l(low, low+count);
    DuanData duan_data = DuanData(count, b, h, l);
    std::vector<Duan> duan_list = duan_data.get_duan_list();
    for (size_t i = 0; i < duan_list.size(); i++)
    {
        Duan& d = duan_list.at(i);
        if (d.direction == 1)
        {
            duan[d.start] = -1;
            duan[d.end] = 1;
        }
        else
        {
            duan[d.start] = 1;
            duan[d.end] = -1;
        }
    }
    PivotData pivot_data = PivotData(count, duan, b, h, l);
    std::vector<Pivot> pivot_list = pivot_data.get_pivot_list();
    for (size_t x = 0; x < pivot_list.size(); x++)
    {
        Pivot& e = pivot_list.at(x);
        for (int y = e.start; y <= e.end; y++)
        {
            out[y] = e.dd;
        }
    }
}

//=============================================================================
// 输出函数9号：中枢起点、终点信号 1是开始 2是结束
//=============================================================================
void Func9(int count, float *out, float *bi, float *high, float *low)
{
    std::vector<float> duan(count);
    std::vector<float> b(bi, bi+count);
    std::vector<float> h(high, high+count);
    std::vector<float> l(low, low+count);
    DuanData duan_data = DuanData(count, b, h, l);
    std::vector<Duan> duan_list = duan_data.get_duan_list();
    for (size_t i = 0; i < duan_list.size(); i++)
    {
        Duan& d = duan_list.at(i);
        if (d.direction == 1)
        {
            duan[d.start] = -1;
            duan[d.end] = 1;
        }
        else
        {
            duan[d.start] = 1;
            duan[d.end] = -1;
        }
    }
    PivotData pivot_data = PivotData(count, duan, b, h, l);
    std::vector<Pivot> pivot_list = pivot_data.get_pivot_list();
    for (size_t x = 0; x < pivot_list.size(); x++)
    {
        Pivot& e = pivot_list.at(x);
        out[e.start] = 1;
        out[e.end] = 2;
    }
}

//=============================================================================
// 输出函数10号：中枢方向
//=============================================================================
void Func10(int count, float *out, float *bi, float *high, float *low)
{
    std::vector<float> duan(count);
    std::vector<float> b(bi, bi+count);
    std::vector<float> h(high, high+count);
    std::vector<float> l(low, low+count);
    DuanData duan_data = DuanData(count, b, h, l);
    std::vector<Duan> duan_list = duan_data.get_duan_list();
    for (size_t i = 0; i < duan_list.size(); i++)
    {
        Duan& d = duan_list.at(i);
        if (d.direction == 1)
        {
            duan[d.start] = -1;
            duan[d.end] = 1;
        }
        else
        {
            duan[d.start] = 1;
            duan[d.end] = -1;
        }
    }
    PivotData pivot_data = PivotData(count, duan, b, h, l);
    std::vector<Pivot> pivot_list = pivot_data.get_pivot_list();
    for (size_t x = 0; x < pivot_list.size(); x++)
    {
        Pivot& e = pivot_list.at(x);
        for (int y = e.start; y <= e.end; y++)
        {
            out[y] = float(e.direction);
        }
    }
}

//=============================================================================
// 输出函数11号：中枢个数
//=============================================================================
void Func11(int count, float *out, float *bi, float *high, float *low)
{
    std::vector<float> duan(count);
    std::vector<float> b(bi, bi+count);
    std::vector<float> h(high, high+count);
    std::vector<float> l(low, low+count);
    DuanData duan_data = DuanData(count, b, h, l);
    std::vector<Duan> duan_list = duan_data.get_duan_list();
    for (size_t i = 0; i < duan_list.size(); i++)
    {
        Duan& d = duan_list.at(i);
        if (d.direction == 1)
        {
            duan[d.start] = -1;
            duan[d.end] = 1;
        }
        else
        {
            duan[d.start] = 1;
            duan[d.end] = -1;
        }
    }
    PivotData pivot_data = PivotData(count, duan, b, h, l);
    std::vector<Pivot> pivot_list = pivot_data.get_pivot_list();
    for (size_t i = 0; i < pivot_list.size(); i++)
    {
        Pivot& e = pivot_list.at(i);
        float c = 1;
        for (int j = static_cast<int>(i - 1); j >= 0; j--)
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

PluginTCalcFuncInfo g_CalcFuncSets[] =
    {
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
// --- ChanlunX 大智慧输出函数 --- //
int WINAPI RUNMODE()
{
    return 0;
}

int WINAPI BI1(CALCINFO *pData)
{
    int nDataLen = pData->m_nNumData;
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

int WINAPI BI2(CALCINFO *pData)
{
    int nDataLen = pData->m_nNumData;
    std::vector<float> high(nDataLen);
    std::vector<float> low(nDataLen);
    for (int i = 0; i < nDataLen; i++)
    {
        high[i] = pData->m_pData[i].m_fHigh;
        low[i] = pData->m_pData[i].m_fLow;
        pData->m_pResultBuf[i] = 0;
    }
    std::vector<float> out = recognise_bi(nDataLen, high, low);
    for (int i = 0; i < nDataLen; i++)
    {
        pData->m_pResultBuf[i] = out[i];
    }
    return 0;
}

int WINAPI DUAN1VAR(CALCINFO *pData)
{
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

int WINAPI DUAN2VAR(CALCINFO *pData)
{
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

int WINAPI ZSZGVAR(CALCINFO *pData)
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
    std::vector<float> duan = recognise_duan(nDataLen, bi, high, low);
    std::vector<Pivot> ZhongShuList = recognise_pivots(nDataLen, duan, bi, high, low);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        for (int j = ZhongShuOne.start + 1; j <= ZhongShuOne.end - 1; j++)
        {
            pData->m_pResultBuf[j] = ZhongShuOne.zg;
        }
    }
    return 0;
}

int WINAPI ZSZDVAR(CALCINFO *pData)
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
    std::vector<float> duan = recognise_duan(nDataLen, bi, high, low);
    std::vector<Pivot> ZhongShuList = recognise_pivots(nDataLen, duan, bi, high, low);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        for (int j = ZhongShuOne.start + 1; j <= ZhongShuOne.end - 1; j++)
        {
            pData->m_pResultBuf[j] = ZhongShuOne.zd;
        }
    }
    return 0;
}

int WINAPI ZSSEVAR(CALCINFO *pData)
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
    std::vector<float> duan = recognise_duan(nDataLen, bi, high, low);
    std::vector<Pivot> ZhongShuList = recognise_pivots(nDataLen, duan, bi, high, low);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        pData->m_pResultBuf[ZhongShuOne.start + 1] = 1;
        pData->m_pResultBuf[ZhongShuOne.end - 1] = 2;
    }
    return 0;
}

int WINAPI ZSFXVAR(CALCINFO *pData)
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
    std::vector<float> duan = recognise_duan(nDataLen, bi, high, low);
    std::vector<Pivot> ZhongShuList = recognise_pivots(nDataLen, duan, bi, high, low);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        for (int j = ZhongShuOne.start + 1; j <= ZhongShuOne.end - 1; j++)
        {
            pData->m_pResultBuf[j] = (float) ZhongShuOne.direction;
        }
    }
    return 0;
}

int WINAPI ZSGSVAR(CALCINFO *pData)
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
    std::vector<float> duan = recognise_duan(nDataLen, bi, high, low);
    std::vector<Pivot> ZhongShuList = recognise_pivots(nDataLen, duan, bi, high, low);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        float c = 1;
        for (int j = static_cast<int>(i - 1); j >= 0; j--)
        {
            if (ZhongShuList.at(j).direction = ZhongShuList.at(i).direction)
            {
                c++;
            }
            else
            {
                break;
            }
        }
        for (int j = ZhongShuOne.start + 1; j <= ZhongShuOne.end - 1; j++)
        {
            pData->m_pResultBuf[j] = c;
        }
    }
    return 0;
}
