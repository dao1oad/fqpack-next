#include "stdafx.h"
#include "TCalcFuncSets.h"
#include "copilot/copilot.h"
#include "copilot/batch_calculator.h"
#include "common/log.h"
#include "func_set.h"
#include <thread>

// ==============================================================================
// 内部统一计算 + 输出
// ==============================================================================
namespace
{

void calc_to_output(CopilotProxy &proxy, int count, float *out)
{
    memset(out, 0, count * sizeof(float));

    // 解析 model_opt
    auto modelOpt = CalcType::CALC_S0001;
    if (proxy.ExistParam(ParamType::PARAM_MODEL_OPT))
    {
        int modelOptInt = static_cast<int>(proxy.GetParam(ParamType::PARAM_MODEL_OPT)[0]) % 10000;
        if (calcTypeMap.find(modelOptInt) != calcTypeMap.end())
        {
            modelOpt = calcTypeMap[modelOptInt];
        }
    }

    std::vector<int> result = proxy.Calc(modelOpt);
    int length = (std::min)(count, static_cast<int>(result.size()));
    for (int i = 0; i < length; i++)
    {
        out[i] = static_cast<float>(result[i]);
    }
    proxy.Reset();
}

} // anonymous namespace

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
// 输出函数3号：计算信号-公共版本（通达信）
//=============================================================================
void Func3(int count, float *out, float *high, float *low, float *close)
{
    if (count == 0) return;
    CopilotProxy &proxy = CopilotProxy::GetInstance();

    proxy.SetParam(ParamType::PARAM_HIGH, std::vector<float>(high, high + count));
    proxy.SetParam(ParamType::PARAM_LOW, std::vector<float>(low, low + count));
    proxy.SetParam(ParamType::PARAM_CLOSE, std::vector<float>(close, close + count));

    calc_to_output(proxy, count, out);
}

//=============================================================================
// 输出函数4号：批量计算所有模型（通达信）
//=============================================================================
void Func4(int count, float *out, float *high, float *low, float *close)
{
    if (count == 0) return;
    memset(out, 0, count * sizeof(float));

    CopilotProxy &proxy = CopilotProxy::GetInstance();
    proxy.SetParam(ParamType::PARAM_HIGH, std::vector<float>(high, high + count));
    proxy.SetParam(ParamType::PARAM_LOW, std::vector<float>(low, low + count));
    proxy.SetParam(ParamType::PARAM_CLOSE, std::vector<float>(close, close + count));

    ChanOptions options;
    if (proxy.ExistParam(ParamType::PARAM_WAVE_OPT))
    {
        int waveOpt = static_cast<int>(proxy.GetParam(ParamType::PARAM_WAVE_OPT)[0]);
        options.bi_mode = waveOpt / 10 % 10;
        options.force_wave_stick_count = waveOpt / 100 % 100;
        options.merge_non_complehensive_wave = waveOpt / 10000 % 10;
    }
    if (proxy.ExistParam(ParamType::PARAM_EXT_OPT))
    {
        options.ext_opt = static_cast<int>(proxy.GetParam(ParamType::PARAM_EXT_OPT)[0]);
    }

    std::vector<float> open_data(count, 0);
    std::vector<float> vol_data(count, 0);
    if (proxy.ExistParam(ParamType::PARAM_OPEN))
        open_data = proxy.GetParam(ParamType::PARAM_OPEN);
    if (proxy.ExistParam(ParamType::PARAM_VOLUME))
        vol_data = proxy.GetParam(ParamType::PARAM_VOLUME);

    auto h = std::vector<float>(high, high + count);
    auto l = std::vector<float>(low, low + count);
    auto c = std::vector<float>(close, close + count);

    BatchCalculator batch(h, l, open_data, c, vol_data, 0, options);
    auto sigs = batch.calc_all();

    for (int i = 0; i < count; i++)
    {
        for (int m = 0; m < 18; m++)
        {
            if (sigs[m][i] != 0)
            {
                out[i] = static_cast<float>(sigs[m][i]);
            }
        }
    }

    proxy.Reset();
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
    CopilotProxy &proxy = CopilotProxy::GetInstance();

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
    }
    proxy.SetParam(ParamType::PARAM_HIGH, high);
    proxy.SetParam(ParamType::PARAM_LOW, low);
    proxy.SetParam(ParamType::PARAM_OPEN, open);
    proxy.SetParam(ParamType::PARAM_CLOSE, close);
    proxy.SetParam(ParamType::PARAM_VOLUME, vol);

    if (pData->m_pfParam1 && pData->m_nParam1Start < 0)
    {
        int option = static_cast<int>(*pData->m_pfParam1);
        proxy.SetParam(ParamType::PARAM_WAVE_OPT, std::vector<float>(1, static_cast<float>(option)));
    }
    if (pData->m_pfParam2)
    {
        int option = static_cast<int>(*pData->m_pfParam2);
        proxy.SetParam(ParamType::PARAM_STRETCH_OPT, std::vector<float>(1, static_cast<float>(option)));
    }
    if (pData->m_pfParam3)
    {
        int option = static_cast<int>(*pData->m_pfParam3);
        proxy.SetParam(ParamType::PARAM_EXT_OPT, std::vector<float>(1, static_cast<float>(option)));
    }
    if (pData->m_pfParam4)
    {
        int modelOptInt = static_cast<int>(*pData->m_pfParam4);
        proxy.SetParam(ParamType::PARAM_MODEL_OPT, std::vector<float>(1, static_cast<float>(modelOptInt)));
    }

    // 利用 CALCINFO 的 result buffer 作为输出
    std::vector<float> tempOut(nDataLen, 0);
    calc_to_output(proxy, nDataLen, tempOut.data());
    for (int i = 0; i < nDataLen; i++)
    {
        pData->m_pResultBuf[i] = tempOut[i];
    }
    return 0;
}

int WINAPI SALL(CALCINFO *pData)
{
    int nDataLen = pData->m_nNumData;
    if (nDataLen == 0) return 0;

    std::vector<float> high(nDataLen), low(nDataLen), open(nDataLen), close(nDataLen), vol(nDataLen);
    for (int i = 0; i < nDataLen; i++)
    {
        high[i] = pData->m_pData[i].m_fHigh;
        low[i] = pData->m_pData[i].m_fLow;
        open[i] = pData->m_pData[i].m_fOpen;
        close[i] = pData->m_pData[i].m_fClose;
        vol[i] = pData->m_pData[i].m_fVolume;
    }

    ChanOptions options;
    if (pData->m_pfParam1 && pData->m_nParam1Start < 0)
    {
        int option = static_cast<int>(*pData->m_pfParam1);
        options.bi_mode = option / 10 % 10;
        options.force_wave_stick_count = option / 100 % 100;
        options.merge_non_complehensive_wave = option / 10000 % 10;
    }
    if (pData->m_pfParam2)
    {
        options.ext_opt = static_cast<int>(*pData->m_pfParam2);
    }

    BatchCalculator batch(high, low, open, close, vol, 0, options);
    auto sigs = batch.calc_all();

    std::vector<float> tempOut(nDataLen, 0);
    for (int i = 0; i < nDataLen; i++)
    {
        for (int m = 0; m < 18; m++)
        {
            if (sigs[m][i] != 0)
            {
                tempOut[i] = static_cast<float>(sigs[m][i]);
            }
        }
    }

    for (int i = 0; i < nDataLen; i++)
    {
        pData->m_pResultBuf[i] = tempOut[i];
    }
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
    for (int i = 0; i < count; i++)
    {
        h[i] = static_cast<float>(high[i]);
        l[i] = static_cast<float>(low[i]);
        o[i] = static_cast<float>(open[i]);
        c[i] = static_cast<float>(close[i]);
        v[i] = static_cast<float>(vol[i]);
    }

    std::vector<float> result = clxs(count, h, l, o, c, v, wave_opt, stretch_opt, trend_opt, model_opt);

    for (size_t i = 0; i < result.size(); i++)
    {
        out[i] = static_cast<double>(result[i]);
    }
}

//=============================================================================
// FQCOPILOT 通用：批量计算全部 18 个模型（MT5/Python）
//=============================================================================
void WINAPI FQ_CLXS_ALL(
    int count,
    int model_count,
    double *out,
    const double *high, const double *low, const double *open, const double *close, const double *vol,
    int wave_opt, int stretch_opt, int trend_opt)
{
    if (count == 0) return;
    memset(out, 0, count * model_count * sizeof(double));

    std::vector<float> h(count), l(count), o(count), c(count), v(count);
    for (int i = 0; i < count; i++)
    {
        h[i] = static_cast<float>(high[i]);
        l[i] = static_cast<float>(low[i]);
        o[i] = static_cast<float>(open[i]);
        c[i] = static_cast<float>(close[i]);
        v[i] = static_cast<float>(vol[i]);
    }

    auto results = clxs_all(count, h, l, o, c, v, wave_opt, stretch_opt, trend_opt);

    int mc = (std::min)(model_count, 18);
    for (int m = 0; m < mc; m++)
    {
        for (int i = 0; i < count; i++)
        {
            out[i * model_count + m] = static_cast<double>(results[m][i]);
        }
    }
}
