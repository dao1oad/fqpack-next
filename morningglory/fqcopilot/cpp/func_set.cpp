#include "func_set.h"
#include "copilot/copilot.h"

std::vector<float> clxs(
    int length,
    std::vector<float> &high, std::vector<float> &low, std::vector<float> &open, std::vector<float> &close,
    std::vector<float> &vol,
    int wave_opt, int stretch_opt, int trend_opt, int model_opt)
{
    std::vector<float> result = std::vector<float>(length, 0);
    if (length == 0)
    {
        return result;
    }
    Copilot copilot;
    copilot.SetParam(ParamType::PARAM_HIGH, high);
    copilot.SetParam(ParamType::PARAM_LOW, low);
    copilot.SetParam(ParamType::PARAM_OPEN, open);
    copilot.SetParam(ParamType::PARAM_CLOSE, close);
    copilot.SetParam(ParamType::PARAM_VOLUME, vol);
    copilot.SetParam(ParamType::PARAM_WAVE_OPT, std::vector<float>(1, static_cast<float>(wave_opt)));
    copilot.SetParam(ParamType::PARAM_STRETCH_OPT, std::vector<float>(1, static_cast<float>(stretch_opt)));
    copilot.SetParam(ParamType::PARAM_TREND_OPT, std::vector<float>(1, static_cast<float>(trend_opt)));
    copilot.SetParam(ParamType::PARAM_MODEL_OPT, std::vector<float>(1, static_cast<float>(model_opt)));
    auto modelOpt = CalcType::CALC_S0001;
    if (calcTypeMap.find(model_opt % 10000) != calcTypeMap.end())
    {
        modelOpt = calcTypeMap[model_opt % 10000];
    }
    std::vector<int> sigs = copilot.Calc(modelOpt);
    for (int i = 0; i < length; i++)
    {
        int entrypointValue = static_cast<int>(sigs[i]);
        if (entrypointValue > 0)
        {
            result[i] = static_cast<float>(entrypointValue);
        }
        else if (entrypointValue < 0)
        {
            result[i] = static_cast<float>(entrypointValue);
        }
        else
        {
            result[i] = 0.0;
        }
    }
    copilot.Reset();
    return result;
}
