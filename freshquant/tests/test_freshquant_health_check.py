from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_module():
    module_path = REPO_ROOT / "script" / "freshquant_health_check.py"
    spec = importlib.util.spec_from_file_location("freshquant_health_check", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_resolve_check_urls_uses_surface_targets_and_deduplicates() -> None:
    module = load_module()

    urls = module.resolve_check_urls(
        surfaces=["web,api", "web"],
        extra_urls=[
            "http://127.0.0.1:18080/",
            "http://127.0.0.1:9999/custom",
        ],
    )

    assert urls == [
        "http://127.0.0.1:15000/api/runtime/components",
        "http://127.0.0.1:15000/api/runtime/health/summary",
        "http://127.0.0.1:15000/api/gantt/plates?provider=xgb",
        "http://127.0.0.1:18080/",
        "http://127.0.0.1:18080/gantt/shouban30",
        "http://127.0.0.1:18080/runtime-observability",
        "http://127.0.0.1:9999/custom",
    ]


def test_build_opener_disables_proxy_resolution() -> None:
    module = load_module()

    opener = module.build_opener()
    handler_names = [handler.__class__.__name__ for handler in opener.handlers]

    assert "ProxyHandler" not in handler_names


def test_run_health_checks_retries_until_success(monkeypatch) -> None:
    module = load_module()
    attempts = {"http://127.0.0.1:18080/": 0}

    def fake_fetch_status(url: str, timeout_seconds: float, opener):
        assert timeout_seconds == 3
        assert opener == "fake-opener"
        attempts[url] += 1
        if attempts[url] == 1:
            return 503
        return 200

    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    results = module.run_health_checks(
        ["http://127.0.0.1:18080/"],
        timeout_seconds=3,
        retries=2,
        retry_delay_seconds=0,
        opener="fake-opener",
        fetch_status=fake_fetch_status,
    )

    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].status_code == 200
    assert results[0].attempts == 2
    assert results[0].error is None


def test_run_health_checks_records_failure_after_retries(monkeypatch) -> None:
    module = load_module()

    def fake_fetch_status(url: str, timeout_seconds: float, opener):
        raise OSError("connection refused")

    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    results = module.run_health_checks(
        ["http://127.0.0.1:18080/runtime-observability"],
        timeout_seconds=3,
        retries=2,
        retry_delay_seconds=0,
        opener="fake-opener",
        fetch_status=fake_fetch_status,
    )

    assert len(results) == 1
    assert results[0].ok is False
    assert results[0].status_code is None
    assert results[0].attempts == 2
    assert "connection refused" in results[0].error


def test_main_outputs_json_and_returns_nonzero_for_failure(
    monkeypatch, capsys
) -> None:
    module = load_module()

    monkeypatch.setattr(
        module,
        "resolve_check_urls",
        lambda surfaces, extra_urls: ["http://127.0.0.1:18080/"],
    )
    monkeypatch.setattr(
        module,
        "run_health_checks",
        lambda urls, **kwargs: [
            module.HealthCheckResult(
                url=urls[0],
                ok=False,
                status_code=503,
                attempts=3,
                error="unexpected status: 503",
            )
        ],
    )

    exit_code = module.main(["--surface", "web", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["passed"] is False
    assert payload["checks"][0]["status_code"] == 503
    assert payload["failures"] == ["http://127.0.0.1:18080/"]
