# coding:utf-8
"""从 freshquant 仓库内人工维护的 TDX IP 池加载行情服务器列表。

权威来源是 ``freshquant/gateway/tdx_ip_pool.json``(随代码分发, 机器无关)。
加载成功时 QASetting 跳过 ``~/.quantaxis/setting/*_ip.json`` 用户目录缓存,
避免陈旧缓存把失效服务器带回选点流程。

定位顺序:
1. 仓库布局推导(vendored 源码运行, 零导入副作用):
   本文件位于 ``<repo>/sunflower/QUANTAXIS/QUANTAXIS/QAUtil/``,
   池文件位于 ``<repo>/freshquant/gateway/``;
2. ``find_spec("freshquant.gateway")`` 回退(wheel/site-packages 安装形态,
   会触发 ``freshquant`` 包初始化)。
"""

import importlib.util
import json
import os

_DEFAULT_PORTS = {"stock": 7709, "future": 7727}
_POOL_FILENAME = "tdx_ip_pool.json"


def _locate_by_repo_layout():
    here = os.path.abspath(__file__)
    # QAUtil -> QUANTAXIS(pkg) -> QUANTAXIS(dist) -> sunflower -> repo root
    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(here))))
    )
    candidate = os.path.join(repo_root, "freshquant", "gateway", _POOL_FILENAME)
    if os.path.exists(candidate):
        return candidate
    return None


def _locate_by_import_spec():
    try:
        spec = importlib.util.find_spec("freshquant.gateway")
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    for root in spec.submodule_search_locations:
        candidate = os.path.join(str(root), _POOL_FILENAME)
        if os.path.exists(candidate):
            return candidate
    return None


def locate_tdx_ip_pool_file():
    """返回 tdx_ip_pool.json 的绝对路径, 找不到时返回 None。"""
    return _locate_by_repo_layout() or _locate_by_import_spec()


def load_tdx_ip_pool(kind, pool_path=None):
    """加载指定类型("stock"/"future")的服务器列表。

    返回 [{"ip": str, "port": int, ...}] 或 None(池不可用时,
    调用方应回退到原有加载逻辑)。
    """
    path = pool_path or locate_tdx_ip_pool_file()
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            pool = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(pool, dict):
        return None

    default_port = _DEFAULT_PORTS.get(kind, 7709)
    hosts = []
    for item in pool.get(kind) or []:
        if not isinstance(item, dict):
            continue
        ip = str(item.get("ip") or "").strip()
        if not ip:
            continue
        try:
            port = int(item.get("port") or default_port)
        except (TypeError, ValueError):
            port = default_port
        host = {"ip": ip, "port": port}
        name = str(item.get("name") or "").strip()
        if name:
            host["name"] = name
        hosts.append(host)
    return hosts or None
