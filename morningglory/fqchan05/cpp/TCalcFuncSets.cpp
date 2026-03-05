#include "stdafx.h"
#include "TCalcFuncSets.h"
#include "Chan.h"
#include "Log.h"
#include <Poco/AccessExpireCache.h>

//=============================================================================
// 输出函数1号：设置缠参数
//=============================================================================
void Func1(int count, float *out, float *pIn1, float *pIn2, float *pIn3)
{
    ChanProxy &chan = ChanProxy::GetInstance();
    chan.Reset();
}

//=============================================================================
// 输出函数2号：设置缠参数
//=============================================================================
void Func2(int count, float *out, float *pIn1, float *pIn2, float *pIn3)
{
    ChanProxy &chan = ChanProxy::GetInstance();
    ParamType paramType = static_cast<ParamType>(static_cast<int>(pIn2[0]));
    if (paramType == ParamType::HIGH) // 最高价
    {
        std::vector<float> highs(pIn1, pIn1 + count);
        chan.SetHighs(highs);
    }
    else if (paramType == ParamType::LOW) // 最低价
    {
        std::vector<float> lows(pIn1, pIn1 + count);
        chan.SetLows(lows);
    }
    else if (paramType == ParamType::OPEN) // 开盘价
    {
        std::vector<float> opens(pIn1, pIn1 + count);
        chan.SetOpens(opens);
    }
    else if (paramType == ParamType::CLOSE) // 收盘价
    {
        std::vector<float> closes(pIn1, pIn1 + count);
        chan.SetCloses(closes);
    }
    else if (paramType == ParamType::VOLUME) // 成交量
    {
        std::vector<float> volumes(pIn1, pIn1 + count);
        chan.SetVolumes(volumes);
    }
}

//=============================================================================
// 输出函数3号：缠论数据计算
//=============================================================================
void Func3(int count, float *out, float *pIn1, float *pIn2, float *pIn3)
{
    ChanProxy &chan = ChanProxy::GetInstance();
    for (int i = 0; i < count; i++)
    {
        chan.Proceed();
    }
}

//=============================================================================
// 输出函数4号：输出
//=============================================================================
void Func4(int count, float *out, float *pIn1, float *pIn2, float *pIn3)
{
    memset(out, 0, count);
    ChanProxy &chan = ChanProxy::GetInstance();
    ParamType paramType = static_cast<ParamType>(static_cast<int>(pIn1[0]));
    if (paramType == ParamType::SWING) // 分型笔数据
    {
    }
    else if (paramType == ParamType::WAVE) // 笔数据
    {
        std::vector<Wave> &waves = chan.GetWaves();
        for (size_t i = 0; i < waves.size(); i++)
        {
            Wave &wave = waves.at(i);
            if (wave.direction == DirectionType::UP)
            {
                if (i == 0)
                {
                    out[wave.startKeyBar.pos] = -1;
                }
                out[wave.endKeyBar.pos] = 1;
            }
            else
            {
                if (i == 0)
                {
                    out[wave.startKeyBar.pos] = 1;
                }
                out[wave.endKeyBar.pos] = -1;
            }
        }
    }
}

PluginTCalcFuncInfo g_CalcFuncSets[] = {
    {1, (pPluginFUNC)&Func1},
    {2, (pPluginFUNC)&Func2},
    {3, (pPluginFUNC)&Func3},
    {4, (pPluginFUNC)&Func4},
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

int WINAPI RESET(CALCINFO *pData)
{
    ChanProxy &chan = ChanProxy::GetInstance();
    chan.Reset();
    return 0;
}

int WINAPI SETPARAMVAR(CALCINFO *pData)
{
    if (pData->m_nParam1Start >= 0 && pData->m_pfParam1 != NULL && pData->m_pfParam2 != NULL)
    {
        int nDataLen = pData->m_nNumData;
        ChanProxy &chan = ChanProxy::GetInstance();
        ParamType paramType = static_cast<ParamType>(static_cast<int>(*pData->m_pfParam2));
        std::vector<float> params(pData->m_pfParam1, pData->m_pfParam1 + nDataLen);
        if (paramType == ParamType::HIGH) // 最高价
        {
            std::vector<float> highs(pData->m_pfParam1, pData->m_pfParam1 + nDataLen);
            chan.SetHighs(highs);
        }
        else if (paramType == ParamType::LOW) // 最低价
        {
            std::vector<float> lows(pData->m_pfParam1, pData->m_pfParam1 + nDataLen);
            chan.SetLows(lows);
        }
        else if (paramType == ParamType::OPEN) // 开盘价
        {
            std::vector<float> opens(pData->m_pfParam1, pData->m_pfParam1 + nDataLen);
            chan.SetOpens(opens);
        }
        else if (paramType == ParamType::CLOSE) // 收盘价
        {
            std::vector<float> closes(pData->m_pfParam1, pData->m_pfParam1 + nDataLen);
            chan.SetCloses(closes);
        }
        else if (paramType == ParamType::VOLUME) // 成交量
        {
            std::vector<float> volumes(pData->m_pfParam1, pData->m_pfParam1 + nDataLen);
            chan.SetVolumes(volumes);
        }
        return 0;
    }
    return -1;
}

int WINAPI CALC(CALCINFO *pData)
{
    int nDataLen = pData->m_nNumData;
    ChanProxy &chan = ChanProxy::GetInstance();
    for (int i = 0; i < nDataLen; i++)
    {
        chan.Proceed();
    }
    return 0;
}

int WINAPI OUTPUT(CALCINFO *pData)
{
    if (pData->m_nParam1Start < 0 && pData->m_pfParam1 != NULL)
    {
        int nDataLen = pData->m_nNumData;
        memset(pData->m_pResultBuf, 0, nDataLen);
        ChanProxy &chan = ChanProxy::GetInstance();
        ParamType paramType = static_cast<ParamType>(static_cast<int>(*pData->m_pfParam1));
        if (paramType == ParamType::SWING) // 分型笔数据
        {
        }
        else if (paramType == ParamType::WAVE) // 笔数据
        {
            std::vector<Wave> &waves = chan.GetWaves();
            for (size_t i = 0; i < waves.size(); i++)
            {
                Wave &wave = waves.at(i);
                if (wave.direction == DirectionType::UP)
                {
                    if (i == 0)
                    {
                        pData->m_pResultBuf[wave.startKeyBar.pos] = -1;
                    }
                    pData->m_pResultBuf[wave.endKeyBar.pos] = 1;
                }
                else
                {
                    if (i == 0)
                    {
                        pData->m_pResultBuf[wave.startKeyBar.pos] = 1;
                    }
                    pData->m_pResultBuf[wave.endKeyBar.pos] = -1;
                }
            }
        }
        return 0;
    }
    return -1;
}
