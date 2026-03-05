@echo off
cd /d "%~dp0"

IF "%TDX_HOME%"=="" SET TDX_HOME=D:\KXG
SET /p TDX_HOME="Enter TDX_HOME ([default]=%TDX_HOME%): "

if exist "%TDX_HOME%\TdxW.exe" (
    echo Correct TDX Directory %TDX_HOME%
) else (
    echo Wrong TDX Directory %TDX_HOME%
    goto :EOF
)

SETX TDX_HOME %TDX_HOME%

IF "%FQ_PERSIST_DIR%"=="" SET FQ_PERSIST_DIR=D:\FQ_PERSIST_DIR
SET /p FQ_PERSIST_DIR="FQ_PERSIST_DIR ([default]=%FQ_PERSIST_DIR%): "

if exist "%FQ_PERSIST_DIR%" (
    echo Directory "%FQ_PERSIST_DIR%" exists. Continue to deploy.
) else (
    echo Directory "%FQ_PERSIST_DIR%" does not exist. Please create it by yourself first.
    goto :EOF
)

SETX FQ_PERSIST_DIR %FQ_PERSIST_DIR%

set DAGSTER_DIR=%FQ_PERSIST_DIR%\dagster_data
set NOTEBOOK_DIR=%FQ_PERSIST_DIR%\notebook_data
set FQ_DATA_DIR=%FQ_PERSIST_DIR%\fq_data

SET FQ_RUN_REAR_BUILD=N
SET /p FQ_RUN_REAR_BUILD="Whether run rear build? ([default]=%FQ_RUN_REAR_BUILD%, Y=Yes, N=No)"

if /I "%FQ_RUN_REAR_BUILD%"=="Y" (
    call build_rear.bat
)

docker network inspect "fq_network" >nul 2>&1
if %errorlevel% equ 0 (
    echo The network "fq_network" exists
) else (
    docker network create -d bridge --subnet 172.19.0.0/24 --gateway 172.19.0.1 fq_network
)

echo stop fq_rear containers
for /f "tokens=*" %%i in ('docker ps -a --format "{{.Names}}" ^| findstr /B "fq_" ^| findstr /V "fq_doc" ^| findstr /V "fq_gogs" ^| findstr /V "fq_redis" ^| findstr /V "fq_mongodb" ^| findstr /V "fq_webui"') do docker stop %%i

echo rm fq_rear containers
for /f "tokens=*" %%i in ('docker ps -a --format "{{.Names}}" ^| findstr /B "fq_" ^| findstr /V "fq_doc" ^| findstr /V "fq_gogs" ^| findstr /V "fq_redis" ^| findstr /V "fq_mongodb" ^| findstr /V "fq_webui"') do docker rm %%i

echo deploy fq_tdxhq
docker run -d --name fq_tdxhq --restart=always --network fq_network ^
    --log-driver=json-file --log-opt max-size=10m --log-opt max-file=3 ^
    --env-file .env ^
    -p 5001:5001 ^
    fq_rear:latest ^
    python -m freshquant.gateway.tdxhq --port 5001

xcopy /Y morningglory\fqdagsterconfig\* %DAGSTER_DIR%\home\

echo deploy fq_dagster_webserver
docker run -d --name fq_dagster_webserver --restart=always --network fq_network ^
    --log-driver=json-file --log-opt max-size=10m --log-opt max-file=3 ^
    --env-file .env ^
    -v %DAGSTER_DIR%:/opt/dagster ^
    -p 10003:10003 ^
    -w /opt/dagster/home ^
    fq_rear:latest ^
    dagster-webserver -h 0.0.0.0 -p 10003

echo deploy fq_guardian
docker run -d --name fq_guardian --restart=always --network fq_network ^
    --log-driver=json-file --log-opt max-size=10m --log-opt max-file=3 ^
    --env-file .env ^
    fq_rear:latest ^
    python -m freshquant.signal.astock.job.monitor_stock_zh_a_min

echo deploy fq_dagster_daemon
docker run -d --name fq_dagster_daemon --restart=always --network fq_network ^
    --log-driver=json-file --log-opt max-size=10m --log-opt max-file=3 ^
    --env-file .env ^
    -v %DAGSTER_DIR%:/opt/dagster ^
    -v %TDX_HOME%:/opt/tdx ^
    -w /opt/dagster/home ^
    fq_rear:latest ^
    dagster-daemon run

echo deploy fq_apiserver
docker run -d --name fq_apiserver --restart=always --network fq_network ^
    --log-driver=json-file --log-opt max-size=10m --log-opt max-file=3 ^
    --env-file .env ^
    -v %TDX_HOME%:/opt/tdx ^
    -p 5000:5000 ^
    fq_rear:latest ^
    python -m freshquant.rear.api_server

echo deploy fq_qawebserver
docker run -d --name fq_qawebserver --restart=always --network fq_network ^
    --log-driver=json-file --log-opt max-size=10m --log-opt max-file=3 ^
    --env-file .env ^
    -v %TDX_HOME%:/opt/tdx ^
    -p 8010:8010 ^
    fq_rear:latest ^
    python -m QUANTAXIS.QAWebServer.server

echo deploy fq_stock_cn_a_collector
docker run -d --name fq_stock_cn_a_collector --restart=always --network fq_network ^
    --log-driver=json-file --log-opt max-size=10m --log-opt max-file=3 ^
    --env-file .env ^
    fq_rear:latest ^
    python -m freshquant.market_data.stock_cn_a_collector

echo deploy fq_stock_cn_a_sina_tick_collector
docker run -d --name fq_stock_cn_a_sina_tick_collector --restart=always --network fq_network ^
    --log-driver=json-file --log-opt max-size=10m --log-opt max-file=3 ^
    --env-file .env ^
    fq_rear:latest ^
    python -m freshquant.market_data.stock_cn_a_sina_tick_collector

echo deploy fq_collect_future_zh_min
docker run -d --name fq_collect_future_zh_min --restart=always --network fq_network ^
    --log-driver=json-file --log-opt max-size=10m --log-opt max-file=3 ^
    --env-file .env ^
    fq_rear:latest ^
    python -m freshquant.data.future.job.collect_future_zh_min

echo deploy fq_huey_worker
docker run -d --name fq_huey_worker --restart=always --network fq_network ^
    --log-driver=json-file --log-opt max-size=10m --log-opt max-file=3 ^
    --env-file .env ^
    fq_rear:latest ^
    python -m freshquant.worker.consumer freshquant.worker.queue.huey -w 50

echo deploy fq_jupyter_lab
docker run -d --name fq_jupyter_lab --restart=always --network fq_network ^
    --log-driver=json-file --log-opt max-size=10m --log-opt max-file=3 ^
    --env-file .env ^
    -v %NOTEBOOK_DIR%:/opt/notebook ^
    -v %FQ_DATA_DIR%:/opt/data ^
    -p 8888:8888 ^
    fq_rear:latest ^
    jupyter lab --port 8888 --ip 0.0.0.0 --allow-root --no-browser --notebook-dir /opt/notebook

docker run --rm --name fq_initialize --network fq_network ^
    --log-driver=json-file --log-opt max-size=10m --log-opt max-file=3 ^
    --env-file .env ^
    fq_rear:latest ^
    python -m freshquant.initialize --quiet

echo restart fq_webui
docker restart fq_webui

echo.
echo All fq_rear containers deployed successfully!
