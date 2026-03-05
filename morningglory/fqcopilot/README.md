# 股软选股插件(fqcopilot)

## 如何编译

### 编译前提

#### 安装vcpkg

```
scoop install vcpkg
```

安装后设置环境变量，VCPKG_ROOT指向安装的根目录，如下是我的安装目录。

```
set VCPKG_ROOT=C:\Users\xxxxxxxx\scoop\apps\vcpkg\current
setx VCPKG_ROOT C:\Users\xxxxxxxx\scoop\apps\vcpkg\current
```

#### 使用vcpkg安装poco

```
vcpkg install poco
```

### Visual Studio 2019 或者 Visual Studio 2022

编译通达信/大智慧/交易师等32位版本用

```cmd
cmake -A Win32 -B build32
cmake --build build32 --config Release
```

编译金字塔64位版本用

```cmd
cmake . -B buildJzt
cmake --build buildJzt --config Release
```

编译大智慧64位版本用

```cmd
cmake -D MAKE_DZH=1 . -B buildDzh
cmake --build buildDzh --config Release
```

## 参数类型说明

参数类型名称|参数类型值|说明
------|------|------
HIGH|1|最高价
LOW|2|最低价
OPEN|3|开盘价
CLOSE|4|收盘价
VOLUME|5|成交量
DT|6|时间
SWING|10|分型笔端点
SWING_PIVOT_SE|11|分型中枢开始和结束
SWING_PIVOT_ZG|12|分型中枢高
SWING_PIVOT_ZD|13|分型中枢低
SWING_PIVOT_GG|14|分型中枢高高
SWING_PIVOT_DD|15|分型中枢低低
WAVE|20|笔端点
WAVE_PIVOT_SE|21|笔中枢开始和结束
WAVE_PIVOT_ZG|22|笔中枢高
WAVE_PIVOT_ZD|23|笔中枢低
WAVE_PIVOT_GG|24|笔中枢高高
WAVE_PIVOT_DD|25|笔中枢低低
STRETCH|30|段端点
STRETCH_PIVOT_SE|31|段中枢开始和结束
STRETCH_PIVOT_ZG|32|段中枢高
STRETCH_PIVOT_ZD|33|段中枢低
STRETCH_PIVOT_GG|34|段中枢高高
STRETCH_PIVOT_DD|35|段中枢低低
TREND1|40|一级走势端点
TREND1_PIVOT_SE|41|一级走势中枢开始和结束
TREND1_PIVOT_ZG|42|一级走势中枢高
TREND1_PIVOT_ZD|43|一级别走势中枢低
TREND1_PIVOT_GG|44|一级走势中枢高高
TREND1_PIVOT_DD|45|一级走势中枢低低
TREND2|50|二级走势端点
TREND2_PIVOT_SE|51|二级走势中枢开始和结束
TREND2_PIVOT_ZG|52|二级走势中枢高
TREND2_PIVOT_ZD|53|二级别走势中枢低
TREND2_PIVOT_GG|54|二级走势中枢高高
TREND2_PIVOT_DD|55|二级走势中枢低低
TREND3|60|三级走势端点
TREND3_PIVOT_SE|61|三级走势中枢开始和结束
TREND3_PIVOT_ZG|62|三级走势中枢高
TREND3_PIVOT_ZD|63|三级别走势中枢低
TREND3_PIVOT_GG|64|三级走势中枢高高
TREND3_PIVOT_DD|65|三级走势中枢低低
TREND4|70|四级走势端点
TREND4_PIVOT_SE|71|四级走势中枢开始和结束
TREND4_PIVOT_ZG|72|四级走势中枢高
TREND4_PIVOT_ZD|73|四级别走势中枢低
TREND4_PIVOT_GG|74|四级走势中枢高高
TREND4_PIVOT_DD|75|四级走势中枢低低
TREND5|80|五级走势端点
TREND5_PIVOT_SE|81|五级走势中枢开始和结束
TREND5_PIVOT_ZG|82|五级走势中枢高
TREND5_PIVOT_ZD|83|五级别走势中枢低
TREND5_PIVOT_GG|84|五级走势中枢高高
TREND5_PIVOT_DD|85|五级走势中枢低低
TREND6|90|五级走势端点
TREND6_PIVOT_SE|91|六级走势中枢开始和结束
TREND6_PIVOT_ZG|92|六级走势中枢高
TREND6_PIVOT_ZD|93|六级别走势中枢低
TREND6_PIVOT_GG|94|六级走势中枢高高
TREND6_PIVOT_DD|95|六级走势中枢低低


## 选股模型使用说明

模型类型编码|模型类型值|模型说明|需要参数
------|------|------|------
CLX_S001|1|走势下跌+上涨笔中枢完备|HIGH,LOW,OPEN.CLOSE,WAVE,STRETCH,TREND1