@echo off
cd /d "%~dp0"

uv venv --relocatable --python 3.12
uv add pip chardet
