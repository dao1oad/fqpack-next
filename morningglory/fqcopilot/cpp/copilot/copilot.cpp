#include "copilot.h"
#include "../chanlun/czsc.h"
#include "../common/log.h"

thread_local CopilotProxy *CopilotProxy::instance = NULL;

CopilotProxy::CopilotProxy()
{
    copilot = new Copilot();
}

CopilotProxy::~CopilotProxy()
{
    if (copilot)
    {
        delete copilot;
        copilot = NULL;
    }
    if (instance)
    {
        delete instance;
        instance = NULL;
    }
}

CopilotProxy &CopilotProxy::GetInstance()
{
    if (!instance)
    {
        instance = new CopilotProxy();
    }
    return *instance;
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
        // 是否合并未完备的笔
        options.merge_non_complehensive_wave = waveOpt / 10000 % 10;
    }
    switch (calcType)
    {
    case CalcType::CALC_S0000:
    {
        return F_S0000(high, low, open, close, vol, switch_opt, options);
    }
    case CalcType::CALC_S0001:
    {
        return F_S0001(high, low, open, close, vol, switch_opt, options);
    }
    case CalcType::CALC_S0002:
    {
        return F_S0002(high, low, open, close, vol, switch_opt, options);
    }
    case CalcType::CALC_S0003:
    {
        return F_S0003(high, low, open, close, vol, switch_opt, options);
    }
    case CalcType::CALC_S0004:
    {
        return F_S0004(high, low, open, close, vol, switch_opt, options);
    }
    case CalcType::CALC_S0005:
    {
        return F_S0005(high, low, open, close, vol, switch_opt, options);
    }
    case CalcType::CALC_S0006:
    {
        return F_S0006(high, low, open, close, vol, switch_opt, options);
    }
    case CalcType::CALC_S0007:
    {
        return F_S0007(high, low, open, close, vol, switch_opt, options);
    }
    case CalcType::CALC_S0008:
    {
        return F_S0008(high, low, open, close, vol, switch_opt, options);
    }
    case CalcType::CALC_S0009:
    {
        return F_S0009(high, low, open, close, vol, switch_opt, options);
    }
    case CalcType::CALC_S0010:
    {
        return F_S0010(high, low, open, close, vol, switch_opt, options);
    }
    case CalcType::CALC_S0011:
    {
        return F_S0011(high, low, open, close, vol, switch_opt, options);
    }
    case CalcType::CALC_S0012:
    {
        return F_S0012(high, low, open, close, vol, switch_opt, options);
    }
    default:
        return F_S0000(high, low, open, close, vol, switch_opt, options);
    }
    return std::vector<int>();
}

std::map<int, TailoredCalcType> tailoredCalcTypeMap = {
    {static_cast<int>(TailoredCalcType::TAILORED_CALC_S0001), TailoredCalcType::TAILORED_CALC_S0001},
};

std::vector<int> Copilot::TailoredCalc(TailoredCalcType calcType)
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
        // 是否合并未完备的笔
        options.merge_non_complehensive_wave = waveOpt / 10000 % 10;
    }
    switch (calcType)
    {
    case TailoredCalcType::TAILORED_CALC_S0001:
    {
        return TAILORED_F_S0001(high, low, open, close, vol, switch_opt, options);
    }
    default:
        return TAILORED_F_S0001(high, low, open, close, vol, switch_opt, options);
    }
    return std::vector<int>();
}

void Copilot::Reset()
{
    params.clear();
}
