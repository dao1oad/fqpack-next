import importlib.util
import sys
import types
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
        "fqnext_xt_account_sync_worker",
    ]


def test_ordered_surfaces_preserve_runtime_priority() -> None:
    module = load_module()

    ordered = module.ordered_surfaces(["tpsl", "market_data", "guardian"])

    assert ordered == ["market_data", "guardian", "tpsl"]


def test_unknown_surface_raises() -> None:
    module = load_module()

    with pytest.raises(ValueError, match="Unknown host deployment surface"):
        module.resolve_surface_programs(["unknown-surface"])


def test_resolve_target_programs_supports_restart_surfaces_without_program_arg() -> (
    None
):
    module = load_module()

    args = module.build_parser().parse_args(
        ["restart-surfaces", "--surface", "market_data", "--surface", "guardian"]
    )

    surfaces, programs = module.resolve_target_programs(args)

    assert surfaces == ["market_data", "guardian"]
    assert programs == [
        "fqnext_realtime_xtdata_producer",
        "fqnext_realtime_xtdata_consumer",
        "fqnext_xtdata_adj_refresh_worker",
        "fqnext_guardian_event",
    ]


def test_resolve_target_programs_supports_wait_settled_without_program_arg() -> None:
    module = load_module()

    args = module.build_parser().parse_args(
        ["wait-settled", "--surface", "market_data", "--surface", "guardian"]
    )

    surfaces, programs = module.resolve_target_programs(args)

    assert surfaces == ["market_data", "guardian"]
    assert programs == [
        "fqnext_realtime_xtdata_producer",
        "fqnext_realtime_xtdata_consumer",
        "fqnext_xtdata_adj_refresh_worker",
        "fqnext_guardian_event",
    ]


def test_resolve_effective_timeout_applies_market_data_floor() -> None:
    module = load_module()

    effective_timeout = module.resolve_effective_timeout_seconds(
        "restart-surfaces",
        ["market_data"],
        45,
    )

    assert effective_timeout == 180.0


def test_resolve_effective_timeout_applies_tpsl_floor() -> None:
    module = load_module()

    effective_timeout = module.resolve_effective_timeout_seconds(
        "restart-surfaces",
        ["tpsl"],
        45,
    )

    assert effective_timeout == 90.0


def test_resolve_effective_timeout_applies_order_management_floor() -> None:
    module = load_module()

    effective_timeout = module.resolve_effective_timeout_seconds(
        "restart-surfaces",
        ["order_management"],
        45,
    )

    assert effective_timeout == 120.0


def test_resolve_effective_timeout_keeps_requested_timeout_for_non_market_data() -> (
    None
):
    module = load_module()

    effective_timeout = module.resolve_effective_timeout_seconds(
        "restart-surfaces",
        ["guardian"],
        45,
    )

    assert effective_timeout == 45.0


def test_wait_for_state_accepts_exited_when_waiting_for_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    states = iter(
        [
            {"statename": "RUNNING", "pid": 1},
            {"statename": "EXITED", "pid": 0},
        ]
    )
    server = types.SimpleNamespace()

    def fake_get_process_info(_server, _name):
        return next(states)

    monkeypatch.setattr(module, "get_process_info", fake_get_process_info)

    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    info = module.wait_for_state(
        server,
        "fqnext_realtime_xtdata_producer",
        "STOPPED",
        timeout_seconds=2,
    )

    assert info["statename"] == "EXITED"


def test_wait_for_programs_settled_waits_for_stable_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    iteration = {"value": 0}
    now = {"value": 0.0}
    snapshots = [
        {
            "producer": {"statename": "EXITED", "pid": 0, "start": 1, "stop": 2},
            "consumer": {"statename": "EXITED", "pid": 0, "start": 1, "stop": 2},
        },
        {
            "producer": {"statename": "STARTING", "pid": 101, "start": 3, "stop": 0},
            "consumer": {"statename": "STARTING", "pid": 202, "start": 3, "stop": 0},
        },
        {
            "producer": {"statename": "RUNNING", "pid": 101, "start": 3, "stop": 0},
            "consumer": {"statename": "RUNNING", "pid": 202, "start": 3, "stop": 0},
        },
        {
            "producer": {"statename": "RUNNING", "pid": 101, "start": 3, "stop": 0},
            "consumer": {"statename": "RUNNING", "pid": 202, "start": 3, "stop": 0},
        },
        {
            "producer": {"statename": "RUNNING", "pid": 101, "start": 3, "stop": 0},
            "consumer": {"statename": "RUNNING", "pid": 202, "start": 3, "stop": 0},
        },
    ]
    name_map = {
        "fqnext_realtime_xtdata_producer": "producer",
        "fqnext_realtime_xtdata_consumer": "consumer",
    }

    def fake_get_process_info(_server, name):
        snapshot = snapshots[min(iteration["value"], len(snapshots) - 1)]
        return snapshot[name_map[name]]

    def fake_sleep(seconds):
        now["value"] += seconds
        iteration["value"] += 1

    monkeypatch.setattr(module, "get_process_info", fake_get_process_info)
    monkeypatch.setattr(module.time, "sleep", fake_sleep)
    monkeypatch.setattr(module.time, "time", lambda: now["value"])

    snapshot = module.wait_for_programs_settled(
        object(),
        [
            "fqnext_realtime_xtdata_producer",
            "fqnext_realtime_xtdata_consumer",
        ],
        timeout_seconds=10,
        settle_seconds=2.0,
        poll_interval_seconds=1.0,
    )

    assert snapshot["fqnext_realtime_xtdata_producer"]["statename"] == "RUNNING"
    assert snapshot["fqnext_realtime_xtdata_consumer"]["statename"] == "RUNNING"


def test_restart_programs_retries_start_when_first_attempt_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    start_calls: list[tuple[str, bool]] = []
    running_wait_calls = {"value": 0}
    process_infos = iter(
        [
            {"statename": "RUNNING", "pid": 11},
            {"statename": "EXITED", "pid": 0},
        ]
    )

    server = types.SimpleNamespace(
        supervisor=types.SimpleNamespace(
            stopProcess=lambda _name, _wait: True,
            startProcess=None,
        )
    )

    def fake_start_process(name: str, wait: bool) -> bool:
        start_calls.append((name, wait))
        return True

    server.supervisor.startProcess = fake_start_process

    monkeypatch.setattr(
        module, "get_process_info", lambda _server, _name: next(process_infos)
    )

    def fake_wait_for_state(_server, _name, expected_state, timeout_seconds=0):
        if expected_state == "STOPPED":
            return {"statename": "EXITED", "pid": 0}
        running_wait_calls["value"] += 1
        if running_wait_calls["value"] == 1:
            raise RuntimeError(
                "Program fqnext_realtime_xtdata_producer did not reach RUNNING; last state=Exited"
            )
        return {"statename": "RUNNING", "pid": 22}

    monkeypatch.setattr(module, "wait_for_state", fake_wait_for_state)
    monkeypatch.setattr(
        module,
        "wait_for_programs_settled",
        lambda _server, _programs, timeout_seconds=0, settle_seconds=0, poll_interval_seconds=0: {
            "fqnext_realtime_xtdata_producer": {"statename": "EXITED", "pid": 0}
        },
    )

    results = module.restart_programs(
        server,
        ["fqnext_realtime_xtdata_producer"],
        timeout_seconds=5,
    )

    assert start_calls == [
        ("fqnext_realtime_xtdata_producer", False),
        ("fqnext_realtime_xtdata_producer", False),
    ]
    assert results == [
        {
            "name": "fqnext_realtime_xtdata_producer",
            "before_state": "RUNNING",
            "after_state": "RUNNING",
            "pid": 22,
        }
    ]


def test_restart_programs_reconciles_remaining_programs_before_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    start_calls: list[tuple[str, bool]] = []
    process_infos = {
        "fqnext_xtquant_broker": {"statename": "RUNNING", "pid": 11},
        "fqnext_xt_account_sync_worker": {"statename": "RUNNING", "pid": 22},
    }
    server = types.SimpleNamespace(
        supervisor=types.SimpleNamespace(
            stopProcess=lambda _name, _wait: True,
            startProcess=None,
        )
    )

    def fake_start_process(name: str, wait: bool) -> bool:
        start_calls.append((name, wait))
        return True

    def fake_get_process_info(_server, name):
        return process_infos[name]

    def fake_wait_for_state(_server, name, expected_state, timeout_seconds=0):
        if expected_state == "STOPPED":
            return {"statename": "EXITED", "pid": 0}
        if name == "fqnext_xtquant_broker":
            raise RuntimeError(
                "Program fqnext_xtquant_broker did not reach RUNNING; last state=Exited"
            )
        return {"statename": "RUNNING", "pid": 222}

    def fake_wait_for_programs_settled(
        _server,
        programs,
        timeout_seconds=0,
        settle_seconds=0,
        poll_interval_seconds=0,
    ):
        return {
            program: {
                "statename": (
                    "EXITED" if program == "fqnext_xtquant_broker" else "RUNNING"
                ),
                "pid": 0 if program == "fqnext_xtquant_broker" else 222,
            }
            for program in programs
        }

    server.supervisor.startProcess = fake_start_process
    monkeypatch.setattr(module, "get_process_info", fake_get_process_info)
    monkeypatch.setattr(module, "wait_for_state", fake_wait_for_state)
    monkeypatch.setattr(
        module, "wait_for_programs_settled", fake_wait_for_programs_settled
    )

    with pytest.raises(RuntimeError, match="fqnext_xtquant_broker") as excinfo:
        module.restart_programs(
            server,
            ["fqnext_xtquant_broker", "fqnext_xt_account_sync_worker"],
            timeout_seconds=5,
        )

    assert start_calls == [
        ("fqnext_xtquant_broker", False),
        ("fqnext_xtquant_broker", False),
        ("fqnext_xt_account_sync_worker", False),
    ]
    assert "fqnext_xt_account_sync_worker" in str(excinfo.value)
