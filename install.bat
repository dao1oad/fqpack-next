@echo off
cd /d "%~dp0"

where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo 错误: 未找到 uv 命令
    echo.
    echo 请先安装 uv: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
    echo 或访问: https://github.com/astral-sh/uv
    exit /b 1
)

uv pip install chardet
uv run install.py %*
