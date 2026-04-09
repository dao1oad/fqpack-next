from pathlib import Path


def test_supervisord_example_targets_canonical_repo_root_pythonpath() -> None:
    config = Path("deployment/examples/supervisord.fqnext.example.conf").read_text(
        encoding="utf-8"
    )

    assert (
        "PYTHONPATH="
        "D:/fqpack/freshquant-2026.2.23;"
        "D:/fqpack/freshquant-2026.2.23/morningglory/fqxtrade;"
        "D:/fqpack/freshquant-2026.2.23/sunflower/QUANTAXIS"
    ) in config
    assert "D:/fqpack/freshquant-2026.2.23/.venv/Scripts/python.exe" in config


def test_configuration_docs_call_out_vendored_quantaxis_pythonpath() -> None:
    configuration = Path("docs/current/configuration.md").read_text(encoding="utf-8")

    assert "`PYTHONPATH`" in configuration
    assert "morningglory/fqxtrade" in configuration
    assert "sunflower/QUANTAXIS" in configuration
    assert "Canonical Main Supervisor Truth" in configuration


def test_readme_calls_out_supervisor_uses_canonical_repo_root_venv() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "Canonical Main Deploy Truth" in readme
    assert r"D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe" in readme
    assert "origin/main" in readme
