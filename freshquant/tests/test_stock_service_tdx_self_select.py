from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from freshquant import stock_service
from freshquant.clx_daily_selection.tdx_export import _encode_blocknew_cfg_group


@pytest.fixture(autouse=True)
def _restore_pristine_stock_service():
    """其他测试会以 stub 依赖 reload stock_service 造成模块级污染；
    每个用例前后重载，恢复真实绑定，保证本文件自包含。"""
    importlib.reload(stock_service)
    yield
    importlib.reload(stock_service)


class FakeStockPoolsCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find_one(self, query):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None

    def insert_one(self, doc):
        self.docs.append(dict(doc))
        return object()

    def update_one(self, query, update, upsert=False):
        target = self.find_one(query)
        if target is None:
            if not upsert:
                return
            target = {}
            self.docs.append(target)
        for key, value in (update.get("$setOnInsert") or {}).items():
            if key not in target:
                target[key] = value
        target.update(update.get("$set") or {})

    def delete_one(self, query):
        for index, doc in enumerate(self.docs):
            if all(doc.get(key) == value for key, value in query.items()):
                self.docs.pop(index)
                return

    def find(self, query=None, projection=None):
        return list(self.docs)


def _write_blocknew_cfg(tmp_path, pairs):
    """Write a TDX blocknew.cfg using the shared 120-byte record encoder.

    Each record is 120 bytes: 50-byte GBK display name + 70-byte file name
    prefix (without the ``.blk`` extension), matching the canonical encoder in
    ``freshquant.clx_daily_selection.tdx_export``.
    """
    cfg_path = Path(tmp_path) / "T0002" / "blocknew" / "blocknew.cfg"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    raw = b"".join(
        _encode_blocknew_cfg_group(display_name, file_name)
        for display_name, file_name in pairs
    )
    cfg_path.write_bytes(raw)
    return cfg_path


def test_decode_tdx_self_select_code_accepts_tdx_and_plain_codes():
    assert stock_service.decode_tdx_self_select_code("0300127") == "300127"
    assert stock_service.decode_tdx_self_select_code("1600000") == "600000"
    assert stock_service.decode_tdx_self_select_code("2830799") == "830799"
    assert stock_service.decode_tdx_self_select_code("300127") == "300127"
    assert stock_service.decode_tdx_self_select_code("1000001") is None
    assert stock_service.decode_tdx_self_select_code("1113000") is None
    assert stock_service.decode_tdx_self_select_code("0123456") is None
    assert stock_service.decode_tdx_self_select_code("bad") is None


def test_read_tdx_self_select_codes_dedupes_gbk_file(tmp_path):
    target = Path(tmp_path) / "T0002" / "blocknew" / "ZXG.blk"
    target.parent.mkdir(parents=True)
    target.write_text("0300127\n0300127\n1600000\nBAD\n", encoding="gbk")

    assert stock_service.read_tdx_self_select_codes(tdx_home=tmp_path) == [
        "300127",
        "600000",
    ]


def test_sync_stock_pools_from_tdx_self_select_replaces_old_pool(monkeypatch, tmp_path):
    target = Path(tmp_path) / "T0002" / "blocknew" / "ZXG.blk"
    target.parent.mkdir(parents=True)
    target.write_text("0300127\n000001\n000002\n000001\n", encoding="gbk")
    collection = FakeStockPoolsCollection(
        [
            {"code": "300127", "category": "已有"},
            {"code": "600999", "category": "旧列表"},
        ]
    )
    fake_db = {
        "stock_pools": collection,
        "xt_positions": FakeStockPoolsCollection(),
    }

    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)

    result = stock_service.sync_stock_pools_from_tdx_self_select(
        tdx_home=tmp_path,
        days=15,
    )

    assert result["read_count"] == 3
    assert result["synced_codes"] == ["300127", "000001", "000002"]
    assert result["removed_codes"] == ["600999"]
    assert result["removed_count"] == 1
    assert result["skipped_invalid_codes"] == []
    assert collection.find_one({"code": "000001"})["category"] == "通达信自选股"
    assert collection.find_one({"code": "300127"})["category"] == "通达信自选股"
    assert collection.find_one({"code": "600999"}) is None


def test_sync_stock_pools_from_tdx_self_select_skips_current_holdings(
    monkeypatch, tmp_path
):
    target = Path(tmp_path) / "T0002" / "blocknew" / "ZXG.blk"
    target.parent.mkdir(parents=True)
    target.write_text("0300127\n000001\n000002\n", encoding="gbk")
    collection = FakeStockPoolsCollection([])
    fake_db = {
        "stock_pools": collection,
        "xt_positions": FakeStockPoolsCollection(
            [
                {"symbol": "sz300127"},
                {"stock_code": "000001.SZ"},
            ]
        ),
    }

    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)

    result = stock_service.sync_stock_pools_from_tdx_self_select(
        tdx_home=tmp_path,
        days=15,
    )

    assert result["synced_codes"] == ["000002"]
    assert result["skipped_holding_codes"] == ["300127", "000001"]
    assert result["skipped_holding_count"] == 2
    assert collection.find_one({"code": "300127"}) is None
    assert collection.find_one({"code": "000001"}) is None


def test_sync_stock_pools_from_tdx_self_select_skips_unsupported_securities(
    monkeypatch, tmp_path
):
    target = Path(tmp_path) / "T0002" / "blocknew" / "ZXG.blk"
    target.parent.mkdir(parents=True)
    target.write_text("113000\n123456\n900901\n0300127\n", encoding="gbk")
    collection = FakeStockPoolsCollection([])
    fake_db = {
        "stock_pools": collection,
        "xt_positions": FakeStockPoolsCollection(),
    }
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)

    result = stock_service.sync_stock_pools_from_tdx_self_select(
        tdx_home=tmp_path,
        days=15,
    )

    assert result["synced_codes"] == ["300127"]
    assert result["skipped_invalid_codes"] == ["113000", "123456", "900901"]


def test_sync_must_pool_from_tdx_self_select_reads_dai_mai_group(monkeypatch, tmp_path):
    target = Path(tmp_path) / "T0002" / "blocknew" / "待买.blk"
    target.parent.mkdir(parents=True)
    target.write_text("0300127\n000001\n000002\n113000\n", encoding="gbk")
    fake_db = {
        "stock_pools": FakeStockPoolsCollection(),
        "must_pool": FakeStockPoolsCollection(),
        "xt_positions": FakeStockPoolsCollection(),
        "params": FakeStockPoolsCollection(
            [{"code": "guardian", "value": {"stock": {"stop_loss_default": 9.5}}}]
        ),
        "instrument_strategy": FakeStockPoolsCollection(),
    }
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    monkeypatch.setattr(stock_service, "get_trade_amount", lambda code: 50000)

    calls = []
    monkeypatch.setattr(
        stock_service.must_pool,
        "import_pool",
        lambda **kwargs: calls.append(kwargs),
    )

    result = stock_service.sync_must_pool_from_tdx_self_select(tdx_home=tmp_path)

    assert result["file_name"] == "待买.blk"
    assert result["category"] == "待买"
    assert result["source"] == "tdx_must_pool"
    assert result["synced_codes"] == ["300127", "000001", "000002"]
    assert result["skipped_invalid_codes"] == ["113000"]
    assert [call["code"] for call in calls] == ["300127", "000001", "000002"]
    assert all(call["category"] == "待买" for call in calls)
    assert calls[0]["provenance"]["sources"] == ["tdx_must_pool"]
    assert calls[0]["provenance"]["categories"] == ["待买"]
    assert calls[0]["provenance"]["memberships"][0]["source"] == "tdx_must_pool"
    assert calls[0]["provenance"]["memberships"][0]["category"] == "待买"
    assert calls[0]["provenance"]["memberships"][0]["extra"]["file_name"] == "待买.blk"


def test_sync_must_pool_from_tdx_self_select_preserves_existing_params(
    monkeypatch, tmp_path
):
    target = Path(tmp_path) / "T0002" / "blocknew" / "待买.blk"
    target.parent.mkdir(parents=True)
    target.write_text("0300127\n", encoding="gbk")
    fake_db = {
        "stock_pools": FakeStockPoolsCollection(),
        "must_pool": FakeStockPoolsCollection(
            [
                {
                    "code": "300127",
                    "category": "人工",
                    "stop_loss_price": 9.8,
                    "initial_lot_amount": 80000,
                    "lot_amount": 50000,
                }
            ]
        ),
        "xt_positions": FakeStockPoolsCollection(),
    }
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)

    calls = []
    monkeypatch.setattr(
        stock_service.must_pool,
        "import_pool",
        lambda **kwargs: calls.append(kwargs),
    )

    result = stock_service.sync_must_pool_from_tdx_self_select(tdx_home=tmp_path)

    assert result["synced_codes"] == ["300127"]
    call = calls[0]
    assert call["code"] == "300127"
    assert call["stop_loss_price"] == 9.8
    assert call["initial_lot_amount"] == 80000
    assert call["lot_amount"] == 50000


def test_sync_must_pool_from_tdx_self_select_keeps_records_outside_group(
    monkeypatch, tmp_path
):
    target = Path(tmp_path) / "T0002" / "blocknew" / "待买.blk"
    target.parent.mkdir(parents=True)
    target.write_text("0300127\n", encoding="gbk")
    collection = FakeStockPoolsCollection(
        [
            {"code": "600999", "category": "人工"},
        ]
    )
    fake_db = {
        "stock_pools": FakeStockPoolsCollection(),
        "must_pool": collection,
        "xt_positions": FakeStockPoolsCollection(),
        "params": FakeStockPoolsCollection(
            [{"code": "guardian", "value": {"stock": {"stop_loss_default": 9.5}}}]
        ),
        "instrument_strategy": FakeStockPoolsCollection(),
    }
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    monkeypatch.setattr(stock_service, "get_trade_amount", lambda code: 50000)

    calls = []
    monkeypatch.setattr(
        stock_service.must_pool,
        "import_pool",
        lambda **kwargs: calls.append(kwargs),
    )

    result = stock_service.sync_must_pool_from_tdx_self_select(tdx_home=tmp_path)

    assert result["synced_codes"] == ["300127"]
    assert result["removed_codes"] == ["600999"]
    assert collection.find_one({"code": "600999"}) is None


def test_sync_must_pool_from_tdx_self_select_skips_current_holdings(
    monkeypatch, tmp_path
):
    target = Path(tmp_path) / "T0002" / "blocknew" / "待买.blk"
    target.parent.mkdir(parents=True)
    target.write_text("0300127\n000002\n", encoding="gbk")
    fake_db = {
        "stock_pools": FakeStockPoolsCollection(),
        "must_pool": FakeStockPoolsCollection(),
        "xt_positions": FakeStockPoolsCollection(
            [
                {"symbol": "sz300127"},
            ]
        ),
        "params": FakeStockPoolsCollection(
            [{"code": "guardian", "value": {"stock": {"stop_loss_default": 9.5}}}]
        ),
        "instrument_strategy": FakeStockPoolsCollection(),
    }
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    monkeypatch.setattr(stock_service, "get_trade_amount", lambda code: 50000)

    calls = []
    monkeypatch.setattr(
        stock_service.must_pool,
        "import_pool",
        lambda **kwargs: calls.append(kwargs),
    )

    result = stock_service.sync_must_pool_from_tdx_self_select(tdx_home=tmp_path)

    assert result["synced_codes"] == ["000002"]
    assert result["skipped_holding_codes"] == ["300127"]
    assert [call["code"] for call in calls] == ["000002"]


def test_read_tdx_blocknew_cfg_mapping_maps_display_to_file(tmp_path):
    _write_blocknew_cfg(tmp_path, [("待买", "DM"), ("clx_18", "CLX_18")])

    assert stock_service.read_tdx_blocknew_cfg_mapping(tdx_home=tmp_path) == {
        "待买": "DM",
        "clx_18": "CLX_18",
    }


def test_read_tdx_blocknew_cfg_mapping_missing_cfg_returns_empty(tmp_path):
    assert stock_service.read_tdx_blocknew_cfg_mapping(tdx_home=tmp_path) == {}


def test_resolve_tdx_block_filename_maps_display_to_file(tmp_path):
    _write_blocknew_cfg(tmp_path, [("待买", "DM")])

    assert stock_service.resolve_tdx_block_filename(tdx_home=tmp_path) == "DM.blk"


def test_resolve_tdx_block_filename_falls_back_without_cfg(tmp_path):
    assert stock_service.resolve_tdx_block_filename(tdx_home=tmp_path) == "待买.blk"


def test_sync_must_pool_reads_dai_mai_group_by_mapped_file(monkeypatch, tmp_path):
    _write_blocknew_cfg(tmp_path, [("待买", "DM")])
    target = Path(tmp_path) / "T0002" / "blocknew" / "DM.blk"
    target.write_text("0300127\n000001\n113000\n", encoding="gbk")
    fake_db = {
        "stock_pools": FakeStockPoolsCollection(),
        "must_pool": FakeStockPoolsCollection(),
        "xt_positions": FakeStockPoolsCollection(),
        "params": FakeStockPoolsCollection(
            [{"code": "guardian", "value": {"stock": {"stop_loss_default": 9.5}}}]
        ),
        "instrument_strategy": FakeStockPoolsCollection(),
    }
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    monkeypatch.setattr(stock_service, "get_trade_amount", lambda code: 50000)
    calls = []
    monkeypatch.setattr(
        stock_service.must_pool,
        "import_pool",
        lambda **kwargs: calls.append(kwargs),
    )

    result = stock_service.sync_must_pool_from_tdx_self_select(tdx_home=tmp_path)

    assert result["file_name"] == "DM.blk"
    assert result["category"] == "待买"
    assert result["source"] == "tdx_must_pool"
    assert result["synced_codes"] == ["300127", "000001"]
    assert result["skipped_invalid_codes"] == ["113000"]
    assert [call["code"] for call in calls] == ["300127", "000001"]
    assert calls[0]["provenance"]["memberships"][0]["extra"]["file_name"] == "DM.blk"


def test_sync_must_pool_accepts_explicit_filename_override(monkeypatch, tmp_path):
    target = Path(tmp_path) / "T0002" / "blocknew" / "other.blk"
    target.parent.mkdir(parents=True)
    target.write_text("0300127\n", encoding="gbk")
    fake_db = {
        "stock_pools": FakeStockPoolsCollection(),
        "must_pool": FakeStockPoolsCollection(),
        "xt_positions": FakeStockPoolsCollection(),
        "params": FakeStockPoolsCollection(
            [{"code": "guardian", "value": {"stock": {"stop_loss_default": 9.5}}}]
        ),
        "instrument_strategy": FakeStockPoolsCollection(),
    }
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    monkeypatch.setattr(stock_service, "get_trade_amount", lambda code: 50000)
    calls = []
    monkeypatch.setattr(
        stock_service.must_pool,
        "import_pool",
        lambda **kwargs: calls.append(kwargs),
    )

    result = stock_service.sync_must_pool_from_tdx_self_select(
        tdx_home=tmp_path,
        filename="other.blk",
    )

    assert result["file_name"] == "other.blk"
    assert result["synced_codes"] == ["300127"]


def test_sync_stock_pools_blocks_when_file_missing(monkeypatch, tmp_path):
    collection = FakeStockPoolsCollection([{"code": "300127", "category": "已有"}])
    fake_db = {
        "stock_pools": collection,
        "xt_positions": FakeStockPoolsCollection(),
    }
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)

    with pytest.raises(RuntimeError, match="不存在"):
        stock_service.sync_stock_pools_from_tdx_self_select(tdx_home=tmp_path)
    assert collection.find_one({"code": "300127"}) is not None


def test_sync_stock_pools_blocks_when_file_has_no_valid_codes(monkeypatch, tmp_path):
    target = Path(tmp_path) / "T0002" / "blocknew" / "ZXG.blk"
    target.parent.mkdir(parents=True)
    target.write_text("BAD\n\n", encoding="gbk")
    collection = FakeStockPoolsCollection([{"code": "300127", "category": "已有"}])
    fake_db = {
        "stock_pools": collection,
        "xt_positions": FakeStockPoolsCollection(),
    }
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)

    with pytest.raises(RuntimeError, match="没有有效代码"):
        stock_service.sync_stock_pools_from_tdx_self_select(tdx_home=tmp_path)
    assert collection.find_one({"code": "300127"}) is not None


def test_sync_must_pool_new_code_uses_system_default_params(monkeypatch, tmp_path):
    target = Path(tmp_path) / "T0002" / "blocknew" / "待买.blk"
    target.parent.mkdir(parents=True)
    target.write_text("0300127\n", encoding="gbk")
    fake_db = {
        "stock_pools": FakeStockPoolsCollection(),
        "must_pool": FakeStockPoolsCollection(),
        "xt_positions": FakeStockPoolsCollection(),
        "params": FakeStockPoolsCollection(
            [{"code": "guardian", "value": {"stock": {"stop_loss_default": 7.77}}}]
        ),
        "instrument_strategy": FakeStockPoolsCollection(),
    }
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    monkeypatch.setattr(stock_service, "get_trade_amount", lambda code: 60000)

    calls = []
    monkeypatch.setattr(
        stock_service.must_pool,
        "import_pool",
        lambda **kwargs: calls.append(kwargs),
    )

    result = stock_service.sync_must_pool_from_tdx_self_select(tdx_home=tmp_path)

    assert result["synced_codes"] == ["300127"]
    assert result["failed_codes"] == []
    call = calls[0]
    assert call["stop_loss_price"] == 7.77
    assert call["initial_lot_amount"] == 60000
    assert call["lot_amount"] == 60000


def test_sync_must_pool_new_code_without_default_stop_loss_fails_but_continues(
    monkeypatch, tmp_path
):
    target = Path(tmp_path) / "T0002" / "blocknew" / "待买.blk"
    target.parent.mkdir(parents=True)
    target.write_text("0300127\n000002\n", encoding="gbk")
    fake_db = {
        "stock_pools": FakeStockPoolsCollection(),
        "must_pool": FakeStockPoolsCollection(),
        "xt_positions": FakeStockPoolsCollection(),
        "params": FakeStockPoolsCollection(),
        "instrument_strategy": FakeStockPoolsCollection(),
    }
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    monkeypatch.setattr(stock_service, "get_trade_amount", lambda code: 60000)

    calls = []
    monkeypatch.setattr(
        stock_service.must_pool,
        "import_pool",
        lambda **kwargs: calls.append(kwargs),
    )

    result = stock_service.sync_must_pool_from_tdx_self_select(tdx_home=tmp_path)

    assert result["synced_codes"] == []
    assert result["failed_codes"] == [
        {"code": "300127", "reason": "默认止损/资金参数不可用"},
        {"code": "000002", "reason": "默认止损/资金参数不可用"},
    ]
    assert calls == []


def test_sync_stock_pools_second_run_is_idempotent(monkeypatch, tmp_path):
    target = Path(tmp_path) / "T0002" / "blocknew" / "ZXG.blk"
    target.parent.mkdir(parents=True)
    target.write_text("0300127\n000001\n", encoding="gbk")
    collection = FakeStockPoolsCollection([])
    fake_db = {
        "stock_pools": collection,
        "xt_positions": FakeStockPoolsCollection(),
    }
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)

    first = stock_service.sync_stock_pools_from_tdx_self_select(tdx_home=tmp_path)
    second = stock_service.sync_stock_pools_from_tdx_self_select(tdx_home=tmp_path)

    assert first["synced_codes"] == ["300127", "000001"]
    assert second["synced_codes"] == ["300127", "000001"]
    assert second["removed_codes"] == []
    assert sorted(doc["code"] for doc in collection.docs) == ["000001", "300127"]


def test_resolve_must_pool_default_params_uses_system_config(monkeypatch):
    fake_db = {
        "params": FakeStockPoolsCollection(
            [{"code": "guardian", "value": {"stock": {"stop_loss_default": 7.77}}}]
        ),
        "must_pool": FakeStockPoolsCollection(),
        "instrument_strategy": FakeStockPoolsCollection(),
    }
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    monkeypatch.setattr(stock_service, "get_trade_amount", lambda code: 60000)

    resolved = stock_service.resolve_must_pool_default_params("300127")

    assert resolved == {
        "stop_loss_price": 7.77,
        "initial_lot_amount": 60000,
        "lot_amount": 60000,
    }


def test_resolve_must_pool_default_params_returns_none_without_stop_loss_config(
    monkeypatch,
):
    fake_db = {
        "params": FakeStockPoolsCollection(),
        "must_pool": FakeStockPoolsCollection(),
        "instrument_strategy": FakeStockPoolsCollection(),
    }
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    monkeypatch.setattr(stock_service, "get_trade_amount", lambda code: 60000)

    assert stock_service.resolve_must_pool_default_params("300127") is None


def test_sync_must_pool_writes_default_params_into_stored_documents(
    monkeypatch, tmp_path
):
    target = Path(tmp_path) / "T0002" / "blocknew" / "待买.blk"
    target.parent.mkdir(parents=True)
    target.write_text("0300127\n", encoding="gbk")

    class AttrDB(dict):
        def __getattr__(self, name):
            return dict.__getitem__(self, name)

    fake_db = AttrDB(
        {
            "stock_pools": FakeStockPoolsCollection(),
            "must_pool": FakeStockPoolsCollection(),
            "xt_positions": FakeStockPoolsCollection(),
            "params": FakeStockPoolsCollection(
                [{"code": "guardian", "value": {"stock": {"stop_loss_default": 7.77}}}]
            ),
            "instrument_strategy": FakeStockPoolsCollection(),
        }
    )
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    monkeypatch.setattr(stock_service.must_pool, "DBfreshquant", fake_db)
    monkeypatch.setattr(
        stock_service.must_pool,
        "query_instrument_info",
        lambda code: {"name": "测试标的", "sec": "stock_cn"},
    )
    monkeypatch.setattr(stock_service, "get_trade_amount", lambda code: 60000)

    result = stock_service.sync_must_pool_from_tdx_self_select(tdx_home=tmp_path)

    assert result["synced_codes"] == ["300127"]
    assert result["failed_codes"] == []
    # 真实 must_pool.import_pool 必须把默认参数写入存储文档，而不是只停留在 UI 层
    stored = fake_db["must_pool"].find_one({"code": "300127"})
    assert stored is not None
    assert stored["stop_loss_price"] == 7.77
    assert stored["initial_lot_amount"] == 60000
    assert stored["lot_amount"] == 60000
