#include "stdafx.h"
#include "TCalcFuncSets.h"
#include "copilot/copilot.h"
#include "common/log.h"
#include "func_set.h"
#include <thread>

//=============================================================================
// 输出函数1号：重置
//=============================================================================
void Func1(int count, float *out, float *pIn1, float *pIn2, float *pIn3)
{
    CopilotProxy &copilotProxy = CopilotProxy::GetInstance();
    copilotProxy.Reset();
}

//=============================================================================
// 输出函数2号：设置参数
//=============================================================================
void Func2(int count, float *out, float *pIn1, float *pIn2, float *pIn3)
{
    if (count == 0) return;
    CopilotProxy &copilotProxy = CopilotProxy::GetInstance();
    ParamType paramType = static_cast<ParamType>(static_cast<int>(pIn1[0]));
    std::vector<float> params(pIn2, pIn2 + count);
    copilotProxy.SetParam(paramType, params);
}

//=============================================================================
// 输出函数3号：计算信号-公共版本
//=============================================================================
void Func3(int count, float *out, float *high, float *low, float *close)
{
    if (count == 0) return;
    memset(out, 0, count * sizeof(float));
    CopilotProxy &copilotProxy = CopilotProxy::GetInstance();

    copilotProxy.SetParam(ParamType::PARAM_HIGH, std::vector<float>(high, high + count));
    copilotProxy.SetParam(ParamType::PARAM_LOW, std::vector<float>(low, low + count));
    copilotProxy.SetParam(ParamType::PARAM_CLOSE, std::vector<float>(close, close + count));

    std::vector<float> modelOpts = copilotProxy.ExistParam(ParamType::PARAM_MODEL_OPT) ? copilotProxy.GetParam(ParamType::PARAM_MODEL_OPT) : std::vector<float>();
    auto modelOpt = CalcType::CALC_S0001;
    if (modelOpts.size() > 0)
    {
        int modelOptInt = static_cast<int>(modelOpts[0]) % 10000;
        if (calcTypeMap.find(modelOptInt) != calcTypeMap.end())
        {
            modelOpt = calcTypeMap[modelOptInt];
        }  
    }

    std::vector<int> result = copilotProxy.Calc(modelOpt);
    int length = (std::min)(count, static_cast<int>(result.size()));
    for (int i = 0; i < length; i++)
    {
        int entrypointValue = static_cast<int>(result[i]);
        if (entrypointValue > 0)
        {
            out[i] = static_cast<float>(entrypointValue);
        }
        else if (entrypointValue < 0)
        {
            out[i] = static_cast<float>(entrypointValue);
        }
        else
        {
            out[i] = 0.0;
        }
    }
    copilotProxy.Reset();
}

//=============================================================================
// 输出函数4号：计算信号-定制版本
//=============================================================================
void Func4(int count, float *out_values, float *high_values, float *low_values, float *close_values)
{
    if (count == 0) return;
    memset(out_values, 0, count * sizeof(float));
    CopilotProxy &copilotProxy = CopilotProxy::GetInstance();

    copilotProxy.SetParam(ParamType::PARAM_HIGH, std::vector<float>(high_values, high_values + count));
    copilotProxy.SetParam(ParamType::PARAM_LOW, std::vector<float>(low_values, low_values + count));
    copilotProxy.SetParam(ParamType::PARAM_CLOSE, std::vector<float>(close_values, close_values + count));

    std::vector<float> modelOpts = copilotProxy.ExistParam(ParamType::PARAM_MODEL_OPT) ? copilotProxy.GetParam(ParamType::PARAM_MODEL_OPT) : std::vector<float>();
    auto modelOpt = TailoredCalcType::TAILORED_CALC_S0001;
    if (modelOpts.size() > 0)
    {
        int modelOptInt = static_cast<int>(modelOpts[0]) % 10000;
        if (tailoredCalcTypeMap.find(modelOptInt) != tailoredCalcTypeMap.end())
        {
            modelOpt = tailoredCalcTypeMap[modelOptInt];
        }  
    }

    std::vector<int> result = copilotProxy.TailoredCalc(modelOpt);
    int length = (std::min)(count, static_cast<int>(result.size()));
    for (int i = 0; i < length; i++)
    {
        int entrypointValue = static_cast<int>(result[i]);
        if (entrypointValue > 0)
        {
            out_values[i] = static_cast<float>(entrypointValue);
        }
        else if (entrypointValue < 0)
        {
            out_values[i] = static_cast<float>(entrypointValue);
        }
        else
        {
            out_values[i] = 0.0;
        }
    }
    copilotProxy.Reset();
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
    CopilotProxy &copilot = CopilotProxy::GetInstance();
    copilot.Reset();
    return 0;
}

int WINAPI SETPARAMVAR(CALCINFO *pData)
{
    if (pData->m_nNumData == 0) return 0;
    if (pData->m_nParam1Start >= 0 && pData->m_pfParam1 != NULL && pData->m_pfParam2 != NULL)
    {
        int nDataLen = pData->m_nNumData;
        CopilotProxy &copilot = CopilotProxy::GetInstance();
        ParamType paramType = static_cast<ParamType>(static_cast<int>(*pData->m_pfParam2));
        std::vector<float> params(pData->m_pfParam1, pData->m_pfParam1 + nDataLen);
        copilot.SetParam(paramType, params);
        return 0;
    }
    return -1;
}

int WINAPI SXXXX(CALCINFO *pData)
{
    int nDataLen = pData->m_nNumData;
    if (nDataLen == 0) return 0;
    memset(pData->m_pResultBuf, 0, nDataLen);
    CopilotProxy &copilotProxy = CopilotProxy::GetInstance();

    std::vector<float> high(nDataLen);
    std::vector<float> low(nDataLen);
    std::vector<float> open(nDataLen);
    std::vector<float> close(nDataLen);
    std::vector<float> vol(nDataLen);
    for (int i = 0; i < nDataLen; i++)
    {
        high[i] = pData->m_pData[i].m_fHigh;
        low[i] = pData->m_pData[i].m_fLow;
        open[i] = pData->m_pData[i].m_fOpen;
        close[i] = pData->m_pData[i].m_fClose;
        vol[i] = pData->m_pData[i].m_fVolume;
        pData->m_pResultBuf[i] = 0;
    }
    copilotProxy.SetParam(ParamType::PARAM_HIGH, high);
    copilotProxy.SetParam(ParamType::PARAM_LOW, low);
    copilotProxy.SetParam(ParamType::PARAM_OPEN, open);
    copilotProxy.SetParam(ParamType::PARAM_CLOSE, close);
    copilotProxy.SetParam(ParamType::PARAM_VOLUME, vol);

    if (pData->m_pfParam1 && pData->m_nParam1Start < 0)
    {
        int option = static_cast<int>(*pData->m_pfParam1);
        std::vector<float> wave_opt(1, option);
        copilotProxy.SetParam(ParamType::PARAM_WAVE_OPT, wave_opt);
    }
    if (pData->m_pfParam2)
    {
        int option = static_cast<int>(*pData->m_pfParam2);
        std::vector<float> stretch_opt(1, option);
        copilotProxy.SetParam(ParamType::PARAM_STRETCH_OPT, stretch_opt);
    }
    if (pData->m_pfParam3)
    {
        int option = static_cast<int>(*pData->m_pfParam3);
        std::vector<float> trend_opt(1, option);
        copilotProxy.SetParam(ParamType::PARAM_TREND_OPT, trend_opt);
    }
    auto modelOpt = CalcType::CALC_S0001;
    if (pData->m_pfParam4)
    {
        int modelOptInt = static_cast<int>(*pData->m_pfParam4);
        std::vector<float> model_opt(1, modelOptInt);
        copilotProxy.SetParam(ParamType::PARAM_MODEL_OPT, model_opt);
        if (calcTypeMap.find(modelOptInt % 10000) != calcTypeMap.end())
        {
            modelOpt = calcTypeMap[modelOptInt % 10000];
        }
    }

    std::vector<int> result = copilotProxy.Calc(modelOpt);
    int length = (std::min)(nDataLen, static_cast<int>(result.size()));
    for (int i = 0; i < length; i++)
    {
        int entrypointValue = static_cast<int>(result[i]);
        if (entrypointValue > 0)
        {
            pData->m_pResultBuf[i] = static_cast<float>(entrypointValue);
        }
        else if (entrypointValue < 0)
        {
            pData->m_pResultBuf[i] = static_cast<float>(entrypointValue);
        }
        else
        {
            pData->m_pResultBuf[i] = 0.0;
        }
    }
    copilotProxy.Reset();
    return 0;
}

int WINAPI TSXXXX(CALCINFO *pData)
{
    int nDataLen = pData->m_nNumData;
    if (nDataLen == 0) return 0;
    memset(pData->m_pResultBuf, 0, nDataLen);
    CopilotProxy &copilotProxy = CopilotProxy::GetInstance();

    std::vector<float> high(nDataLen);
    std::vector<float> low(nDataLen);
    std::vector<float> open(nDataLen);
    std::vector<float> close(nDataLen);
    std::vector<float> vol(nDataLen);
    for (int i = 0; i < nDataLen; i++)
    {
        high[i] = pData->m_pData[i].m_fHigh;
        low[i] = pData->m_pData[i].m_fLow;
        open[i] = pData->m_pData[i].m_fOpen;
        close[i] = pData->m_pData[i].m_fClose;
        vol[i] = pData->m_pData[i].m_fVolume;
        pData->m_pResultBuf[i] = 0;
    }
    copilotProxy.SetParam(ParamType::PARAM_HIGH, high);
    copilotProxy.SetParam(ParamType::PARAM_LOW, low);
    copilotProxy.SetParam(ParamType::PARAM_OPEN, open);
    copilotProxy.SetParam(ParamType::PARAM_CLOSE, close);
    copilotProxy.SetParam(ParamType::PARAM_VOLUME, vol);

    if (pData->m_pfParam1 && pData->m_nParam1Start < 0)
    {
        int option = static_cast<int>(*pData->m_pfParam1);
        std::vector<float> wave_opt(1, option);
        copilotProxy.SetParam(ParamType::PARAM_WAVE_OPT, wave_opt);
    }
    if (pData->m_pfParam2)
    {
        int option = static_cast<int>(*pData->m_pfParam2);
        std::vector<float> stretch_opt(1, option);
        copilotProxy.SetParam(ParamType::PARAM_STRETCH_OPT, stretch_opt);
    }
    if (pData->m_pfParam3)
    {
        int option = static_cast<int>(*pData->m_pfParam3);
        std::vector<float> trend_opt(1, option);
        copilotProxy.SetParam(ParamType::PARAM_TREND_OPT, trend_opt);
    }
    auto modelOpt = TailoredCalcType::TAILORED_CALC_S0001;
    if (pData->m_pfParam4)
    {
        int modelOptInt = static_cast<int>(*pData->m_pfParam4);
        std::vector<float> model_opt(1, modelOptInt);
        copilotProxy.SetParam(ParamType::PARAM_MODEL_OPT, model_opt);
        if (tailoredCalcTypeMap.find(modelOptInt % 10000) != tailoredCalcTypeMap.end())
        {
            modelOpt = tailoredCalcTypeMap[modelOptInt % 10000];
        }
    }

    std::vector<int> result = copilotProxy.TailoredCalc(modelOpt);
    int length = (std::min)(nDataLen, static_cast<int>(result.size()));
    for (int i = 0; i < length; i++)
    {
        int entrypointValue = static_cast<int>(result[i]);
        if (entrypointValue > 0)
        {
            pData->m_pResultBuf[i] = static_cast<float>(entrypointValue);
        }
        else if (entrypointValue < 0)
        {
            pData->m_pResultBuf[i] = static_cast<float>(entrypointValue);
        }
        else
        {
            pData->m_pResultBuf[i] = 0.0;
        }
    }
    copilotProxy.Reset();
    return 0;
}

//=============================================================================
// FQCOPILOT 通用：波浪信号输出（MT5/Python 等可直接调）
//=============================================================================
void WINAPI FQ_CLXS(
    int count, double *out,
    const double *high, const double *low, const double *open, const double *close, const double *vol,
    int wave_opt, int stretch_opt, int trend_opt, int model_opt)
{
    if (count == 0)
        return;
    memset(out, 0, count * sizeof(double));

    // 显式转换 double* → float* vector
    std::vector<float> h(count);
    std::vector<float> l(count);
    std::vector<float> o(count);
    std::vector<float> c(count);
    std::vector<float> v(count);
    for(int i = 0; i < count; i++) {
        h[i] = static_cast<float>(high[i]);
        l[i] = static_cast<float>(low[i]);
        o[i] = static_cast<float>(open[i]);
        c[i] = static_cast<float>(close[i]);
        v[i] = static_cast<float>(vol[i]);
    }

    std::vector<float> result = clxs(count, h, l, o, c, v, wave_opt, stretch_opt, trend_opt, model_opt);

    // 输出信号值
    for (size_t i = 0; i < result.size(); i++)
    {
        out[i] = static_cast<double>(result[i]);
    }
}
