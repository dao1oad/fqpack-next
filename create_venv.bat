@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>nul
    if %errorlevel% equ 0 exit /b 0
    rmdir /s /q .venv || exit /b 1
)

set "UV_BIN="
call :resolve_uv
if not defined UV_BIN (
    echo Error: uv.exe not found
    exit /b 1
)

"%UV_BIN%" python install 3.12 || exit /b 1
"%UV_BIN%" venv .venv --python 3.12 || exit /b 1
exit /b 0

:resolve_uv
where uv >nul 2>nul
if %errorlevel% equ 0 (
    for /f "delims=" %%i in ('where uv') do (
        set "UV_BIN=%%i"
        goto :eof
    )
)
if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "UV_BIN=%USERPROFILE%\.local\bin\uv.exe"
    goto :eof
)
if exist "%USERPROFILE%\.cargo\bin\uv.exe" (
    set "UV_BIN=%USERPROFILE%\.cargo\bin\uv.exe"
    goto :eof
)
if exist "D:\fqpack\miniconda3\envs\fqkit\Scripts\uv.exe" (
    set "UV_BIN=D:\fqpack\miniconda3\envs\fqkit\Scripts\uv.exe"
)
goto :eof
