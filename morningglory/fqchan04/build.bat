@echo off
setlocal enabledelayedexpansion

call clean.bat

xmake

:: 构建 Python wheel（多版本）
for %%v in (3.8 3.9 3.10 3.11 3.12) do (
    uv build --wheel --python %%v --directory "%CD%\python"
)

:: 构建 Linux wheel（多版本）
for %%v in (3.8 3.9 3.10 3.11 3.12) do (
    docker run --rm -v "%CD%":/fqchan04 -w /fqchan04/python python:%%v-bookworm sh -c "sed -i 's/\r$//' build.sh && sh build.sh"
)

:: 打包发布
uv run --directory "%CD%\python" package.py

endlocal
