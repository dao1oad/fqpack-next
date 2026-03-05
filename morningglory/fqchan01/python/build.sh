#!/bin/bash
export PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
export PIP_TRUSTED_HOST=mirrors.aliyun.com
python -m pip install build
python -m build --wheel
