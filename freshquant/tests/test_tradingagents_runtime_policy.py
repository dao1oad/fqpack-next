from pathlib import Path


def test_tradingagents_sources_and_runtime_assets_are_retired() -> None:
    for path in (
        Path("third_party/tradingagents-cn"),
        Path("docker/tradingagents"),
        Path("runtime/tradingagents-cn"),
        Path("docs/current/modules/tradingagents-cn.md"),
    ):
        assert not path.exists(), path


def test_tradingagents_services_ports_and_data_contract_are_absent() -> None:
    compose = Path("docker/compose.parallel.yaml").read_text(encoding="utf-8")

    for forbidden in (
        "ta_backend",
        "ta_frontend",
        "ta_tunnel",
        "13000",
        "13080",
        "tradingagents_cn",
        "runtime/tradingagents-cn",
    ):
        assert forbidden not in compose


def test_qa_and_quantaxis_contract_remains_present() -> None:
    compose = Path("docker/compose.parallel.yaml").read_text(encoding="utf-8")

    assert "fq_qawebserver:" in compose
    assert '"18010:8010"' in compose
    assert Path("sunflower/QUANTAXIS").is_dir()
