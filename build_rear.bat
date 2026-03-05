@echo off
cd /d "%~dp0"

docker build -t fq_rear -f docker/Dockerfile.rear .