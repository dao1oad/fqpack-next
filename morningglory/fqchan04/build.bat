@echo off
setlocal enabledelayedexpansion

call clean.bat

xmake

:: package DLLs
uv run --directory "%CD%" package.py

:: build Python wheels (all versions, windows + linux)
uvx cibuildwheel --platform windows python
uvx cibuildwheel --platform linux python

:: package Python wheels
uv run --directory "%CD%\python" package.py

endlocal
