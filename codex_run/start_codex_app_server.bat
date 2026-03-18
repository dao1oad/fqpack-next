@echo off
setlocal
cd /d "%~dp0.."
if "%~1"=="" (
    powershell -ExecutionPolicy Bypass -File "%~dp0start_freshquant_codex.ps1" -Mode app-server
) else (
    powershell -ExecutionPolicy Bypass -File "%~dp0start_freshquant_codex.ps1" -Mode app-server -CodexArgs %*
)
exit /b %errorlevel%
