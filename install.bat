@echo off
setlocal
cd /d "%~dp0"

call create_venv.bat || exit /b 1

set "UV_BIN="
call :resolve_uv
if not defined UV_BIN (
    echo Error: uv.exe not found
    exit /b 1
)

".venv\Scripts\python.exe" install.py --skip-env --runtime-prereqs-only || exit /b 1
if exist "morningglory\fqchan01\python\build" (
    rmdir /s /q "morningglory\fqchan01\python\build" || exit /b 1
)
"%UV_BIN%" sync --frozen --refresh-package fqchan01 --reinstall-package fqchan01 || exit /b 1
".venv\Scripts\python.exe" install.py %*
exit /b %errorlevel%

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
