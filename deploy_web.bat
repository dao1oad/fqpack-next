@echo off
cd /d "%~dp0"

echo ========================================
echo FreshQuant Web UI Deployment Script
echo ========================================

SET FQ_RUN_WEB_BUILD=N
SET /p FQ_RUN_WEB_BUILD="Rebuild web UI? ([default]=%FQ_RUN_WEB_BUILD%, Y=Yes, N=No): "

if /I "%FQ_RUN_WEB_BUILD%"=="Y" (
    echo Building web UI...
    call build_web.bat
    if %errorlevel% neq 0 (
        echo Web build failed!
        goto :EOF
    )
)

echo Checking if fq_network exists...
docker network inspect "fq_network" >nul 2>&1
if %errorlevel% equ 0 (
    echo Network "fq_network" exists
) else (
    echo Creating network "fq_network"...
    docker network create -d bridge --subnet 172.19.0.0/24 --gateway 172.19.0.1 fq_network
)

echo Stopping fq_webui container...
docker stop fq_webui 2>nul

echo Removing fq_webui container...
docker rm fq_webui 2>nul

echo Deploying fq_webui...
docker run -d --name fq_webui --restart=always --network fq_network ^
    --log-driver=json-file --log-opt max-size=10m --log-opt max-file=3 ^
    -p 80:80 ^
    fq_webui:latest

if %errorlevel% equ 0 (
    echo ========================================
    echo fq_webui deployed successfully!
    echo Access at: http://localhost
    echo ========================================
) else (
    echo ========================================
    echo fq_webui deployment failed!
    echo ========================================
)
