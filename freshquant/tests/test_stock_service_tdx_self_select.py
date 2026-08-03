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

    def find(self, query=None, projection=None):
        return list(self.docs)


def test_decode_tdx_self_select_code_accepts_tdx_and_plain_codes():
    assert stock_service.decode_tdx_self_select_code("0300127") == "300127"
    assert stock_service.decode_tdx_self_select_code("1600000") == "600000"
    assert stock_service.decode_tdx_self_select_code("2830799") == "830799"
    assert stock_service.decode_tdx_self_select_code("300127") == "300127"
    assert stock_service.decode_tdx_self_select_code("1000001") is None
    assert stock_service.decode_tdx_self_select_code("bad") is None


def test_read_tdx_self_select_codes_dedupes_gbk_file(tmp_path):
    target = Path(tmp_path) / "T0002" / "blocknew" / "ZXG.blk"
    target.parent.mkdir(parents=True)
    target.write_text("0300127\n0300127\n1600000\nBAD\n", encoding="gbk")

    assert stock_service.read_tdx_self_select_codes(tdx_home=tmp_path) == [
        "300127",
        "600000",
    ]


def test_sync_stock_pools_from_tdx_self_select_appends_without_duplicate(
    monkeypatch, tmp_path
):
    target = Path(tmp_path) / "T0002" / "blocknew" / "ZXG.blk"
    target.parent.mkdir(parents=True)
    target.write_text("0300127\n000001\n000002\n000001\n", encoding="gbk")
    collection = FakeStockPoolsCollection([{"code": "300127", "category": "已有"}])
    fake_db = {
        "stock_pools": collection,
        "xt_positions": FakeStockPoolsCollection(),
    }

    def fake_save_a_stock_pools(code, **kwargs):
        if code == "000002":
            return
        collection.insert_one({"code": code, "category": kwargs.get("category")})

    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    monkeypatch.setattr(stock_service, "save_a_stock_pools", fake_save_a_stock_pools)

    result = stock_service.sync_stock_pools_from_tdx_self_select(
        tdx_home=tmp_path,
        days=15,
    )

    assert result["read_count"] == 3
    assert result["appended_codes"] == ["000001"]
    assert result["skipped_existing_codes"] == ["300127"]
    assert result["skipped_invalid_codes"] == ["000002"]
    assert collection.find_one({"code": "000001"})["category"] == "通达信自选股"


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

    def fake_save_a_stock_pools(code, **kwargs):
        collection.insert_one({"code": code, "category": kwargs.get("category")})

    monkeypatch.setattr(stock_service, "DBfreshquant", fake_db)
    monkeypatch.setattr(stock_service, "save_a_stock_pools", fake_save_a_stock_pools)

    result = stock_service.sync_stock_pools_from_tdx_self_select(
        tdx_home=tmp_path,
        days=15,
    )

    assert result["appended_codes"] == ["000002"]
    assert result["skipped_holding_codes"] == ["300127", "000001"]
    assert result["skipped_holding_count"] == 2
    assert collection.find_one({"code": "300127"}) is None
    assert collection.find_one({"code": "000001"}) is None
