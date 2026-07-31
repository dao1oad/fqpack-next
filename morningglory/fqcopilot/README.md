# 股软选股插件(fqcopilot)

## 如何编译

### 编译前提

- xmake：`winget install Xmake-io.Xmake`
- VS BuildTools + C++ 工具集：`winget install Microsoft.VisualStudio.BuildTools --override "--passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"`

### 编译命令

```bash
# 编译全部目标
xmake build

# 或单独编译
xmake build tdx64    # 通达信64位
xmake build jzt      # 金字塔64位
xmake build jzt32    # 金字塔32位
xmake build dzh      # 大智慧64位
xmake build mt5      # MT5
```

编译产物输出到各目标的 `dlls/` 目录。

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
CLX_S016|16|支撑/阻力区间反转|HIGH,LOW,OPEN.CLOSE,WAVE,STRETCH
CLX_S017|17|支撑/阻力区间反转（笔级别）|HIGH,LOW,OPEN.CLOSE,WAVE,SWING