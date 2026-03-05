#include "Main.h"
#include <iostream>
#include <fstream>

using namespace std;

//定义DLL程序的入口函数
BOOL APIENTRY DllMain(HANDLE hModule, DWORD ul_reason_for_call, LPVOID lpReserved)
{
    switch (ul_reason_for_call)
    {
    case DLL_PROCESS_ATTACH:
    case DLL_THREAD_ATTACH:
    case DLL_THREAD_DETACH:
    case DLL_PROCESS_DETACH:
        break;
    }
    return TRUE;
}

//=============================================================================
// 输出函数1号：输出分型笔端点
//=============================================================================
void Func1(int nCount, float *pOut, float *pHigh, float *pLow, float *pIgnore)
{
    std::vector<float> high(pHigh, pHigh + nCount);
    std::vector<float> low(pLow, pLow + nCount);
    std::vector<float> out = Bi1(nCount, high, low);
    memset(pOut, 0, nCount);
    for (int i = 0; i < nCount; i++)
    {
        pOut[i] = out[i];
    }
}

//=============================================================================
// 输出函数2号：输出笔顶底端点
//=============================================================================
void Func2(int nCount, float *pOut, float *pHigh, float *pLow, float *pIgnore)
{
    std::vector<float> high(pHigh, pHigh + nCount);
    std::vector<float> low(pLow, pLow + nCount);
    std::vector<float> out = Bi2(nCount, high, low);
    memset(pOut, 0, nCount);
    for (int i = 0; i < nCount; i++)
    {
        pOut[i] = out[i];
    }
}

//=============================================================================
// 输出函数3号：输出段的端点标准画法
//=============================================================================
void Func3(int nCount, float *pOut, float *pIn, float *pHigh, float *pLow)
{
    std::vector<float> bi(pIn, pIn + nCount);
    std::vector<float> high(pHigh, pHigh + nCount);
    std::vector<float> low(pLow, pLow + nCount);
    std::vector<float> out = Duan1(nCount, bi, high, low);
    memset(pOut, 0, nCount);
    for (int i = 0; i < nCount; i++)
    {
        pOut[i] = out[i];
    }
}

//=============================================================================
// 输出函数4号：输出段的端点1+1终结画法
//=============================================================================
void Func4(int nCount, float *pOut, float *pIn, float *pHigh, float *pLow)
{
    std::vector<float> bi(pIn, pIn + nCount);
    std::vector<float> high(pHigh, pHigh + nCount);
    std::vector<float> low(pLow, pLow + nCount);
    std::vector<float> out = Duan2(nCount, bi, high, low);
    memset(pOut, 0, nCount);
    for (int i = 0; i < nCount; i++)
    {
        pOut[i] = out[i];
    }
}

//=============================================================================
// 输出函数5号：中枢高点数据
//=============================================================================
void Func5(int nCount, float *pOut, float *pIn, float *pHigh, float *pLow)
{
    std::vector<float> bi(pIn, pIn + nCount);
    std::vector<float> high(pHigh, pHigh + nCount);
    std::vector<float> low(pLow, pLow + nCount);
    std::vector<Pivot> ZhongShuList = ZS(nCount, bi, high, low);
    memset(pOut, 0, nCount);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        for (int j = ZhongShuOne.start; j <= ZhongShuOne.end; j++)
        {
            pOut[j] = ZhongShuOne.zg;
        }
    }
}

//=============================================================================
// 输出函数6号：中枢高点（GG）数据
//=============================================================================
void Func6(int nCount, float *pOut, float *pIn, float *pHigh, float *pLow)
{
    std::vector<float> bi(pIn, pIn + nCount);
    std::vector<float> high(pHigh, pHigh + nCount);
    std::vector<float> low(pLow, pLow + nCount);
    std::vector<Pivot> ZhongShuList = ZS(nCount, bi, high, low);
    memset(pOut, 0, nCount);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        for (int j = ZhongShuOne.start; j <= ZhongShuOne.end; j++)
        {
            pOut[j] = ZhongShuOne.gg;
        }
    }
}

//=============================================================================
// 输出函数7号：中枢低点数据
//=============================================================================
void Func7(int nCount, float *pOut, float *pIn, float *pHigh, float *pLow)
{
    std::vector<float> bi(pIn, pIn + nCount);
    std::vector<float> high(pHigh, pHigh + nCount);
    std::vector<float> low(pLow, pLow + nCount);
    std::vector<Pivot> ZhongShuList = ZS(nCount, bi, high, low);
    memset(pOut, 0, nCount);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        for (int j = ZhongShuOne.start; j <= ZhongShuOne.end; j++)
        {
            pOut[j] = ZhongShuOne.zd;
        }
    }
}

//=============================================================================
// 输出函数8号：中枢低点（DD）数据
//=============================================================================
void Func8(int nCount, float *pOut, float *pIn, float *pHigh, float *pLow)
{
    std::vector<float> bi(pIn, pIn + nCount);
    std::vector<float> high(pHigh, pHigh + nCount);
    std::vector<float> low(pLow, pLow + nCount);
    std::vector<Pivot> ZhongShuList = ZS(nCount, bi, high, low);
    memset(pOut, 0, nCount);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        for (int j = ZhongShuOne.start; j <= ZhongShuOne.end; j++)
        {
            pOut[j] = ZhongShuOne.dd;
        }
    }
}

//=============================================================================
// 输出函数9号：中枢起点、终点信号 1是开始 2是结束
//=============================================================================
void Func9(int nCount, float *pOut, float *pIn, float *pHigh, float *pLow)
{
    std::vector<float> bi(pIn, pIn + nCount);
    std::vector<float> high(pHigh, pHigh + nCount);
    std::vector<float> low(pLow, pLow + nCount);
    std::vector<Pivot> ZhongShuList = ZS(nCount, bi, high, low);
    memset(pOut, 0, nCount);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        pOut[ZhongShuOne.start] = 1;
        pOut[ZhongShuOne.end] = 2;
    }
}

//=============================================================================
// 输出函数10号：中枢方向
//=============================================================================
void Func10(int nCount, float *pOut, float *pIn, float *pHigh, float *pLow)
{
    std::vector<float> bi(pIn, pIn + nCount);
    std::vector<float> high(pHigh, pHigh + nCount);
    std::vector<float> low(pLow, pLow + nCount);
    std::vector<Pivot> ZhongShuList = ZS(nCount, bi, high, low);
    memset(pOut, 0, nCount);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        for (int j = ZhongShuOne.start; j <= ZhongShuOne.end; j++)
        {
            pOut[j] = (float)ZhongShuOne.direction;
        }
    }
}

//=============================================================================
// 输出函数11号：同方向的第几个中枢
//=============================================================================
void Func11(int nCount, float *pOut, float *pIn, float *pHigh, float *pLow)
{
    std::vector<float> bi(pIn, pIn + nCount);
    std::vector<float> high(pHigh, pHigh + nCount);
    std::vector<float> low(pLow, pLow + nCount);
    std::vector<Pivot> ZhongShuList = ZS(nCount, bi, high, low);
    memset(pOut, 0, nCount);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        float c = 1;
        for (int j = static_cast<int>(i - 1); j >= 0; j--)
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
            pOut[j] = c;
        }
    }
}

static PluginTCalcFuncInfo Info[] =
    {
        {1, &Func1},
        {2, &Func2},
        {3, &Func3},
        {4, &Func4},
        {5, &Func5},
        {6, &Func6},
        {7, &Func7},
        {8, &Func8},
        {9, &Func9},
        {10, &Func10},
        {11, &Func11},
        {0, NULL}};

BOOL RegisterTdxFunc(PluginTCalcFuncInfo **pInfo)
{
    if (*pInfo == NULL)
    {
        *pInfo = Info;

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
    std::vector<float> out = Bi1(nDataLen, high, low);
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
    std::vector<float> out = Bi2(nDataLen, high, low);
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
        std::vector<float> out = Duan1(nDataLen, bi, high, low);
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
        std::vector<float> out = Duan2(nDataLen, bi, high, low);
        for (int i = 0; i < nDataLen; i++)
        {
            pData->m_pResultBuf[i] = out[i];
        }
        return 0;
    }
    return -1;
}

// --- 8 中枢高点
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
    std::vector<Pivot> ZhongShuList = ZS(nDataLen, bi, high, low);
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

// --- 9 中枢低点
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
    std::vector<Pivot> ZhongShuList = ZS(nDataLen, bi, high, low);
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

// --- 10 中枢开始结束
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
    std::vector<Pivot> ZhongShuList = ZS(nDataLen, bi, high, low);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        pData->m_pResultBuf[ZhongShuOne.start + 1] = 1;
        pData->m_pResultBuf[ZhongShuOne.end - 1] = 2;
    }
    return 0;
}

// --- 11 中枢方向
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
    std::vector<Pivot> ZhongShuList = ZS(nDataLen, bi, high, low);
    for (size_t i = 0; i < ZhongShuList.size(); i++)
    {
        Pivot ZhongShuOne = ZhongShuList.at(i);
        for (int j = ZhongShuOne.start + 1; j <= ZhongShuOne.end - 1; j++)
        {
            pData->m_pResultBuf[j] = ZhongShuOne.direction;
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
    std::vector<Pivot> ZhongShuList = ZS(nDataLen, bi, high, low);
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
// --- ChanlunX 大智慧输出函数 --- //
