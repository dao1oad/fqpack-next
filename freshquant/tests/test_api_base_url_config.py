from __future__ import annotations

import importlib


def test_get_api_base_url_uses_bootstrap_file(tmp_path, monkeypatch):
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    bootstrap_file.write_text(
        "api:\n  base_url: http://127.0.0.1:19999\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))

    import freshquant.bootstrap_config as bootstrap_module
    import freshquant.util.url as url_module

    bootstrap_module = importlib.reload(bootstrap_module)
    url_module = importlib.reload(url_module)

    assert bootstrap_module.bootstrap_config.api.base_url == "http://127.0.0.1:19999"
    assert url_module.get_api_base_url() == "http://127.0.0.1:19999"
