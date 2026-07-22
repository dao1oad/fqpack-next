#include "copilot.h"
#include "../chanlun/czsc.h"
#include "../common/log.h"

CopilotProxy::CopilotProxy() : copilot(std::make_unique<Copilot>()) {}

CopilotProxy::~CopilotProxy() = default;

CopilotProxy &CopilotProxy::GetInstance()
{
    thread_local CopilotProxy instance;
    return instance;
}

void CopilotProxy::SetParam(ParamType paramType, std::vector<float> params)
{
    copilot->SetParam(paramType, params);
}

bool CopilotProxy::ExistParam(ParamType paramType)
{
    return copilot->ExistParam(paramType);
}

std::vector<float> &CopilotProxy::GetParam(ParamType paramType)
{
    return copilot->GetParam(paramType);
}

std::vector<int> CopilotProxy::Calc(CalcType calcType)
{
    return copilot->Calc(calcType);
}

std::vector<int> CopilotProxy::TailoredCalc(TailoredCalcType calcType)
{
    return copilot->TailoredCalc(calcType);
}

void CopilotProxy::Reset()
{
    copilot->Reset();
}

Copilot::Copilot()
{
    this->params[ParamType::PARAM_UNKNOWN] = std::vector<float>();
}

Copilot::~Copilot()
{
    this->params.clear();
}

void Copilot::SetParam(ParamType paramType, std::vector<float> params)
{
    this->params[paramType] = params;
}

bool Copilot::ExistParam(ParamType paramType)
{
    return this->params.count(paramType);
}

std::vector<float> &Copilot::GetParam(ParamType paramType)
{
    if (params.count(paramType))
    {
        return this->params[paramType];
    } else {
        return this->params[ParamType::PARAM_UNKNOWN];
    }
}

// 策略注册表
std::map<int, CalcFn> &get_calc_registry()
{
    static std::map<int, CalcFn> registry;
    return registry;
}

// 保留 calcTypeMap 用于 func_set.cpp 兼容
std::map<int, CalcType> calcTypeMap = {
    {static_cast<int>(CalcType::CALC_S0000), CalcType::CALC_S0000},
    {static_cast<int>(CalcType::CALC_S0001), CalcType::CALC_S0001},
    {static_cast<int>(CalcType::CALC_S0002), CalcType::CALC_S0002},
    {static_cast<int>(CalcType::CALC_S0003), CalcType::CALC_S0003},
    {static_cast<int>(CalcType::CALC_S0004), CalcType::CALC_S0004},
    {static_cast<int>(CalcType::CALC_S0005), CalcType::CALC_S0005},
    {static_cast<int>(CalcType::CALC_S0006), CalcType::CALC_S0006},
    {static_cast<int>(CalcType::CALC_S0007), CalcType::CALC_S0007},
    {static_cast<int>(CalcType::CALC_S0008), CalcType::CALC_S0008},
    {static_cast<int>(CalcType::CALC_S0009), CalcType::CALC_S0009},
    {static_cast<int>(CalcType::CALC_S0010), CalcType::CALC_S0010},
    {static_cast<int>(CalcType::CALC_S0011), CalcType::CALC_S0011},
    {static_cast<int>(CalcType::CALC_S0012), CalcType::CALC_S0012},
    {static_cast<int>(CalcType::CALC_S0013), CalcType::CALC_S0013},
    {static_cast<int>(CalcType::CALC_S0014), CalcType::CALC_S0014},
    {static_cast<int>(CalcType::CALC_S0015), CalcType::CALC_S0015},
    {static_cast<int>(CalcType::CALC_S0016), CalcType::CALC_S0016},
    {static_cast<int>(CalcType::CALC_S0017), CalcType::CALC_S0017},
    {static_cast<int>(CalcType::CALC_S0101), CalcType::CALC_S0101},
};

std::vector<int> Copilot::Calc(CalcType calcType)
{
    // 准备参数
    std::vector<float> high = this->ExistParam(ParamType::PARAM_HIGH) ? this->GetParam(ParamType::PARAM_HIGH) : std::vector<float>();
    std::vector<float> low = this->ExistParam(ParamType::PARAM_LOW) ? this->GetParam(ParamType::PARAM_LOW) : std::vector<float>();
    std::vector<float> open = this->ExistParam(ParamType::PARAM_OPEN) ? this->GetParam(ParamType::PARAM_OPEN) : std::vector<float>();
    std::vector<float> close = this->ExistParam(ParamType::PARAM_CLOSE) ? this->GetParam(ParamType::PARAM_CLOSE) : std::vector<float>();
    std::vector<float> vol = this->ExistParam(ParamType::PARAM_VOLUME) ? this->GetParam(ParamType::PARAM_VOLUME) : std::vector<float>();
    // 检查 high, low, open, close 的长度是否一致且大于 0
    if (high.size() != low.size() || high.size() != open.size() || high.size() != close.size() || high.size() != vol.size() || high.size() == 0)
    {
        return std::vector<int>();
    }

    int switch_opt = 1;
    if (this->ExistParam(ParamType::PARAM_MODEL_OPT))
    {
        auto model_opt = static_cast<int>(this->GetParam(ParamType::PARAM_MODEL_OPT)[0]);
        switch_opt = model_opt / 10000;
    }

    ChanOptions options;
    // 设置笔参数
    if (this->ExistParam(ParamType::PARAM_WAVE_OPT))
    {
        int waveOpt = static_cast<int>(this->GetParam(ParamType::PARAM_WAVE_OPT)[0]);
        options.bi_mode = waveOpt / 10 % 10;
        options.force_wave_stick_count = waveOpt / 100 % 100;
        options.merge_non_complehensive_wave = waveOpt / 10000 % 10;
    }
    // 设置扩展参数
    if (this->ExistParam(ParamType::PARAM_EXT_OPT))
    {
        options.ext_opt = static_cast<int>(this->GetParam(ParamType::PARAM_EXT_OPT)[0]);
    }

    auto &registry = get_calc_registry();
    int key = static_cast<int>(calcType);
    auto it = registry.find(key);
    if (it != registry.end())
    {
        return it->second(high, low, open, close, vol, switch_opt, options);
    }
    return std::vector<int>();
}

std::map<int, TailoredCalcType> tailoredCalcTypeMap = {
    {static_cast<int>(TailoredCalcType::TAILORED_CALC_S0001),
     TailoredCalcType::TAILORED_CALC_S0001},
};

std::vector<int> Copilot::TailoredCalc(TailoredCalcType calcType)
{
    std::vector<float> high = this->ExistParam(ParamType::PARAM_HIGH)
                                  ? this->GetParam(ParamType::PARAM_HIGH)
                                  : std::vector<float>();
    std::vector<float> low = this->ExistParam(ParamType::PARAM_LOW)
                                 ? this->GetParam(ParamType::PARAM_LOW)
                                 : std::vector<float>();
    std::vector<float> open = this->ExistParam(ParamType::PARAM_OPEN)
                                  ? this->GetParam(ParamType::PARAM_OPEN)
                                  : std::vector<float>();
    std::vector<float> close = this->ExistParam(ParamType::PARAM_CLOSE)
                                   ? this->GetParam(ParamType::PARAM_CLOSE)
                                   : std::vector<float>();
    std::vector<float> vol = this->ExistParam(ParamType::PARAM_VOLUME)
                                 ? this->GetParam(ParamType::PARAM_VOLUME)
                                 : std::vector<float>();
    if (high.size() != low.size() || high.size() != open.size() ||
        high.size() != close.size() || high.size() != vol.size() ||
        high.empty())
    {
        return std::vector<int>();
    }

    int switch_opt = 1;
    if (this->ExistParam(ParamType::PARAM_MODEL_OPT))
    {
        switch_opt = static_cast<int>(
                         this->GetParam(ParamType::PARAM_MODEL_OPT)[0]) /
                     10000;
    }

    ChanOptions options;
    if (this->ExistParam(ParamType::PARAM_WAVE_OPT))
    {
        int wave_opt = static_cast<int>(
            this->GetParam(ParamType::PARAM_WAVE_OPT)[0]);
        options.bi_mode = wave_opt / 10 % 10;
        options.force_wave_stick_count = wave_opt / 100 % 100;
        options.merge_non_complehensive_wave = wave_opt / 10000 % 10;
    }
    if (calcType == TailoredCalcType::TAILORED_CALC_S0001)
    {
        return TAILORED_F_S0001(
            high, low, open, close, vol, switch_opt, options);
    }
    return TAILORED_F_S0001(
        high, low, open, close, vol, switch_opt, options);
}

void Copilot::Reset()
{
    params.clear();
}
