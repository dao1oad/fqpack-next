@echo off
setlocal enabledelayedexpansion

call clean.bat

xmake

pushd "%CD%\python"
call conda activate py39
python -m pip install build && python -m build --wheel
call conda activate py310
python -m pip install build && python -m build --wheel
call conda activate py311
python -m pip install build && python -m build --wheel
call conda activate py312
python -m pip install build && python -m build --wheel
call conda deactivate
popd

docker run --rm -v "%cd%:/fqchan01" -w /fqchan01/python ^
  -e PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple ^
  -e PIP_TRUSTED_HOST=mirrors.aliyun.com ^
  python:3.9-bookworm ^
  sh -c "python -m pip install build && python -m build --wheel"
docker run --rm -v "%cd%":/fqchan01 -w /fqchan01/python ^
  -e PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple ^
  -e PIP_TRUSTED_HOST=mirrors.aliyun.com ^
  python:3.10-bookworm ^
  sh -c "python -m pip install build && python -m build --wheel"
docker run --rm -v "%cd%":/fqchan01 -w /fqchan01/python ^
  -e PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple ^
  -e PIP_TRUSTED_HOST=mirrors.aliyun.com ^
  python:3.11-bookworm ^
  sh -c "python -m pip install build && python -m build --wheel"
docker run --rm -v "%cd%":/fqchan01 -w /fqchan01/python ^
  -e PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple ^
  -e PIP_TRUSTED_HOST=mirrors.aliyun.com ^
  python:3.12-bookworm ^
  sh -c "python -m pip install build && python -m build --wheel"

call package.bat
pushd "%CD%\python"
call package.bat
popd

endlocal
