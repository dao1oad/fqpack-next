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
    __declspec(dllexport) int WINAPI BI1(CALCINFO *pData);      // 笔端点
    __declspec(dllexport) int WINAPI BI2(CALCINFO *pData);      // 笔端点
    __declspec(dllexport) int WINAPI BI(CALCINFO *pData);      // 笔端点
    __declspec(dllexport) int WINAPI DUAN1VAR(CALCINFO *pData); // 段端点
    __declspec(dllexport) int WINAPI DUAN2VAR(CALCINFO *pData); // 段端点
    __declspec(dllexport) int WINAPI ZSZGVAR(CALCINFO *pData);  // 中枢高
    __declspec(dllexport) int WINAPI ZSZDVAR(CALCINFO *pData);  // 中枢低
    __declspec(dllexport) int WINAPI ZSSEVAR(CALCINFO *pData);  // 中枢开始结束
    __declspec(dllexport) int WINAPI ZSFXVAR(CALCINFO *pData);  // 中枢方向
    __declspec(dllexport) int WINAPI ZSGSVAR(CALCINFO *pData);  // 同方向的第几个中枢

#ifdef _X64
    #pragma comment(linker, "/export:_RUNMODE@0=RUNMODE")
    #pragma comment(linker, "/export:_BI1@4=BI1")
    #pragma comment(linker, "/export:_BI2@4=BI2")
    #pragma comment(linker, "/export:_DUAN1VAR@4=DUAN1VAR")
    #pragma comment(linker, "/export:_DUAN2VAR@4=DUAN2VAR")
    #pragma comment(linker, "/export:_ZSZGVAR@4=ZSZGVAR")
    #pragma comment(linker, "/export:_ZSZDVAR@4=ZSZDVAR")
    #pragma comment(linker, "/export:_ZSSEVAR@4=ZSSEVAR")
    #pragma comment(linker, "/export:_ZSFXVAR@4=ZSFXVAR")
    #pragma comment(linker, "/export:_ZSGSVAR@4=ZSGSVAR")
#endif

#ifdef __cplusplus
}
#endif //__cplusplus

#endif //__TCALC_FUNC_SETS
