from __future__ import annotations

from pathlib import Path

from freshquant import stock_service


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
    }
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)

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
    assert collection.find_one({"code": "600999"}) is not None


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
    }
    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)

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
