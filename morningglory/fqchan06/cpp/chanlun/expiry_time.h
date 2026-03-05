#pragma once

// 自动计算过期时间：编译时间 + 1年
// 使用编译时宏解析 __DATE__ 和 __TIME__

// 月份名称到数字的转换宏
#define MONTH_JAN 1
#define MONTH_FEB 2
#define MONTH_MAR 3
#define MONTH_APR 4
#define MONTH_MAY 5
#define MONTH_JUN 6
#define MONTH_JUL 7
#define MONTH_AUG 8
#define MONTH_SEP 9
#define MONTH_OCT 10
#define MONTH_NOV 11
#define MONTH_DEC 12

// 解析月份字符串
#define MONTH_NUM(mon) \
    ((mon[0] == 'J' && mon[1] == 'a' && mon[2] == 'n') ? MONTH_JAN : \
     (mon[0] == 'F' && mon[1] == 'e' && mon[2] == 'b') ? MONTH_FEB : \
     (mon[0] == 'M' && mon[1] == 'a' && mon[2] == 'r') ? MONTH_MAR : \
     (mon[0] == 'A' && mon[1] == 'p' && mon[2] == 'r') ? MONTH_APR : \
     (mon[0] == 'M' && mon[1] == 'a' && mon[2] == 'y') ? MONTH_MAY : \
     (mon[0] == 'J' && mon[1] == 'u' && mon[2] == 'n') ? MONTH_JUN : \
     (mon[0] == 'J' && mon[1] == 'u' && mon[2] == 'l') ? MONTH_JUL : \
     (mon[0] == 'A' && mon[1] == 'u' && mon[2] == 'g') ? MONTH_AUG : \
     (mon[0] == 'S' && mon[1] == 'e' && mon[2] == 'p') ? MONTH_SEP : \
     (mon[0] == 'O' && mon[1] == 'c' && mon[2] == 't') ? MONTH_OCT : \
     (mon[0] == 'N' && mon[1] == 'o' && mon[2] == 'v') ? MONTH_NOV : \
     (mon[0] == 'D' && mon[1] == 'e' && mon[2] == 'c') ? MONTH_DEC : 0)

// 解析编译日期和时间
#define COMPILE_YEAR ((__DATE__[7] - '0') * 1000 + (__DATE__[8] - '0') * 100 + (__DATE__[9] - '0') * 10 + (__DATE__[10] - '0'))
#define COMPILE_MONTH MONTH_NUM(__DATE__)
#define COMPILE_DAY ((__DATE__[4] == ' ' ? 0 : __DATE__[4] - '0') * 10 + (__DATE__[5] - '0'))
#define COMPILE_HOUR ((__TIME__[0] - '0') * 10 + (__TIME__[1] - '0'))
#define COMPILE_MIN ((__TIME__[3] - '0') * 10 + (__TIME__[4] - '0'))
#define COMPILE_SEC ((__TIME__[6] - '0') * 10 + (__TIME__[7] - '0'))

// 计算从1970年1月1日到编译日期的天数（简化算法）
#define DAYS_FROM_1970_TO_COMPILE \
    ((COMPILE_YEAR - 1970) * 365 + (COMPILE_YEAR - 1969) / 4 - (COMPILE_YEAR - 1901) / 100 + (COMPILE_YEAR - 1601) / 400 + \
     (COMPILE_MONTH > 1 ? 31 : 0) + \
     (COMPILE_MONTH > 2 ? (28 + ((COMPILE_YEAR % 4 == 0 && COMPILE_YEAR % 100 != 0) || COMPILE_YEAR % 400 == 0)) : 0) + \
     (COMPILE_MONTH > 3 ? 31 : 0) + \
     (COMPILE_MONTH > 4 ? 30 : 0) + \
     (COMPILE_MONTH > 5 ? 31 : 0) + \
     (COMPILE_MONTH > 6 ? 30 : 0) + \
     (COMPILE_MONTH > 7 ? 31 : 0) + \
     (COMPILE_MONTH > 8 ? 31 : 0) + \
     (COMPILE_MONTH > 9 ? 30 : 0) + \
     (COMPILE_MONTH > 10 ? 31 : 0) + \
     (COMPILE_MONTH > 11 ? 30 : 0) + \
     (COMPILE_DAY - 1))

// 计算编译时的Unix时间戳
#define COMPILE_TIMESTAMP \
    (DAYS_FROM_1970_TO_COMPILE * 86400LL + COMPILE_HOUR * 3600 + COMPILE_MIN * 60 + COMPILE_SEC)

// 过期时间 = 编译时间 + 1年（365天）
#define EXPIRY_TIME (COMPILE_TIMESTAMP + 365LL * 24 * 3600)