# fqchan04 - 交易工具库

远白超级板块和已矣公式库（多平台 DLL + Python 版本）。

## 开发命令

| 命令 | 用途 |
|------|------|
| `xmake` | 编译所有 C++ DLL 目标 |
| `python package.py` | 打包 Python 版本 |
| `build.bat` | 全平台构建（C++ + Python） |
| `clean.bat` | 清理构建代码 |

## 架构概览

本项目为多平台设计，核心高性能计算集成至 C++ DLL。

- **C++ 核心库**：`cpp/` 目录下的源码，通过 xmake 构建扩展
- **Python 封装**：`python/` 目录下的 Python 解蟬封装
- **多平台目标**：xmake.lua 配置的 6 个目标（tdx, tdx64, kt, jzt, jzt32, dzh）
- **版本管理**：version.py 和 version.txt 支持自动生成版本号

**核心流程**：C++ 实现缠论分析逻辑→生成多平台 DLL→Python 接口封装→用于各交易软件的公式展示

## 代码规范

项目采用 xmake 作为构建系统，用于编译 C++ 核心。pre-commit 配置确保代码质量和格式统一。

- **UTF-8 编码**：xmake.lua 中配置 Windows 平台使用 UTF-8 编码
- **代码格式化**：.pre-commit-config.yaml 配置 Black 格式化、检查 JSON/YAML、修复结尾空白等功能
- **类型注解**：pre-commit 配置要求使用 Python 类型注解

## 环境变量

本项目无需特定环境变量配置。

## 常用操作

这是起点，您可以通过 `#` 命令进一步添加操作。
