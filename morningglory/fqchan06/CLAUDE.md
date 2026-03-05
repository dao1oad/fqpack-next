# fqchan06

缠论技术分析插件，支持通达信、金字塔、大智慧、KT交易师等交易软件，提供笔、线段、中枢等指标计算。

## 开发命令

| 命令 | 用途 |
|------|------|
| `build.bat` | 构建所有平台插件 + Python wheel（全量构建） |
| `xmake` | 编译 C++ 插件（仅当前平台） |
| `python/build.sh` | 构建 Python wheel（Linux/Docker） |

## 架构概览

**cpp/** - C++ 核心算法，编译为各平台共享库（DLL）
- **chanlun/** - 缠论算法实现：`bi`（笔）、`chan`（线段）、`xd`（线段）、`czsc`（中枢）
- **common/** - 通用工具：日志输出
- `PluginTCalcFunc.h` - 插件接口定义
- `TCalcFuncSets.cpp/h` - 公式函数导出

**python/** - Python 绑定，通过 Cython 封装 C++ 算法

**输出目录** - 各平台插件产物
- `tdx/tdx64/` - 通达信 32/64 位
- `jzt/jzt32/` - 金字塔 64/32 位
- `kt/` - KT 交易师
- `dzh/` - 大智慧

**核心流程**：交易软件调用 DLL 导出函数 → `TCalcFuncSets.cpp` 分发到缠论算法 → 返回计算结果

## 代码规范

- 全局 UTF-8 编码（`/utf-8` 标志）
- 特性通过 `xmake.lua` 中的宏定义控制：
  - `_GAP_COUNT_AS_ONE_BAR` - 跳空缺口计数1根K线
  - `_RIPPLE_REVERSE_WAVE_NO_MERGE` - 小转大笔不合并
- 平台区分宏：`_X64`（64位）、`_DZH`（大智慧）
- 编译使用 xmake，支持 release/debug 模式
