#include "func_set.h"
#include "copilot/copilot.h"
#include "copilot/batch_calculator.h"
#include <utility>

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
    copilot.SetParam(ParamType::PARAM_EXT_OPT, std::vector<float>(1, static_cast<float>(trend_opt)));
    copilot.SetParam(ParamType::PARAM_MODEL_OPT, std::vector<float>(1, static_cast<float>(model_opt)));

    int typeKey = model_opt % 10000;
    std::vector<int> sigs;
    if (calcTypeMap.find(typeKey) != calcTypeMap.end())
    {
        sigs = copilot.Calc(calcTypeMap[typeKey]);
    }
    else
    {
        sigs = copilot.Calc(CalcType::CALC_S0001);
    }

    for (int i = 0; i < length; ++i)
    {
        int entrypointValue = static_cast<int>(sigs[i]);
        if (entrypointValue != 0)
        {
            result[i] = static_cast<float>(entrypointValue);
        }
    }
    copilot.Reset();
    return result;
}

std::vector<std::vector<float>> clxs_all(
    int length,
    std::vector<float> &high, std::vector<float> &low,
    std::vector<float> &open, std::vector<float> &close,
    std::vector<float> &vol,
    int wave_opt, int stretch_opt, int trend_opt)
{
    std::vector<std::vector<float>> result(18, std::vector<float>(length, 0));
    if (length == 0) return result;

    ChanOptions options;
    options.bi_mode = wave_opt / 10 % 10;
    options.force_wave_stick_count = wave_opt / 100 % 100;
    options.merge_non_complehensive_wave = wave_opt / 10000 % 10;
    options.ext_opt = trend_opt;

    BatchCalculator batch(high, low, open, close, vol, 0, options);
    auto sigs = batch.calc_all();

    for (int model = 0; model < 18; model++)
    {
        for (int i = 0; i < length; i++)
        {
            if (sigs[model][i] != 0)
            {
                result[model][i] = static_cast<float>(sigs[model][i]);
            }
        }
    }
    return result;
}

std::vector<std::vector<int>> clxs_all_detailed(
    int length,
    std::vector<float> &high, std::vector<float> &low,
    std::vector<float> &open, std::vector<float> &close,
    std::vector<float> &vol,
    int wave_opt, int stretch_opt, int trend_opt)
{
    std::vector<std::vector<int>> result(20);
    if (length == 0) return result;

    ChanOptions options;
    options.bi_mode = wave_opt / 10 % 10;
    options.force_wave_stick_count = wave_opt / 100 % 100;
    options.merge_non_complehensive_wave = wave_opt / 10000 % 10;
    options.ext_opt = trend_opt;

    BatchCalculator batch(high, low, open, close, vol, 0, options);
    auto detailed = batch.calc_all_detailed();
    for (int model = 0; model < 18; ++model)
    {
        result[model] = std::move(detailed.signals[model]);
    }
    result[18] = std::move(detailed.buy_base_trigger_masks);
    result[19] = std::move(detailed.sell_base_trigger_masks);
    return result;
}
