from __future__ import annotations

from pathlib import Path


def test_current_docs_describe_memory_layer_contract() -> None:
    runtime_text = Path("docs/current/runtime.md").read_text(encoding="utf-8")
    architecture_text = Path("docs/current/architecture.md").read_text(encoding="utf-8")
    configuration_text = Path("docs/current/configuration.md").read_text(
        encoding="utf-8"
    )
    troubleshooting_text = Path("docs/current/troubleshooting.md").read_text(
        encoding="utf-8"
    )

    assert "FQ_MEMORY_CONTEXT_PATH" in runtime_text
    assert "FQ_MEMORY_CONTEXT_ROLE" in runtime_text
    assert "fq_memory" in runtime_text
    assert ".codex/memory" in runtime_text
    assert "cleanup-requests" in runtime_text

    assert "冷记忆" in architecture_text
    assert "热记忆" in architecture_text
    assert "context pack" in architecture_text

    assert "FQ_MEMORY_CONTEXT_PATH" in configuration_text
    assert "FQ_MEMORY_CONTEXT_ROLE" in configuration_text

    assert "refresh_freshquant_memory.py" in troubleshooting_text
    assert "compile_freshquant_context_pack.py" in troubleshooting_text
    assert "FQ_MEMORY_CONTEXT_PATH" in troubleshooting_text
    assert "FQ_MEMORY_CONTEXT_ROLE" in troubleshooting_text
    assert "cleanup-requests" in troubleshooting_text
