#pragma once

#include "PluginTCalcFunc.h"

#ifdef __cplusplus
extern "C"
{
#endif //__cplusplus
    /********************************************************************/
    //******************************通达信******************************//
    /********************************************************************/
    __declspec(dllexport) BOOL RegisterTdxFunc(PluginTCalcFuncInfo **pInfo);
    /********************************************************************/
    //************************交易师 大智慧******************************//
    /********************************************************************/
    __declspec(dllexport) int WINAPI RUNMODE();
    __declspec(dllexport) int WINAPI RESET(CALCINFO *pData);     // 计算
    __declspec(dllexport) int WINAPI SETPARAMVAR(CALCINFO *pData); // 设置参数
    __declspec(dllexport) int WINAPI SXXXX(CALCINFO *pData);     // 计算SXXXX
    __declspec(dllexport) int WINAPI SALL(CALCINFO *pData);      // 批量计算所有模型
    /********************************************************************/
    //******************************FQCOPILOT******************************/
    /********************************************************************/
    __declspec(dllexport) void WINAPI FQ_CLXS(
        int count, double *out,
        const double *high, const double *low, const double *open, const double *close, const double *vol,
        int wave_opt, int stretch_opt, int trend_opt, int model_opt);
    __declspec(dllexport) void WINAPI FQ_CLXS_ALL(
        int count,
        int model_count,
        double *out,
        const double *high, const double *low, const double *open, const double *close, const double *vol,
        int wave_opt, int stretch_opt, int trend_opt);

#ifdef MAKE_X64
#pragma comment(linker, "/export:_RUNMODE@0=RUNMODE")
#pragma comment(linker, "/export:_RESET@4=RESET")
#pragma comment(linker, "/export:_SETPARAMVAR@4=SETPARAMVAR")
#pragma comment(linker, "/export:_SXXXX@4=SXXXX")
#pragma comment(linker, "/export:_SALL@4=SALL")
#pragma comment(linker, "/export:_FQ_CLXS@52=FQ_CLXS")
#pragma comment(linker, "/export:FQ_CLXS_ALL=FQ_CLXS_ALL")
#endif
#ifdef __cplusplus
}
#endif //__cplusplus
