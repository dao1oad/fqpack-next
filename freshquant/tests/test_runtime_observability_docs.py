from pathlib import Path


def test_runtime_observability_docs_reference_clickhouse_query_path() -> None:
    module_doc = Path("docs/current/modules/runtime-observability.md").read_text(
        encoding="utf-8"
    )
    runtime_doc = Path("docs/current/runtime.md").read_text(encoding="utf-8")
    deployment_doc = Path("docs/current/deployment.md").read_text(encoding="utf-8")
    troubleshooting_doc = Path("docs/current/troubleshooting.md").read_text(
        encoding="utf-8"
    )

    assert "ClickHouse" in module_doc
    assert "runtime indexer" in module_doc
    assert "fq_runtime_clickhouse" in deployment_doc
    assert "fq_runtime_indexer" in deployment_doc
    assert "ClickHouse" in runtime_doc
    assert "ClickHouse" in troubleshooting_doc
