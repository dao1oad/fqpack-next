from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType


def _build_dagster_stub():
    module = ModuleType("dagster")

    class AssetExecutionContext:  # pragma: no cover - test stub only
        pass

    class _FakeAssetDef:
        def __init__(self, fn, name, group_name=None):
            self._fn = fn
            self.name = name
            self.group_name = group_name
            self.dependency_names = [
                name
                for name in fn.__code__.co_varnames[: fn.__code__.co_argcount]
                if name != "context"
            ]

        def __call__(self, *args, **kwargs):
            return self._fn(*args, **kwargs)

    def asset(fn=None, **kwargs):
        if fn is None:
            return lambda inner: _FakeAssetDef(
                inner,
                kwargs.get("name") or inner.__name__,
                group_name=kwargs.get("group_name"),
            )
        return _FakeAssetDef(
            fn,
            kwargs.get("name") or fn.__name__,
            group_name=kwargs.get("group_name"),
        )

    module.asset = asset
    module.AssetExecutionContext = AssetExecutionContext
    return module


def _import_postclose_ready_module(monkeypatch):
    project_root = Path(__file__).resolve().parents[2]
    project_src = project_root / "morningglory" / "fqdagster" / "src"
    monkeypatch.syspath_prepend(str(project_root))
    monkeypatch.syspath_prepend(str(project_src))
    monkeypatch.setitem(sys.modules, "dagster", _build_dagster_stub())
    assets_dir = project_src / "fqdagster" / "defs" / "assets"
    assets_package = ModuleType("fqdagster.defs.assets")
    assets_package.__path__ = [str(assets_dir)]
    monkeypatch.setitem(sys.modules, "fqdagster.defs.assets", assets_package)
    sys.modules.pop("fqdagster.defs.assets.postclose_ready", None)
    return importlib.import_module("fqdagster.defs.assets.postclose_ready")


def test_refresh_quality_stock_universe_snapshot_depends_on_stock_assets(monkeypatch):
    module = _import_postclose_ready_module(monkeypatch)

    assert module.refresh_quality_stock_universe_snapshot.dependency_names == [
        "stock_block",
        "stock_day",
    ]


def test_refresh_quality_stock_universe_snapshot_runs_once_and_returns_payload(
    monkeypatch,
):
    module = _import_postclose_ready_module(monkeypatch)
    calls = []

    monkeypatch.setattr(
        module,
        "resolve_latest_completed_trade_date",
        lambda: "2026-03-19",
    )
    monkeypatch.setattr(
        module,
        "refresh_quality_stock_universe",
        lambda: calls.append("called")
        or {
            "count": 23,
            "source_version": "xgt_hot_blocks_v1",
            "updated_at": "2026-03-19T16:02:00+00:00",
        },
    )

    payload = module.refresh_quality_stock_universe_snapshot(
        "2026-03-19 16:00:00",
        "2026-03-19 16:01:00",
    )

    assert calls == ["called"]
    assert payload == {
        "trade_date": "2026-03-19",
        "count": 23,
        "source_version": "xgt_hot_blocks_v1",
        "updated_at": "2026-03-19T16:02:00+00:00",
    }
