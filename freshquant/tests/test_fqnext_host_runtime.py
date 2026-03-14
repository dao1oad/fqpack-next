import importlib.util
import sys
from pathlib import Path

import pytest


def load_module():
    module_path = Path("script/fqnext_host_runtime.py")
    spec = importlib.util.spec_from_file_location("fqnext_host_runtime", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_supervisor_rpc_url_reads_fqnext_port() -> None:
    module = load_module()
    config_text = Path("deployment/examples/supervisord.fqnext.example.conf").read_text(
        encoding="utf-8"
    )

    rpc_url = module.parse_supervisor_rpc_url(config_text)

    assert rpc_url == "http://127.0.0.1:10011/RPC2"


def test_parse_supervisor_rpc_url_tolerates_utf8_bom() -> None:
    module = load_module()
    config_text = "\ufeff[inet_http_server]\nport=127.0.0.1:10011\n"

    rpc_url = module.parse_supervisor_rpc_url(config_text)

    assert rpc_url == "http://127.0.0.1:10011/RPC2"


def test_resolve_surface_programs_expands_market_and_order_management() -> None:
    module = load_module()

    programs = module.resolve_surface_programs(["market_data", "order_management"])

    assert programs == [
        "fqnext_realtime_xtdata_producer",
        "fqnext_realtime_xtdata_consumer",
        "fqnext_xtdata_adj_refresh_worker",
        "fqnext_xtquant_broker",
        "fqnext_credit_subjects_worker",
    ]


def test_ordered_surfaces_preserve_runtime_priority() -> None:
    module = load_module()

    ordered = module.ordered_surfaces(["tpsl", "market_data", "guardian"])

    assert ordered == ["market_data", "guardian", "tpsl"]


def test_unknown_surface_raises() -> None:
    module = load_module()

    with pytest.raises(ValueError, match="Unknown host deployment surface"):
        module.resolve_surface_programs(["unknown-surface"])
