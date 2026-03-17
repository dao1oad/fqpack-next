from __future__ import annotations

from types import SimpleNamespace

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
        self.created_indexes: list[tuple[list[tuple[str, int]], bool, str | None]] = []

    def create_index(self, keys, unique=False, name=None):
        self.created_indexes.append((list(keys), bool(unique), name))


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
        daily_screening_memberships=SimpleCollection(
            "daily_screening_memberships"
        ),
        daily_screening_stock_snapshots=SimpleCollection(
            "daily_screening_stock_snapshots"
        ),
    )

    repo = DailyScreeningRepository(db=fake_db)

    assert repo.runs.name == "daily_screening_runs"
    assert repo.memberships.name == "daily_screening_memberships"
    assert repo.stock_snapshots.name == "daily_screening_stock_snapshots"


def test_repository_builds_expected_indexes():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    repo = DailyScreeningRepository(db=FakeDB())
    specs = repo.index_specs()

    assert specs == {
        "daily_screening_runs": [
            {
                "name": "daily_screening_runs_run_id",
                "keys": [("run_id", 1)],
                "unique": True,
            }
        ],
        "daily_screening_memberships": [
            {
                "name": "daily_screening_memberships_run_stage_code",
                "keys": [("run_id", 1), ("stage", 1), ("code", 1)],
                "unique": True,
            }
        ],
        "daily_screening_stock_snapshots": [
            {
                "name": "daily_screening_stock_snapshots_run_code",
                "keys": [("run_id", 1), ("code", 1)],
                "unique": True,
            }
        ],
    }


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
        ([("run_id", 1)], True, "daily_screening_runs_run_id")
    ]
    assert repo.memberships.created_indexes == [
        (
            [("run_id", 1), ("stage", 1), ("code", 1)],
            True,
            "daily_screening_memberships_run_stage_code",
        )
    ]
    assert repo.stock_snapshots.created_indexes == [
        ([("run_id", 1), ("code", 1)], True, "daily_screening_stock_snapshots_run_code")
    ]


def test_repository_ensure_indexes_skips_fake_collections_without_create_index():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    repo = DailyScreeningRepository(
        db=FakeDB(
            daily_screening_runs=SimpleCollection("daily_screening_runs"),
            daily_screening_memberships=SimpleCollection(
                "daily_screening_memberships"
            ),
            daily_screening_stock_snapshots=SimpleCollection(
                "daily_screening_stock_snapshots"
            ),
        )
    )

    repo.ensure_indexes()


def test_repository_round_trips_run_scope_documents():
    from freshquant.daily_screening.repository import DailyScreeningRepository

    fake_db = FakeDB(
        daily_screening_runs=SimpleCollection("daily_screening_runs"),
        daily_screening_memberships=SimpleCollection(
            "daily_screening_memberships"
        ),
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
            {"code": "000001", "name": "alpha"},
            {"code": "000002", "name": "beta"},
        ],
    )
    snapshots = repo.upsert_stock_snapshots(
        run_id="run-1",
        snapshots=[
            {"code": "000001", "name": "alpha"},
            {"code": "000002", "name": "beta"},
        ],
    )

    summary = repo.query_scope_summary(run_id="run-1")
    stocks = repo.query_scope_stocks(run_id="run-1")
    detail_memberships = repo.get_stock_detail_memberships(
        run_id="run-1", code="000001"
    )

    assert saved_run["run_id"] == "run-1"
    assert [item["stage"] for item in memberships] == ["clxs", "clxs"]
    assert [item["code"] for item in snapshots] == ["000001", "000002"]
    assert summary["run_id"] == "run-1"
    assert summary["membership_count"] == 2
    assert summary["stock_count"] == 2
    assert summary["stage_counts"] == {"clxs": 2}
    assert [item["code"] for item in stocks] == ["000001", "000002"]
    assert [item["code"] for item in detail_memberships] == ["000001"]
