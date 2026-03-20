from __future__ import annotations

from datetime import datetime


class FakeCollection:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs = [dict(doc) for doc in (docs or [])]

    def find(self, query=None):
        query = query or {}
        return [
            dict(doc)
            for doc in self.docs
            if all(doc.get(key) == value for key, value in query.items())
        ]

    def delete_many(self, query):
        before = len(self.docs)
        self.docs = [
            dict(doc)
            for doc in self.docs
            if not all(doc.get(key) == value for key, value in query.items())
        ]
        return type("DeleteResult", (), {"deleted_count": before - len(self.docs)})()

    def insert_one(self, document):
        self.docs.append(dict(document))
        return type("InsertResult", (), {"acknowledged": True})()

    def replace_one(self, query, document, upsert=False):
        for index, doc in enumerate(self.docs):
            if all(doc.get(key) == value for key, value in query.items()):
                self.docs[index] = dict(document)
                return type("ReplaceResult", (), {"matched_count": 1})()
        if upsert:
            self.docs.append(dict(document))
        return type("ReplaceResult", (), {"matched_count": 0})()


class FakeDB(dict):
    def __getitem__(self, name):
        return dict.__getitem__(self, name)


class BoollessDB(FakeDB):
    def __bool__(self):
        raise NotImplementedError(
            "Database objects do not implement truth value testing"
        )


def _make_service(docs: list[dict] | None = None):
    from freshquant.pre_pool_service import PrePoolService

    return PrePoolService(db=FakeDB(stock_pre_pools=FakeCollection(docs)))


def test_pre_pool_service_accepts_db_objects_without_bool_support():
    from freshquant.pre_pool_service import PrePoolService

    db = BoollessDB(stock_pre_pools=FakeCollection())

    service = PrePoolService(db=db)

    assert service.db is db
    assert service.collection is db["stock_pre_pools"]


def test_upsert_pre_pool_creates_single_row_for_new_code():
    service = _make_service()

    service.upsert_code(
        code="000001",
        name="alpha",
        symbol="sz000001",
        source="daily-screening",
        category="CLXS_10008",
        added_at=datetime(2026, 3, 20, 9, 31),
        expire_at=datetime(2026, 6, 16, 0, 0),
        extra={"screening_run_id": "run-1"},
        workspace_order=7,
    )

    rows = service.list_codes()

    assert len(rows) == 1
    assert rows[0]["code"] == "000001"
    assert rows[0]["name"] == "alpha"
    assert rows[0]["symbol"] == "sz000001"
    assert rows[0]["sources"] == ["daily-screening"]
    assert rows[0]["categories"] == ["CLXS_10008"]
    assert rows[0]["workspace_order"] == 7
    assert rows[0]["memberships"] == [
        {
            "source": "daily-screening",
            "category": "CLXS_10008",
            "added_at": datetime(2026, 3, 20, 9, 31),
            "expire_at": datetime(2026, 6, 16, 0, 0),
            "extra": {"screening_run_id": "run-1"},
        }
    ]


def test_upsert_pre_pool_merges_new_membership_into_existing_code():
    service = _make_service()

    service.upsert_code(
        code="000001",
        name="alpha",
        symbol="sz000001",
        source="daily-screening",
        category="CLXS_10008",
        added_at=datetime(2026, 3, 20, 9, 31),
        extra={"screening_run_id": "run-1"},
    )
    service.upsert_code(
        code="000001",
        name="alpha",
        symbol="sz000001",
        source="shouban30",
        category="plate:trade_date:2026-03-19",
        added_at=datetime(2026, 3, 20, 10, 5),
        extra={"plate_key": "trade_date:2026-03-19"},
        workspace_order=1,
    )

    rows = service.list_codes()

    assert len(rows) == 1
    row = rows[0]
    assert row["sources"] == ["daily-screening", "shouban30"]
    assert row["categories"] == ["CLXS_10008", "plate:trade_date:2026-03-19"]
    assert row["workspace_order"] == 1
    assert {(item["source"], item["category"]) for item in row["memberships"]} == {
        ("daily-screening", "CLXS_10008"),
        ("shouban30", "plate:trade_date:2026-03-19"),
    }


def test_upsert_pre_pool_is_idempotent_for_same_source_and_category():
    service = _make_service()

    service.upsert_code(
        code="000001",
        name="alpha",
        symbol="sz000001",
        source="daily-screening",
        category="CLXS_10008",
        added_at=datetime(2026, 3, 20, 9, 31),
        extra={"screening_run_id": "run-1"},
    )
    service.upsert_code(
        code="000001",
        name="alpha-2",
        symbol="sz000001",
        source="daily-screening",
        category="CLXS_10008",
        added_at=datetime(2026, 3, 20, 10, 5),
        extra={"screening_run_id": "run-2"},
    )

    rows = service.list_codes()

    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "alpha-2"
    assert row["sources"] == ["daily-screening"]
    assert row["categories"] == ["CLXS_10008"]
    assert row["memberships"] == [
        {
            "source": "daily-screening",
            "category": "CLXS_10008",
            "added_at": datetime(2026, 3, 20, 10, 5),
            "expire_at": None,
            "extra": {"screening_run_id": "run-2"},
        }
    ]


def test_delete_pre_pool_removes_entire_code_record():
    service = _make_service()

    service.upsert_code(
        code="000001",
        name="alpha",
        symbol="sz000001",
        source="daily-screening",
        category="CLXS_10008",
    )
    service.upsert_code(
        code="000002",
        name="beta",
        symbol="sz000002",
        source="shouban30",
        category="intersection",
    )

    deleted = service.delete_code("000001")

    assert deleted is True
    assert [row["code"] for row in service.list_codes()] == ["000002"]


def test_list_pre_pool_returns_unique_codes_with_sources_and_categories():
    service = _make_service(
        [
            {
                "code": "000001",
                "name": "alpha",
                "category": "CLXS_10008",
                "remark": "daily-screening:clxs",
                "datetime": datetime(2026, 3, 18, 0, 0),
                "expire_at": datetime(2026, 6, 16, 0, 0),
                "extra": {"screening_run_id": "run-1"},
            },
            {
                "code": "000001",
                "name": "alpha",
                "category": "CLXS_10004",
                "remark": "daily-screening:clxs",
                "datetime": datetime(2026, 3, 19, 0, 0),
                "expire_at": datetime(2026, 6, 17, 0, 0),
                "extra": {"screening_run_id": "run-2"},
            },
            {
                "code": "000001",
                "name": "alpha",
                "category": "三十涨停Pro预选",
                "datetime": datetime(2026, 3, 20, 7, 39),
                "extra": {
                    "shouban30_order": 0,
                    "shouban30_plate_key": "trade_date:2026-03-19",
                },
            },
            {
                "code": "000002",
                "name": "beta",
                "category": "manual_pick",
                "datetime": datetime(2026, 3, 20, 8, 0),
                "remark": "",
            },
        ]
    )

    rows = service.list_codes()

    assert [row["code"] for row in rows] == ["000001", "000002"]

    alpha = rows[0]
    assert alpha["sources"] == ["daily-screening", "shouban30"]
    assert alpha["categories"] == [
        "CLXS_10004",
        "CLXS_10008",
        "plate:trade_date:2026-03-19",
    ]
    assert alpha["workspace_order"] == 0
    assert {(item["source"], item["category"]) for item in alpha["memberships"]} == {
        ("daily-screening", "CLXS_10004"),
        ("daily-screening", "CLXS_10008"),
        ("shouban30", "plate:trade_date:2026-03-19"),
    }

    beta = rows[1]
    assert beta["sources"] == ["manual"]
    assert beta["categories"] == ["manual_pick"]
