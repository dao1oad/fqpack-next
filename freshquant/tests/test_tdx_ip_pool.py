"""QUANTAXIS 侧 TDX IP 池加载器(QAIPPool)的单元测试。

直接从源码文件加载模块, 避免触发 QUANTAXIS 包的重量级 __init__。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = (
    _REPO_ROOT / "sunflower" / "QUANTAXIS" / "QUANTAXIS" / "QAUtil" / "QAIPPool.py"
)
_POOL_PATH = _REPO_ROOT / "freshquant" / "gateway" / "tdx_ip_pool.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("qa_ip_pool_under_test", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repo_pool_file_exists_and_loads():
    module = _load_module()
    stock_hosts = module.load_tdx_ip_pool("stock", pool_path=str(_POOL_PATH))
    future_hosts = module.load_tdx_ip_pool("future", pool_path=str(_POOL_PATH))
    assert stock_hosts, "repo tdx_ip_pool.json must provide stock hosts"
    assert future_hosts, "repo tdx_ip_pool.json must provide future hosts"
    for host in stock_hosts + future_hosts:
        assert host["ip"]
        assert isinstance(host["port"], int)


def test_locate_pool_file_resolves_repo_json():
    module = _load_module()
    located = module.locate_tdx_ip_pool_file()
    assert located is not None
    assert Path(located).resolve() == _POOL_PATH.resolve()


def test_load_pool_defaults_port_and_keeps_name(tmp_path):
    module = _load_module()
    pool_file = tmp_path / "pool.json"
    pool_file.write_text(
        json.dumps(
            {
                "stock": [
                    {"ip": "1.2.3.4"},
                    {"ip": "5.6.7.8", "port": "7719", "name": "华东主站"},
                    {"ip": ""},
                    "not-a-dict",
                ]
            }
        ),
        encoding="utf-8",
    )
    hosts = module.load_tdx_ip_pool("stock", pool_path=str(pool_file))
    assert hosts == [
        {"ip": "1.2.3.4", "port": 7709},
        {"ip": "5.6.7.8", "port": 7719, "name": "华东主站"},
    ]


def test_load_pool_returns_none_for_missing_or_bad_input(tmp_path):
    module = _load_module()
    assert module.load_tdx_ip_pool("stock", pool_path=str(tmp_path / "none.json")) is (
        None
    )
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{not json", encoding="utf-8")
    assert module.load_tdx_ip_pool("stock", pool_path=str(bad_file)) is None
    empty_file = tmp_path / "empty.json"
    empty_file.write_text(json.dumps({"stock": []}), encoding="utf-8")
    assert module.load_tdx_ip_pool("stock", pool_path=str(empty_file)) is None
