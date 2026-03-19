from __future__ import annotations

from types import SimpleNamespace

import pytest

from freshquant.db import DBScreening


class SimpleCollection:
    def __init__(self, name: str, docs: list[dict] | None = None) -> None:
        self.name = name
        self.docs = [dict(doc) for doc in docs or []]

    def find(self, query=None):
        query = query or {}
        return [
            dict(doc)
            for doc in self.docs
            if all(doc.get(key) == value for key, value in query.items())
        ]

    def find_one(self, query=None):
        rows = self.find(query)
        return rows[0] if rows else None

    def replace_one(self, query, document, upsert=False):
        for index, doc in enumerate(self.docs):
            if all(doc.get(key) == value for key, value in query.items()):
                self.docs[index] = dict(document)
                return SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            self.docs.append(dict(document))
        return SimpleNamespace(matched_count=0, modified_count=0)

    def delete_many(self, query):
        before = len(self.docs)
        self.docs = [
            doc
            for doc in self.docs
            if not all(doc.get(key) == value for key, value in query.items())
        ]
        return SimpleNamespace(deleted_count=before - len(self.docs))

    def insert_many(self, documents, ordered=False):
        self.docs.extend(dict(doc) for doc in documents)
        return SimpleNamespace(inserted_ids=list(range(len(documents))))


class IndexableCollection(SimpleCollection):
    def __init__(self, name: str, docs: list[dict] | None = None) -> None:
        super().__init__(name, docs)
        self.created_indexes: list[dict] = []

    def create_index(self, keys, **kwargs):
        self.created_indexes.append(
            {
                "keys": list(keys),
                "unique": bool(kwargs.get("unique", False)),
                "name": kwargs.get("name"),
                "partial_filter_expression": kwargs.get(
                    "partialFilterExpression"
                ),
            }
        )


class DistinctableCollection(SimpleCollection):
    def distinct(self, field_name):
        return sorted({doc.get(field_name) for doc in self.docs})


class LegacyIndexedCollection(SimpleCollection):
    LEGACY_KEY_FIELDS = (
        "run_id",
        "scope",
        "stage",
        "code",
        "model_key",
        "period",
        "fire_time",
    )

    def insert_many(self, documents, ordered=False):
        existing = {
            tuple(doc.get(field) for field in self.LEGACY_KEY_FIELDS)
            for doc in self.docs
        }
        for document in documents:
            key = tuple(document.get(field) for field in self.LEGACY_KEY_FIELDS)
            if key in existing:
                raise AssertionError(f"legacy duplicate key: {key}")
            existing.add(key)
        return super().insert_many(documents, ordered=ordered)


class FakeDB(dict):
    def __getitem__(self, name):
        return dict.__getitem__(self, name)


def test_db_module_exposes_screening_database(monkeypatch, tmp_path):
    bootstrap_file = tmp_path / "freshquant_bootstrap.yaml"
    bootstrap_file.write_text(
        "\n".join(
            [
                "mongodb:",
                "  host: 127.0.0.1",
                "  port: 27027",
                "  db: freshquant_runtime",
                "  screening_db: unit_test_screening_db",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FRESHQUANT_BOOTSTRAP_FILE", str(bootstrap_file))

    import importlib

    import freshquant.bootstrap_config as bootstrap_module
    import freshquant.db as db_module

    bootstrap_module = importlib.reload(bootstrap_module)
    db_module = importlib.reload(db_module)

    assert bootstrap_module.bootstrap_config.mongodb.screening_db == (
        "unit_test_screening_db"
    )
    assert db_module.DBScreening.name == "unit_test_screening_db"
    assert db_module.get_db("screening") is db_module.DBScreening
    assert db_module.get_db("unit_test_screening_db") is db_module.DBScreening


def test_repository_uses_fqscreening_collections():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_runs=SimpleCollection("daily_screening_runs"),
        daily_screening_memberships=SimpleCollection("daily_screening_memberships"),
        daily_screening_stock_snapshots=SimpleCollection(
            "daily_screening_stock_snapshots"
        ),
    )

    repo = DailyScreeningRepository(db=fake_db)

    assert repo.runs.name == "daily_screening_runs"
    assert repo.memberships.name == "daily_screening_memberships"
    assert repo.stock_snapshots.name == "daily_screening_stock_snapshots"


def test_repository_builds_condition_key_indexes():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    repo = DailyScreeningRepository(db=FakeDB())
    specs = repo.index_specs()

    assert specs["daily_screening_memberships"][0]["keys"] == [
        ("scope_id", 1),
        ("code", 1),
        ("condition_key", 1),
    ]


def test_repository_upserts_snapshot_metrics_by_scope_and_code():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_stock_snapshots=SimpleCollection(
            "daily_screening_stock_snapshots"
        )
    )
    repo = DailyScreeningRepository(db=fake_db)

    repo.upsert_stock_snapshots(
        scope_id="trade_date:2026-03-18",
        trade_date="2026-03-18",
        snapshots=[
            {
                "code": "000001",
                "symbol": "sz000001",
                "name": "alpha",
                "higher_multiple": 2.5,
            }
        ],
    )

    assert fake_db["daily_screening_stock_snapshots"].docs[0] == {
        "scope_id": "trade_date:2026-03-18",
        "trade_date": "2026-03-18",
        "code": "000001",
        "symbol": "sz000001",
        "name": "alpha",
        "higher_multiple": 2.5,
    }


def test_repository_replaces_condition_memberships_by_scope_and_condition_key():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_memberships=SimpleCollection("daily_screening_memberships")
    )
    repo = DailyScreeningRepository(db=fake_db)

    repo.replace_condition_memberships(
        scope_id="trade_date:2026-03-18",
        condition_key="clxs",
        codes=[{"code": "000001", "name": "alpha"}],
    )

    assert fake_db["daily_screening_memberships"].docs == [
        {
            "scope_id": "trade_date:2026-03-18",
            "scope": "trade_date:2026-03-18",
            "run_id": "trade_date:2026-03-18",
            "condition_key": "clxs",
            "code": "000001",
            "stage": "clxs",
            "name": "alpha",
        }
    ]


def test_repository_condition_memberships_fill_legacy_identity_from_condition_key():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_memberships=SimpleCollection("daily_screening_memberships")
    )
    repo = DailyScreeningRepository(db=fake_db)

    repo.replace_condition_memberships(
        scope_id="trade_date:2026-03-18",
        condition_key="hot:45d",
        codes=[{"code": "000001", "name": "alpha"}],
    )
    repo.replace_condition_memberships(
        scope_id="trade_date:2026-03-18",
        condition_key="flag:quality_subject",
        codes=[{"code": "000002", "name": "beta"}],
    )
    repo.replace_condition_memberships(
        scope_id="trade_date:2026-03-18",
        condition_key="chanlun_period:30m",
        codes=[{"code": "000003", "name": "gamma"}],
    )

    assert fake_db["daily_screening_memberships"].docs == [
        {
            "scope_id": "trade_date:2026-03-18",
            "scope": "trade_date:2026-03-18",
            "run_id": "trade_date:2026-03-18",
            "condition_key": "hot:45d",
            "code": "000001",
            "name": "alpha",
            "stage": "shouban30_agg90",
            "model_key": "hot",
            "period": "45d",
        },
        {
            "scope_id": "trade_date:2026-03-18",
            "scope": "trade_date:2026-03-18",
            "run_id": "trade_date:2026-03-18",
            "condition_key": "flag:quality_subject",
            "code": "000002",
            "name": "beta",
            "stage": "market_flags",
            "model_key": "quality_subject",
            "signal_type": "quality_subject",
            "signal_name": "quality_subject",
        },
        {
            "scope_id": "trade_date:2026-03-18",
            "scope": "trade_date:2026-03-18",
            "run_id": "trade_date:2026-03-18",
            "condition_key": "chanlun_period:30m",
            "code": "000003",
            "name": "gamma",
            "stage": "chanlun",
            "model_key": "period",
            "period": "30m",
        },
    ]


def test_repository_condition_memberships_do_not_conflict_with_legacy_unique_identity():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_memberships=LegacyIndexedCollection(
            "daily_screening_memberships"
        )
    )
    repo = DailyScreeningRepository(db=fake_db)

    repo.replace_condition_memberships(
        scope_id="trade_date:2026-03-18",
        condition_key="cls:S0001",
        codes=[{"code": "000010", "name": "alpha"}],
    )
    repo.replace_condition_memberships(
        scope_id="trade_date:2026-03-18",
        condition_key="hot:45d",
        codes=[{"code": "000010", "name": "alpha"}],
    )
    repo.replace_condition_memberships(
        scope_id="trade_date:2026-03-18",
        condition_key="hot:60d",
        codes=[{"code": "000010", "name": "alpha"}],
    )

    assert len(fake_db["daily_screening_memberships"].docs) == 3


def test_repository_query_scope_stocks_strips_mongo_internal_id():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_stock_snapshots=SimpleCollection(
            "daily_screening_stock_snapshots",
            docs=[
                {
                    "_id": object(),
                    "scope_id": "trade_date:2026-03-18",
                    "code": "000001",
                    "name": "alpha",
                }
            ],
        )
    )
    repo = DailyScreeningRepository(db=fake_db)

    rows = repo.query_scope_stocks(scope="trade_date:2026-03-18")

    assert rows == [
        {
            "scope_id": "trade_date:2026-03-18",
            "code": "000001",
            "name": "alpha",
        }
    ]


def test_repository_lists_distinct_scope_ids_from_memberships_and_snapshots():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_memberships=DistinctableCollection(
            "daily_screening_memberships",
            docs=[
                {"scope_id": "trade_date:2026-03-18", "code": "000001"},
                {"scope_id": "trade_date:2026-03-17", "code": "000002"},
            ],
        ),
        daily_screening_stock_snapshots=DistinctableCollection(
            "daily_screening_stock_snapshots",
            docs=[
                {"scope_id": "trade_date:2026-03-18", "code": "000001"},
                {"scope_id": "run:legacy", "code": "000003"},
            ],
        ),
    )
    repo = DailyScreeningRepository(db=fake_db)

    assert repo.list_scope_ids(prefix="trade_date:") == [
        "trade_date:2026-03-18",
        "trade_date:2026-03-17",
    ]


def test_repository_preserves_legacy_membership_metadata_while_replacing_by_scope_and_condition_key():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_memberships=SimpleCollection("daily_screening_memberships")
    )
    repo = DailyScreeningRepository(db=fake_db)

    repo.replace_stage_memberships(
        run_id="run-1",
        stage="clxs",
        scope="scope-a",
        memberships=[
            {
                "code": "000001",
                "name": "alpha",
                "symbol": "sz000001",
                "branch": "clxs",
                "model_key": "buy_zs_huila",
                "signal_type": "buy_zs_huila",
                "signal_name": "buy_zs_huila",
                "period": "30m",
                "fire_time": "2026-03-18T09:30:00+08:00",
            }
        ],
    )
    repo.replace_stage_memberships(
        run_id="run-1",
        stage="clxs",
        scope="scope-a",
        memberships=[
            {
                "code": "000001",
                "name": "alpha-2",
                "symbol": "sz000001",
                "branch": "clxs",
                "model_key": "buy_zs_huila_v2",
                "signal_type": "buy_zs_huila",
                "signal_name": "buy_zs_huila_v2",
                "period": "60m",
                "fire_time": "2026-03-18T10:30:00+08:00",
            }
        ],
    )

    assert fake_db["daily_screening_memberships"].docs == [
        {
            "scope_id": "scope-a",
            "condition_key": "clxs",
            "code": "000001",
            "stage": "clxs",
            "name": "alpha-2",
            "symbol": "sz000001",
            "branch": "clxs",
            "model_key": "buy_zs_huila_v2",
            "signal_type": "buy_zs_huila",
            "signal_name": "buy_zs_huila_v2",
            "period": "60m",
            "fire_time": "2026-03-18T10:30:00+08:00",
        }
    ]


def test_repository_ensure_indexes_calls_create_index_with_expected_contract():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    repo = DailyScreeningRepository(
        db=FakeDB(
            daily_screening_runs=IndexableCollection("daily_screening_runs"),
            daily_screening_memberships=IndexableCollection(
                "daily_screening_memberships"
            ),
            daily_screening_stock_snapshots=IndexableCollection(
                "daily_screening_stock_snapshots"
            ),
        )
    )

    repo.ensure_indexes()

    assert repo.runs.created_indexes == [
        {
            "keys": [("run_id", 1)],
            "unique": True,
            "name": "daily_screening_runs_run_id",
            "partial_filter_expression": None,
        }
    ]
    assert repo.memberships.created_indexes == [
        {
            "keys": [("scope_id", 1), ("code", 1), ("condition_key", 1)],
            "unique": True,
            "name": "daily_screening_memberships_scope_id_code_condition_key",
            "partial_filter_expression": {
                "scope_id": {"$exists": True},
                "code": {"$exists": True},
                "condition_key": {"$exists": True},
            },
        }
    ]
    assert repo.stock_snapshots.created_indexes == [
        {
            "keys": [("scope_id", 1), ("code", 1)],
            "unique": True,
            "name": "daily_screening_stock_snapshots_scope_id_code",
            "partial_filter_expression": {
                "scope_id": {"$exists": True},
                "code": {"$exists": True},
            },
        }
    ]


def test_repository_ensure_indexes_skips_fake_collections_without_create_index():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    repo = DailyScreeningRepository(
        db=FakeDB(
            daily_screening_runs=SimpleCollection("daily_screening_runs"),
            daily_screening_memberships=SimpleCollection("daily_screening_memberships"),
            daily_screening_stock_snapshots=SimpleCollection(
                "daily_screening_stock_snapshots"
            ),
        )
    )

    repo.ensure_indexes()


def test_repository_uses_scope_in_identity_for_same_run():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_runs=SimpleCollection("daily_screening_runs"),
        daily_screening_memberships=SimpleCollection("daily_screening_memberships"),
        daily_screening_stock_snapshots=SimpleCollection(
            "daily_screening_stock_snapshots"
        ),
    )
    repo = DailyScreeningRepository(db=fake_db)

    repo.replace_stage_memberships(
        run_id="run-1",
        stage="clxs",
        scope="scope-a",
        memberships=[
            {
                "run_id": "run-1",
                "scope": "scope-a",
                "stage": "clxs",
                "code": "000001",
                "name": "alpha",
                "model_key": "buy_zs_huila",
                "period": "30m",
                "fire_time": "2026-03-18T09:30:00+08:00",
            }
        ],
    )
    repo.replace_stage_memberships(
        run_id="run-1",
        stage="clxs",
        scope="scope-b",
        memberships=[{"code": "000001", "name": "alpha"}],
    )
    repo.upsert_stock_snapshots(
        run_id="run-1",
        scope="scope-a",
        snapshots=[{"code": "000001", "name": "alpha"}],
    )
    repo.upsert_stock_snapshots(
        run_id="run-1",
        scope="scope-b",
        snapshots=[{"code": "000001", "name": "alpha"}],
    )

    assert repo.index_specs()["daily_screening_memberships"][0]["keys"] == [
        ("scope_id", 1),
        ("code", 1),
        ("condition_key", 1),
    ]
    assert repo.index_specs()["daily_screening_stock_snapshots"][0]["keys"] == [
        ("scope_id", 1),
        ("code", 1),
    ]
    assert sorted(
        (row.get("scope_id"), row.get("condition_key"), row.get("code"))
        for row in fake_db["daily_screening_memberships"].docs
    ) == [("scope-a", "clxs", "000001"), ("scope-b", "clxs", "000001")]
    assert sorted(
        (row.get("scope_id"), row.get("code"))
        for row in fake_db["daily_screening_stock_snapshots"].docs
    ) == [("scope-a", "000001"), ("scope-b", "000001")]


def test_repository_upsert_stock_snapshots_replaces_scope_rows():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_runs=SimpleCollection("daily_screening_runs"),
        daily_screening_memberships=SimpleCollection("daily_screening_memberships"),
        daily_screening_stock_snapshots=SimpleCollection(
            "daily_screening_stock_snapshots"
        ),
    )
    repo = DailyScreeningRepository(db=fake_db)

    repo.upsert_stock_snapshots(
        run_id="run-1",
        scope="scope-a",
        snapshots=[
            {"code": "000001", "name": "alpha"},
            {"code": "000002", "name": "beta"},
        ],
    )
    repo.upsert_stock_snapshots(
        run_id="run-1",
        scope="scope-a",
        snapshots=[{"code": "000001", "name": "alpha"}],
    )

    assert sorted(
        (row.get("scope_id"), row.get("code"))
        for row in fake_db["daily_screening_stock_snapshots"].docs
    ) == [("scope-a", "000001")]


def test_repository_requires_membership_identity_keys():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    repo = DailyScreeningRepository(db=FakeDB())

    with pytest.raises(ValueError):
        repo.replace_stage_memberships(stage="clxs", memberships=[{"code": "000001"}])

    with pytest.raises(ValueError):
        repo.replace_condition_memberships(
            scope_id="scope-a",
            condition_key="clxs",
            codes=[{"name": "alpha"}],
        )

    with pytest.raises(ValueError):
        repo.replace_stage_memberships(
            stage="clxs",
            memberships=[{"scope_id": "scope-a"}],
        )


def test_repository_requires_snapshot_identity_keys():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    repo = DailyScreeningRepository(db=FakeDB())

    with pytest.raises(ValueError):
        repo.upsert_stock_snapshots(
            trade_date="2026-03-18",
            snapshots=[{"code": "000001"}],
        )

    with pytest.raises(ValueError):
        repo.upsert_stock_snapshots(
            scope_id="scope-a",
            trade_date="2026-03-18",
            snapshots=[{"name": "alpha"}],
        )


def test_repository_invalid_snapshot_batch_does_not_clear_existing_scope_rows():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_runs=SimpleCollection("daily_screening_runs"),
        daily_screening_memberships=SimpleCollection("daily_screening_memberships"),
        daily_screening_stock_snapshots=SimpleCollection(
            "daily_screening_stock_snapshots",
            docs=[
                {"scope_id": "scope-a", "code": "000001", "name": "alpha"},
                {"scope_id": "scope-a", "code": "000002", "name": "beta"},
            ],
        ),
    )
    repo = DailyScreeningRepository(db=fake_db)

    with pytest.raises(ValueError):
        repo.upsert_stock_snapshots(
            scope_id="scope-a",
            trade_date="2026-03-18",
            snapshots=[{"name": "invalid"}],
        )

    assert fake_db["daily_screening_stock_snapshots"].docs == [
        {"scope_id": "scope-a", "code": "000001", "name": "alpha"},
        {"scope_id": "scope-a", "code": "000002", "name": "beta"},
    ]


def test_repository_summary_stage_filter_only_affects_memberships():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_runs=SimpleCollection("daily_screening_runs"),
        daily_screening_memberships=SimpleCollection("daily_screening_memberships"),
        daily_screening_stock_snapshots=SimpleCollection(
            "daily_screening_stock_snapshots"
        ),
    )
    repo = DailyScreeningRepository(db=fake_db)

    repo.replace_stage_memberships(
        run_id="run-1",
        stage="clxs",
        scope="scope-a",
        memberships=[
            {
                "run_id": "run-1",
                "scope": "scope-a",
                "stage": "clxs",
                "code": "000001",
                "name": "alpha",
                "model_key": "buy_zs_huila",
                "period": "30m",
                "fire_time": "2026-03-18T09:30:00+08:00",
            }
        ],
    )
    repo.replace_stage_memberships(
        run_id="run-1",
        stage="chanlun",
        scope="scope-a",
        memberships=[
            {
                "run_id": "run-1",
                "scope": "scope-a",
                "stage": "chanlun",
                "code": "000002",
                "name": "beta",
                "signal_type": "buy_zs_huila",
                "period": "30m",
                "fire_time": "2026-03-18T10:30:00+08:00",
            }
        ],
    )
    repo.upsert_stock_snapshots(
        run_id="run-1",
        scope="scope-a",
        snapshots=[
            {"run_id": "run-1", "scope": "scope-a", "code": "000001", "name": "alpha"},
            {"run_id": "run-1", "scope": "scope-a", "code": "000002", "name": "beta"},
        ],
    )

    summary = repo.query_scope_summary(scope="scope-a", stage="clxs")

    assert summary["membership_count"] == 1
    assert summary["stage_counts"] == {"clxs": 1}
    assert summary["stock_count"] == 2
    assert summary["stock_codes"] == ["000001", "000002"]
    assert fake_db["daily_screening_memberships"].docs[0]["stage"] == "clxs"
    assert fake_db["daily_screening_memberships"].docs[0]["model_key"] == "buy_zs_huila"
    assert fake_db["daily_screening_memberships"].docs[0]["period"] == "30m"
    assert fake_db["daily_screening_memberships"].docs[0]["fire_time"] == (
        "2026-03-18T09:30:00+08:00"
    )
    assert fake_db["daily_screening_stock_snapshots"].docs[0]["run_id"] == "run-1"
    assert fake_db["daily_screening_stock_snapshots"].docs[0]["scope"] == "scope-a"


def test_repository_summary_keeps_run_id_empty_when_only_scope_is_provided():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_runs=SimpleCollection("daily_screening_runs"),
        daily_screening_memberships=SimpleCollection("daily_screening_memberships"),
        daily_screening_stock_snapshots=SimpleCollection(
            "daily_screening_stock_snapshots"
        ),
    )
    repo = DailyScreeningRepository(db=fake_db)

    repo.replace_stage_memberships(
        run_id="run-1",
        stage="clxs",
        scope="scope-a",
        memberships=[{"code": "000001", "name": "alpha"}],
    )
    repo.upsert_stock_snapshots(
        run_id="run-1",
        scope="scope-a",
        snapshots=[{"code": "000001", "name": "alpha"}],
    )

    summary = repo.query_scope_summary(scope="scope-a")

    assert summary["run_id"] is None
    assert summary["scope"] == "scope-a"


def test_repository_empty_membership_list_clears_target_stage():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_runs=SimpleCollection("daily_screening_runs"),
        daily_screening_memberships=SimpleCollection(
            "daily_screening_memberships",
            docs=[
                {
                    "scope_id": "run-1",
                    "condition_key": "clxs",
                    "code": "000001",
                },
                {
                    "scope_id": "run-1",
                    "condition_key": "clxs",
                    "code": "000002",
                },
                {
                    "scope_id": "run-1",
                    "condition_key": "chanlun",
                    "code": "000003",
                },
            ],
        ),
        daily_screening_stock_snapshots=SimpleCollection(
            "daily_screening_stock_snapshots"
        ),
    )
    repo = DailyScreeningRepository(db=fake_db)

    repo.replace_stage_memberships(
        run_id="run-1",
        stage="clxs",
        memberships=[],
    )

    assert [
        (row["condition_key"], row["scope_id"], row["code"])
        for row in fake_db["daily_screening_memberships"].docs
    ] == [("chanlun", "run-1", "000003")]


def test_repository_rejects_mixed_scope_memberships():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    repo = DailyScreeningRepository(db=FakeDB())

    with pytest.raises(ValueError):
        repo.replace_stage_memberships(
            stage="clxs",
            memberships=[
                {"code": "000001", "scope_id": "scope-a"},
                {"code": "000002", "scope_id": "scope-b"},
            ],
        )


def test_repository_rejects_mixed_scope_snapshots():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    repo = DailyScreeningRepository(db=FakeDB())

    with pytest.raises(ValueError):
        repo.upsert_stock_snapshots(
            snapshots=[
                {"code": "000001", "scope_id": "scope-a"},
                {"code": "000002", "scope_id": "scope-b"},
            ],
        )


def test_repository_rejects_mixed_stage_memberships_without_mutating_existing_rows():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_runs=SimpleCollection("daily_screening_runs"),
        daily_screening_memberships=SimpleCollection(
            "daily_screening_memberships",
            docs=[
                {
                    "scope_id": "scope-a",
                    "condition_key": "clxs",
                    "code": "000001",
                }
            ],
        ),
        daily_screening_stock_snapshots=SimpleCollection(
            "daily_screening_stock_snapshots"
        ),
    )
    repo = DailyScreeningRepository(db=fake_db)

    with pytest.raises(ValueError):
        repo.replace_stage_memberships(
            scope="scope-a",
            memberships=[
                {"condition_key": "clxs", "code": "000001"},
                {"condition_key": "chanlun", "code": "000002"},
            ],
        )

    assert fake_db["daily_screening_memberships"].docs == [
        {
            "scope_id": "scope-a",
            "condition_key": "clxs",
            "code": "000001",
        }
    ]


def test_repository_rejects_mixed_run_id_memberships_without_mutating_existing_rows():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_runs=SimpleCollection("daily_screening_runs"),
        daily_screening_memberships=SimpleCollection(
            "daily_screening_memberships",
            docs=[
                {
                    "scope_id": "scope-a",
                    "condition_key": "clxs",
                    "code": "000001",
                }
            ],
        ),
        daily_screening_stock_snapshots=SimpleCollection(
            "daily_screening_stock_snapshots"
        ),
    )
    repo = DailyScreeningRepository(db=fake_db)

    with pytest.raises(ValueError):
        repo.replace_stage_memberships(
            stage="clxs",
            memberships=[
                {"scope_id": "scope-a", "code": "000001"},
                {"scope_id": "scope-b", "code": "000002"},
            ],
        )

    assert fake_db["daily_screening_memberships"].docs == [
        {
            "scope_id": "scope-a",
            "condition_key": "clxs",
            "code": "000001",
        }
    ]


def test_repository_invalid_membership_batch_does_not_clear_existing_rows():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_runs=SimpleCollection("daily_screening_runs"),
        daily_screening_memberships=SimpleCollection(
            "daily_screening_memberships",
            docs=[
                {
                    "scope_id": "scope-a",
                    "condition_key": "clxs",
                    "code": "000001",
                }
            ],
        ),
        daily_screening_stock_snapshots=SimpleCollection(
            "daily_screening_stock_snapshots"
        ),
    )
    repo = DailyScreeningRepository(db=fake_db)

    with pytest.raises(ValueError):
        repo.replace_stage_memberships(
            run_id="run-1",
            stage="clxs",
            memberships=[{"name": "alpha"}],
        )

    assert fake_db["daily_screening_memberships"].docs == [
        {
            "scope_id": "scope-a",
            "condition_key": "clxs",
            "code": "000001",
        }
    ]


def test_repository_rejects_mixed_run_id_snapshots_without_mutating_existing_rows():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_runs=SimpleCollection("daily_screening_runs"),
        daily_screening_memberships=SimpleCollection("daily_screening_memberships"),
        daily_screening_stock_snapshots=SimpleCollection(
            "daily_screening_stock_snapshots",
            docs=[
                {
                    "scope_id": "scope-a",
                    "code": "000001",
                }
            ],
        ),
    )
    repo = DailyScreeningRepository(db=fake_db)

    with pytest.raises(ValueError):
        repo.upsert_stock_snapshots(
            snapshots=[
                {"scope_id": "scope-a", "code": "000001"},
                {"scope_id": "scope-b", "code": "000002"},
            ],
        )

    assert fake_db["daily_screening_stock_snapshots"].docs == [
        {
            "scope_id": "scope-a",
            "code": "000001",
        }
    ]


def test_repository_round_trips_run_scope_documents():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_runs=SimpleCollection("daily_screening_runs"),
        daily_screening_memberships=SimpleCollection("daily_screening_memberships"),
        daily_screening_stock_snapshots=SimpleCollection(
            "daily_screening_stock_snapshots"
        ),
    )
    repo = DailyScreeningRepository(db=fake_db)

    saved_run = repo.save_run({"run_id": "run-1", "status": "running"})
    memberships = repo.replace_stage_memberships(
        run_id="run-1",
        stage="clxs",
        memberships=[
            {
                "run_id": "run-1",
                "scope": "scope-a",
                "stage": "clxs",
                "code": "000001",
                "name": "alpha",
                "model_key": "buy_zs_huila",
                "period": "30m",
                "fire_time": "2026-03-18T09:30:00+08:00",
            },
            {
                "run_id": "run-1",
                "scope": "scope-a",
                "stage": "clxs",
                "code": "000002",
                "name": "beta",
                "model_key": "buy_zs_huila",
                "period": "60m",
                "fire_time": "2026-03-18T10:30:00+08:00",
            },
        ],
    )
    snapshots = repo.upsert_stock_snapshots(
        run_id="run-1",
        snapshots=[
            {"run_id": "run-1", "scope": "scope-a", "code": "000001", "name": "alpha"},
            {"run_id": "run-1", "scope": "scope-a", "code": "000002", "name": "beta"},
        ],
    )

    summary = repo.query_scope_summary(run_id="run-1")
    stocks = repo.query_scope_stocks(run_id="run-1")
    detail_memberships = repo.get_stock_detail_memberships(
        run_id="run-1", code="000001"
    )

    assert saved_run["run_id"] == "run-1"
    assert [item["condition_key"] for item in memberships] == ["clxs", "clxs"]
    assert [item["code"] for item in snapshots] == ["000001", "000002"]
    assert [item["stage"] for item in memberships] == ["clxs", "clxs"]
    assert [item["model_key"] for item in memberships] == [
        "buy_zs_huila",
        "buy_zs_huila",
    ]
    assert [item["period"] for item in memberships] == ["30m", "60m"]
    assert summary["run_id"] == "run-1"
    assert summary["membership_count"] == 2
    assert summary["stock_count"] == 2
    assert summary["stage_counts"] == {"clxs": 2}
    assert [item["code"] for item in stocks] == ["000001", "000002"]
    assert [item["code"] for item in detail_memberships] == ["000001"]
    assert fake_db["daily_screening_memberships"].docs[0]["run_id"] == "run-1"
    assert fake_db["daily_screening_memberships"].docs[0]["scope"] == "scope-a"
    assert fake_db["daily_screening_stock_snapshots"].docs[0]["run_id"] == "run-1"
    assert fake_db["daily_screening_stock_snapshots"].docs[0]["scope"] == "scope-a"


def test_repository_allows_multiple_memberships_for_same_code_and_condition_key():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_runs=SimpleCollection("daily_screening_runs"),
        daily_screening_memberships=SimpleCollection("daily_screening_memberships"),
        daily_screening_stock_snapshots=SimpleCollection(
            "daily_screening_stock_snapshots"
        ),
    )
    repo = DailyScreeningRepository(db=fake_db)

    repo.replace_condition_memberships(
        scope_id="scope-a",
        condition_key="buy_zs_huila_30m",
        codes=[{"code": "000001", "name": "alpha"}],
    )
    repo.replace_condition_memberships(
        scope_id="scope-a",
        condition_key="buy_zs_huila_60m",
        codes=[{"code": "000001", "name": "alpha"}],
    )
    repo.replace_condition_memberships(
        scope_id="scope-a",
        condition_key="macd_bullish_divergence",
        codes=[{"code": "000001", "name": "alpha"}],
    )

    assert sorted(
        (item["code"], item["condition_key"])
        for item in fake_db["daily_screening_memberships"].docs
    ) == [
        ("000001", "buy_zs_huila_30m"),
        ("000001", "buy_zs_huila_60m"),
        ("000001", "macd_bullish_divergence"),
    ]
    assert len(fake_db["daily_screening_memberships"].docs) == 3
