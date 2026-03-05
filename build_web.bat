@echo off
cd /d "%~dp0"

docker build -t fq_webui -f docker/Dockerfile.web .