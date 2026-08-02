from __future__ import annotations

from collections.abc import Mapping

from freshquant.market_data.xtdata import qfq_worker


def _get(document, path):
    value = document
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def _set(document, path, value):
    target = document
    parts = path.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def _matches(document, query):
    for key, expected in query.items():
        value = _get(document, key)
        if isinstance(expected, Mapping) and "$in" in expected:
            if value not in expected["$in"]:
                return False
        elif value != expected:
            return False
    return True


class _Result:
    matched_count = 1


class _Collection:
    def __init__(self, rows=()):
        self.rows = [dict(row) for row in rows]

    def find_one(self, query, projection=None, sort=None):
        rows = [row for row in self.rows if _matches(row, query)]
        for field, direction in reversed(sort or []):
            rows.sort(key=lambda row: _get(row, field), reverse=direction < 0)
        if not rows:
            return None
        row = dict(rows[0])
        if projection:
            row = {key: value for key, value in row.items() if projection.get(key, 1)}
        return row

    def update_one(self, query, update, upsert=False):
        for row in self.rows:
            if _matches(row, query):
                for path, value in update.get("$set", {}).items():
                    _set(row, path, value)
                return _Result()
        result = _Result()
        result.matched_count = 0
        return result


class _DB:
    def __init__(self, **collections):
        self.collections = {
            name: _Collection(rows) for name, rows in collections.items()
        }

    def __getitem__(self, name):
        return self.collections.setdefault(name, _Collection())


def _marker(*, scope="stock", active="a", asof="2026-01-02", inactive_status="ready"):
    prefix = "stock" if scope == "stock" else "etf"
    return {
        "scope": scope,
        "active_slot": active,
        "slots": {
            "a": {
                "collection": f"{prefix}_adj_qfq_a",
                "snapshot_id": "snapshot-a",
                "factor_asof": asof,
                "status": "ready" if active == "a" else inactive_status,
                "published_at": "2026-01-02T08:00:00Z",
            },
            "b": {
                "collection": f"{prefix}_adj_qfq_b",
                "snapshot_id": "snapshot-b",
                "factor_asof": asof,
                "status": "ready" if active == "b" else inactive_status,
                "published_at": "2026-01-02T08:00:00Z",
            },
        },
        "source": "xtdata_preclose",
        "schema_version": 1,
    }


def test_worker_consumes_latest_success_marker_for_each_scope():
    marker_db = _DB(
        dagster_pipeline_markers=[
            {
                "pipeline_key": "stock_postclose_ready",
                "trade_date": "2026-01-05",
                "status": "failed",
            },
            {
                "pipeline_key": "stock_postclose_ready",
                "trade_date": "2026-01-02",
                "status": "success",
            },
            {
                "pipeline_key": "etf_postclose_ready",
                "trade_date": "2026-01-03",
                "status": "success",
            },
        ]
    )
    calls = []

    def sync_fn(**kwargs):
        calls.append(kwargs)
        return {"ready": True}

    factor_db = _DB(
        qfq_ready=[
            _marker(scope="stock", asof="2026-01-01"),
            _marker(scope="etf", asof="2026-01-01"),
        ]
    )

    result = qfq_worker.run_pending_once(
        marker_db=marker_db,
        factor_db=factor_db,
        sync_fn=sync_fn,
    )

    assert [(call["scope"], call["target_date"]) for call in calls] == [
        ("stock", "2026-01-02"),
        ("etf", "2026-01-03"),
    ]
    assert result["by_scope"]["stock"]["status"] == "published"


def test_worker_skips_scope_when_active_snapshot_is_current():
    marker_db = _DB(
        dagster_pipeline_markers=[
            {
                "pipeline_key": "stock_postclose_ready",
                "trade_date": "2026-01-02",
                "status": "success",
            }
        ]
    )
    factor_db = _DB(qfq_ready=[_marker()])

    result = qfq_worker.run_pending_once(
        scopes=["stock"],
        marker_db=marker_db,
        factor_db=factor_db,
        sync_fn=lambda **kwargs: (_ for _ in ()).throw(AssertionError("unexpected")),
    )

    assert result["by_scope"]["stock"] == {
        "status": "current",
        "factor_asof": "2026-01-02",
    }


def test_worker_delegates_interrupted_build_recovery_to_locked_sync():
    marker_db = _DB(
        dagster_pipeline_markers=[
            {
                "pipeline_key": "stock_postclose_ready",
                "trade_date": "2026-01-05",
                "status": "success",
            }
        ]
    )
    factor_db = _DB(qfq_ready=[_marker(inactive_status="building")])
    observed = []

    def sync_fn(**kwargs):
        observed.append(factor_db["qfq_ready"].rows[0]["slots"]["b"]["status"])
        return {"ready": True}

    qfq_worker.run_pending_once(
        scopes=["stock"],
        marker_db=marker_db,
        factor_db=factor_db,
        sync_fn=sync_fn,
    )

    assert observed == ["building"]


def test_worker_delegates_interrupted_build_even_when_active_is_current():
    marker_db = _DB(
        dagster_pipeline_markers=[
            {
                "pipeline_key": "stock_postclose_ready",
                "trade_date": "2026-01-02",
                "status": "success",
            }
        ]
    )
    factor_db = _DB(qfq_ready=[_marker(inactive_status="building")])
    calls = []

    qfq_worker.run_pending_once(
        scopes=["stock"],
        marker_db=marker_db,
        factor_db=factor_db,
        sync_fn=lambda **kwargs: calls.append(kwargs) or {"ready": True},
    )

    assert len(calls) == 1


def test_worker_waits_when_bfq_marker_is_missing():
    called = []
    result = qfq_worker.run_pending_once(
        scopes=["stock"],
        marker_db=_DB(),
        factor_db=_DB(),
        sync_fn=lambda **kwargs: called.append(kwargs),
    )
    assert not called
    assert result["by_scope"]["stock"]["status"] == "waiting_for_bfq"


def test_worker_requires_manual_bootstrap_when_qfq_marker_is_missing():
    marker_db = _DB(
        dagster_pipeline_markers=[
            {
                "pipeline_key": "stock_postclose_ready",
                "trade_date": "2026-01-05",
                "status": "success",
            }
        ]
    )
    called = []

    result = qfq_worker.run_pending_once(
        scopes=["stock"],
        marker_db=marker_db,
        factor_db=_DB(),
        sync_fn=lambda **kwargs: called.append(kwargs),
    )

    assert not called
    assert result["by_scope"]["stock"] == {
        "status": "bootstrap_required",
        "target_date": "2026-01-05",
    }


def test_worker_scope_failure_does_not_block_other_scope():
    marker_db = _DB(
        dagster_pipeline_markers=[
            {
                "pipeline_key": "stock_postclose_ready",
                "trade_date": "2026-01-05",
                "status": "success",
            },
            {
                "pipeline_key": "etf_postclose_ready",
                "trade_date": "2026-01-05",
                "status": "success",
            },
        ]
    )
    calls = []

    def sync_fn(**kwargs):
        calls.append(kwargs["scope"])
        if kwargs["scope"] == "stock":
            raise RuntimeError("stock sync failed")
        return {"ready": True}

    factor_db = _DB(
        qfq_ready=[
            _marker(scope="stock", asof="2026-01-01"),
            _marker(scope="etf", asof="2026-01-01"),
        ]
    )

    result = qfq_worker.run_pending_once(
        marker_db=marker_db,
        factor_db=factor_db,
        sync_fn=sync_fn,
    )

    assert calls == ["stock", "etf"]
    assert result["by_scope"]["stock"]["status"] == "error"
    assert result["by_scope"]["etf"]["status"] == "published"


def test_worker_once_returns_nonzero_when_any_scope_errors(monkeypatch, capsys):
    monkeypatch.setattr(
        qfq_worker,
        "run_pending_once",
        lambda **_kwargs: {
            "by_scope": {
                "stock": {"status": "error", "error": "sync failed"},
                "etf": {"status": "published"},
            }
        },
    )

    assert qfq_worker.main(["worker", "--once"]) == 1
    assert '"status": "error"' in capsys.readouterr().out


def test_build_full_passes_force_full_rebuild(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        qfq_worker,
        "sync_qfq_factors",
        lambda **kwargs: calls.append(kwargs) or {"ready": True},
    )

    assert (
        qfq_worker.main(
            [
                "build",
                "--scope",
                "stock",
                "--target-date",
                "2026-01-05",
                "--full",
            ]
        )
        == 0
    )
    assert calls[0]["force_full_rebuild"] is True
    assert '"ready": true' in capsys.readouterr().out


def test_strict_status_reports_active_snapshot_lag():
    marker_db = _DB(
        dagster_pipeline_markers=[
            {
                "pipeline_key": "stock_postclose_ready",
                "trade_date": "2026-01-05",
                "status": "success",
            }
        ]
    )
    factor_db = _DB(qfq_ready=[_marker(asof="2026-01-02")])

    result = qfq_worker.qfq_readiness_status(
        scopes=["stock"], marker_db=marker_db, factor_db=factor_db
    )

    assert result["ready"] is False
    assert result["by_scope"]["stock"]["status"] == "stale"


def test_status_strict_returns_nonzero_when_shadow_is_not_ready(monkeypatch, capsys):
    monkeypatch.setattr(
        qfq_worker,
        "qfq_readiness_status",
        lambda **_kwargs: {
            "ready": False,
            "by_scope": {"stock": {"status": "missing_qfq_marker"}},
        },
    )

    assert qfq_worker.main(["status", "--scope", "stock", "--strict"]) == 1
    assert '"ready": false' in capsys.readouterr().out


def test_audit_full_passes_source_loader_and_single_code(monkeypatch, capsys):
    calls = []
    client = type(
        "Client",
        (),
        {
            "load_daily_bars": lambda *args, **kwargs: None,
            "load_front_ratio_bars": lambda *args, **kwargs: None,
            "load_listing_metadata": lambda *args, **kwargs: None,
        },
    )()
    monkeypatch.setattr(qfq_worker, "XtDataQfqClient", lambda: client)
    monkeypatch.setattr(
        qfq_worker,
        "get_qfq_marker",
        lambda **_kwargs: _marker(),
    )
    monkeypatch.setattr(
        qfq_worker,
        "audit_qfq_slot",
        lambda **kwargs: calls.append(kwargs) or {"ok": True},
    )

    assert (
        qfq_worker.main(
            [
                "audit",
                "--scope",
                "stock",
                "--mode",
                "full",
                "--code",
                "000001",
            ]
        )
        == 0
    )
    assert calls[0]["codes"] == ["000001"]
    assert calls[0]["bars_loader"] is not None
    assert calls[0]["front_ratio_loader"] is not None
    assert calls[0]["listing_date_loader"] is not None
    assert calls[0]["source_tail_days"] is None
    assert '"ok": true' in capsys.readouterr().out


def test_audit_structure_passes_only_shared_client_listing_loader(monkeypatch, capsys):
    calls = []
    client = type(
        "Client",
        (),
        {
            "load_daily_bars": lambda *args, **kwargs: None,
            "load_front_ratio_bars": lambda *args, **kwargs: None,
            "load_listing_metadata": lambda *args, **kwargs: {
                "open_date": "1993-08-09",
                "is_trading": True,
            },
        },
    )()
    monkeypatch.setattr(qfq_worker, "XtDataQfqClient", lambda: client)
    monkeypatch.setattr(qfq_worker, "get_qfq_marker", lambda **_kwargs: _marker())
    monkeypatch.setattr(
        qfq_worker,
        "audit_qfq_slot",
        lambda **kwargs: calls.append(kwargs) or {"ok": True},
    )

    assert qfq_worker.main(["audit", "--scope", "stock"]) == 0
    assert calls[0]["bars_loader"] is None
    assert calls[0]["front_ratio_loader"] is None
    assert calls[0]["listing_date_loader"] is not None
    assert '"ok": true' in capsys.readouterr().out
