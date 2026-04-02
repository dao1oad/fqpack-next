from pathlib import Path


def test_host_runtime_ctl_references_supervisor_service_and_bridge() -> None:
    text = Path("script/fqnext_host_runtime_ctl.ps1").read_text(encoding="utf-8")

    assert "fqnext-supervisord" in text
    assert "fqnext-supervisord-restart" in text
    assert "EnsureServiceAndRestartSurfaces" in text


def test_host_runtime_ctl_normalizes_comma_separated_surfaces() -> None:
    text = Path("script/fqnext_host_runtime_ctl.ps1").read_text(encoding="utf-8")

    assert "Normalize-DeploymentSurfaces" in text
    assert "-split ','" in text


def test_host_runtime_ctl_waits_for_settled_surfaces_after_service_recovery() -> None:
    text = Path("script/fqnext_host_runtime_ctl.ps1").read_text(encoding="utf-8")

    assert "wait-settled" in text
    assert "WasRecovered" in text


def test_host_runtime_ctl_can_reconcile_supervisor_config_to_repo_root() -> None:
    text = Path("script/fqnext_host_runtime_ctl.ps1").read_text(encoding="utf-8")

    assert "SupervisorConfigRepoRoot" in text
    assert "fqnext_supervisor_config.py" in text
    assert "Invoke-AdminBridgeRecovery" in text


def test_install_fqnext_supervisord_service_uses_delayed_auto_start() -> None:
    text = Path("script/install_fqnext_supervisord_service.ps1").read_text(
        encoding="utf-8"
    )

    assert "SERVICE_DELAYED_AUTO_START" in text
    assert "supervisord.fqnext.conf" in text


def test_restart_task_scripts_share_same_task_name() -> None:
    install_text = Path("script/install_fqnext_supervisord_restart_task.ps1").read_text(
        encoding="utf-8"
    )
    invoke_text = Path("script/invoke_fqnext_supervisord_restart_task.ps1").read_text(
        encoding="utf-8"
    )
    run_text = Path("script/run_fqnext_supervisord_restart_task.ps1").read_text(
        encoding="utf-8"
    )

    assert "fqnext-supervisord-restart" in install_text
    assert "fqnext-supervisord-restart" in invoke_text
    assert "fqnext-supervisord" in run_text
    assert "D:\\fqpack\\supervisord\\scripts" in install_text


def test_runtime_docs_reference_fqnext_supervisord_formal_entry() -> None:
    runtime_doc = Path("docs/current/runtime.md").read_text(encoding="utf-8")

    assert "fqnext-supervisord" in runtime_doc
    assert "http://127.0.0.1:10011/RPC2" in runtime_doc
