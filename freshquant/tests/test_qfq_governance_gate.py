from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def load_module():
    module_path = Path("script/qfq_governance_gate.py")
    spec = importlib.util.spec_from_file_location("qfq_governance_gate", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def deployment_context(module, tmp_path: Path, *, sha: str = "a" * 40):
    return module.DeploymentContext(
        repo_root=str(tmp_path),
        head_sha=sha,
        origin_main_sha=sha,
        deployed_sha=sha,
        deployed_at="2026-07-23T00:00:00Z",
        latest_run_dir=None,
        state_path=str(tmp_path / "production-state.json"),
        formal_deploy_root=str(tmp_path / "formal-deploy"),
    )


def test_deployment_identity_requires_head_origin_and_deployed_sha_to_match(
    tmp_path: Path,
) -> None:
    module = load_module()
    context = deployment_context(module, tmp_path)

    assert module.deployment_identity_failures(context) == []

    mismatched = module.DeploymentContext(
        **{**context.as_dict(), "origin_main_sha": "b" * 40}
    )
    assert any(
        "HEAD, origin/main and deployed SHA differ" in failure
        for failure in module.deployment_identity_failures(mismatched)
    )

    assert "evidence has no deployed SHA" in module._check_identity(
        {"finishedAt": "2026-07-23T00:00:01Z"},
        context,
        require_after=True,
    )


def test_result_must_finish_after_latest_deploy(tmp_path: Path) -> None:
    module = load_module()
    context = deployment_context(module, tmp_path)

    module.assert_after_latest_deploy("2026-07-23T00:00:01Z", context)
    with pytest.raises(module.GateError, match="must be later"):
        module.assert_after_latest_deploy("2026-07-23T00:00:00Z", context)


def test_bootstrap_persists_clean_deployment_bound_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    context = deployment_context(module, tmp_path)
    monkeypatch.setattr(
        module, "load_deployment_context", lambda *args, **kwargs: context
    )
    calls: list[dict[str, object]] = []

    def sync(**kwargs):
        calls.append(kwargs)
        return {
            "ready": True,
            "source": "xtdata_preclose",
            "writer": "freshquant.market_data.xtdata.qfq",
            "by_scope": {
                "stock": {
                    "failed": 0,
                    "published": True,
                    "ready": "ready",
                    "audit": {
                        "ok": True,
                        "missing": 0,
                        "extra": 0,
                        "invalid": 0,
                        "duplicates": 0,
                    },
                },
                "etf": {
                    "failed": 0,
                    "published": True,
                    "ready": "ready",
                    "audit": {
                        "ok": True,
                        "missing": 0,
                        "extra": 0,
                        "invalid": 0,
                        "duplicates": 0,
                    },
                },
            },
        }

    result = module.run_bootstrap(
        scope="stock,etf",
        full=True,
        verify=True,
        evidence_root=tmp_path,
        require_deployed_main=True,
        require_after_latest_deploy=True,
        sync_callable=sync,
    )

    assert result["ok"] is True
    assert calls[0]["incremental"] is False
    assert calls[0]["scope"] == "stock,etf"
    evidence = json.loads(
        (tmp_path / "qfq-bootstrap-real.json").read_text(encoding="utf-8")
    )
    assert evidence["deployedSha"] == "a" * 40
    assert evidence["finishedAt"] > evidence["deployedAt"]


def test_bootstrap_requires_source_writer_and_scope_audit() -> None:
    module = load_module()
    clean = {
        "ready": True,
        "source": "xtdata_preclose",
        "writer": "freshquant.market_data.xtdata.qfq",
        "by_scope": {
            "stock": {
                "failed": 0,
                "published": True,
                "ready": "ready",
                "audit": {
                    "ok": True,
                    "missing": 0,
                    "extra": 0,
                    "invalid": 0,
                    "duplicates": 0,
                },
            }
        },
    }

    missing_source = json.loads(json.dumps(clean))
    missing_source.pop("source")
    assert "bootstrap source is not xtdata_preclose" in module._bootstrap_result_is_clean(
        missing_source, ["stock"]
    )

    missing_writer = json.loads(json.dumps(clean))
    missing_writer.pop("writer")
    assert "bootstrap writer is not canonical" in module._bootstrap_result_is_clean(
        missing_writer, ["stock"]
    )

    missing_audit = json.loads(json.dumps(clean))
    missing_audit["by_scope"]["stock"].pop("audit")
    assert "stock factor audit is missing" in module._bootstrap_result_is_clean(
        missing_audit, ["stock"]
    )


def test_verify_rejects_stale_deployment_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    context = deployment_context(module, tmp_path)
    monkeypatch.setattr(
        module, "load_deployment_context", lambda *args, **kwargs: context
    )
    (tmp_path / "qfq-bootstrap-real.json").write_text(
        json.dumps(
            {
                "ok": True,
                "deployedSha": "a" * 40,
                "finishedAt": "2026-07-22T23:59:59Z",
            }
        ),
        encoding="utf-8",
    )

    result = module.run_verify(
        checks="qfq",
        evidence_root=tmp_path,
        require_after_latest_deploy=True,
    )

    assert result["ok"] is False
    assert any("finishedAt must be later" in item for item in result["failures"])


def test_bootstrap_rejects_index_scope() -> None:
    module = load_module()

    with pytest.raises(module.GateError, match="only stock and/or etf"):
        module.run_bootstrap(
            scope="index",
            full=True,
            verify=True,
            sync_callable=lambda **kwargs: {},
        )


def test_market_jobs_evidence_requires_both_checks_and_all_jobs() -> None:
    module = load_module()
    payload = {
        "checks": ["dagster", "coverage"],
        "results": {
            "dagster": {
                "passed": True,
                "details": {
                    "jobs": {
                        name: [{"run_id": f"run-{name}"}]
                        for name in module.MARKET_JOB_NAMES
                    }
                },
            },
            "coverage": {"passed": True},
        },
    }
    assert module._market_jobs_evidence_failures(payload) == []

    coverage_only = json.loads(json.dumps(payload))
    coverage_only["checks"] = ["coverage"]
    assert any(
        "must include dagster and coverage" in failure
        for failure in module._market_jobs_evidence_failures(coverage_only)
    )

    missing_index_job = json.loads(json.dumps(payload))
    missing_index_job["results"]["dagster"]["details"]["jobs"][
        "index_data_job"
    ] = []
    assert any(
        "index_data_job" in failure
        for failure in module._market_jobs_evidence_failures(missing_index_job)
    )


def test_coverage_only_verify_does_not_publish_market_jobs_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    context = deployment_context(module, tmp_path)
    monkeypatch.setattr(
        module, "load_deployment_context", lambda *args, **kwargs: context
    )
    monkeypatch.setattr(
        module,
        "_check_coverage_runtime",
        lambda *args, **kwargs: {"passed": True, "details": {}, "failures": []},
    )

    result = module.run_verify(checks="coverage", evidence_root=tmp_path)

    assert result["ok"] is True
    assert Path(result["evidencePath"]).name == "verify-coverage.json"
    assert not (tmp_path / "market-jobs-real.json").exists()


def test_cleanup_requires_main_clean_worktree_and_no_issue_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    context = deployment_context(module, tmp_path)
    Path(context.state_path).write_text(
        json.dumps({"last_success_sha": context.deployed_sha}), encoding="utf-8"
    )

    def fake_git(_repo_root, *args):
        if args == ("branch", "--show-current"):
            return "codex/issue-467-xtdata-qfq-governance"
        if args[:2] == ("status", "--porcelain=v1"):
            return " M freshquant/data/stock.py"
        if args and args[0] == "for-each-ref":
            return "main\ncodex/issue-467-xtdata-qfq-governance"
        raise AssertionError(args)

    monkeypatch.setattr(module, "run_git", fake_git)
    result = module._check_cleanup(context)

    assert result["passed"] is False
    assert any("requires main branch" in failure for failure in result["failures"])
    assert any("worktree is not clean" in failure for failure in result["failures"])
    assert any("branch refs remain" in failure for failure in result["failures"])
