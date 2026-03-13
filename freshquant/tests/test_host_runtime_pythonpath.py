from pathlib import Path


def test_supervisord_example_adds_vendored_quantaxis_to_pythonpath() -> None:
    config = Path("deployment/examples/supervisord.fqnext.example.conf").read_text(
        encoding="utf-8"
    )

    assert (
        "PYTHONPATH="
        "D:/fqpack/freshquant-2026.2.23;"
        "D:/fqpack/freshquant-2026.2.23/morningglory/fqxtrade;"
        "D:/fqpack/freshquant-2026.2.23/sunflower/QUANTAXIS"
    ) in config


def test_configuration_docs_call_out_vendored_quantaxis_pythonpath() -> None:
    configuration = Path("docs/current/configuration.md").read_text(encoding="utf-8")

    assert (
        "若本地要复现同一模式，优先保证 `PYTHONPATH` 指向仓库源码、"
        "`morningglory/fqxtrade` 与 `sunflower/QUANTAXIS`"
    ) in configuration
