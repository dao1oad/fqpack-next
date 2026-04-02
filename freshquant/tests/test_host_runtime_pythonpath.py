from pathlib import Path


def test_supervisord_example_targets_deploy_mirror_pythonpath() -> None:
    config = Path("deployment/examples/supervisord.fqnext.example.conf").read_text(
        encoding="utf-8"
    )

    assert (
        "PYTHONPATH="
        "D:/fqpack/freshquant-2026.2.23/.worktrees/main-deploy-production;"
        "D:/fqpack/freshquant-2026.2.23/.worktrees/main-deploy-production/morningglory/fqxtrade;"
        "D:/fqpack/freshquant-2026.2.23/.worktrees/main-deploy-production/sunflower/QUANTAXIS"
    ) in config
    assert (
        "D:/fqpack/freshquant-2026.2.23/.worktrees/main-deploy-production/.venv/Scripts/python.exe"
        in config
    )


def test_configuration_docs_call_out_vendored_quantaxis_pythonpath() -> None:
    configuration = Path("docs/current/configuration.md").read_text(encoding="utf-8")

    assert (
        "若本地要复现同一模式，优先保证 `PYTHONPATH` 指向仓库源码、"
        "`morningglory/fqxtrade` 与 `sunflower/QUANTAXIS`"
    ) in configuration


def test_readme_calls_out_supervisor_uses_deploy_mirror_venv() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "main-deploy-production" in readme
    assert r".worktrees\main-deploy-production\.venv\Scripts\python.exe" in readme
