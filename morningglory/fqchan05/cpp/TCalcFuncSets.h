#ifndef __TCALC_FUNC_SETS
#define __TCALC_FUNC_SETS

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
    __declspec(dllexport) int WINAPI RESET(CALCINFO *pData);       // 重置
    __declspec(dllexport) int WINAPI SETPARAMVAR(CALCINFO *pData); // 设置参数
    __declspec(dllexport) int WINAPI CALC(CALCINFO *pData); // 计算
    __declspec(dllexport) int WINAPI OUTPUT(CALCINFO *pData); // 输出

#ifdef _X64
#pragma comment(linker, "/export:_RUNMODE@0=RUNMODE")
#pragma comment(linker, "/export:_RESET@4=RESET")
#pragma comment(linker, "/export:_SETPARAMVAR@4=SETPARAMVAR")
#pragma comment(linker, "/export:_CALC@4=CALC")
#pragma comment(linker, "/export:_OUTPUT@4=OUTPUT")
#endif
#ifdef __cplusplus
}
#endif //__cplusplus

#endif //__TCALC_FUNC_SETS
