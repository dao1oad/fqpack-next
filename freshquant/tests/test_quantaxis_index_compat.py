import importlib.util
from pathlib import Path

_SOURCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "sunflower"
    / "QUANTAXIS"
    / "QUANTAXIS"
    / "QASU"
    / "index_compat.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "freshquant_vendor_index_compat", _SOURCE_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_ensure_canonical_index = _MODULE.ensure_canonical_index
_ensure_compatible_index = _MODULE.ensure_compatible_index
_migrate_canonical_indexes = _MODULE.migrate_canonical_indexes


class _FakeCollection:
    def __init__(self, indexes, *, duplicate_groups=0):
        self._indexes = dict(indexes)
        self.duplicate_groups = duplicate_groups
        self.created = []
        self.dropped = []
        self.last_pipeline = None

    def index_information(self):
        return self._indexes

    def create_index(self, fields, **options):
        fields = list(fields)
        name = options.get("name") or "_".join(
            f"{field}_{direction}" for field, direction in fields
        )
        spec = {"key": fields}
        if options.get("unique"):
            spec["unique"] = True
        self._indexes[name] = spec
        self.created.append(
            {
                "fields": fields,
                "unique": bool(options.get("unique")),
                "name": options.get("name"),
            }
        )
        return name

    def drop_index(self, name):
        self.dropped.append(name)
        del self._indexes[name]

    def aggregate(self, pipeline, **kwargs):
        self.last_pipeline = pipeline
        if not self.duplicate_groups:
            return []
        return [{"groups": self.duplicate_groups}]


class _FakeDatabase:
    def __init__(self, *, index_day, index_min):
        self.collections = {
            "index_day": index_day,
            "index_min": index_min,
        }

    def __getitem__(self, name):
        return self.collections[name]


def test_ensure_compatible_index_reuses_unique_index_with_same_keys():
    fields = [("code", 1), ("date_stamp", 1)]
    collection = _FakeCollection(
        {
            "code_1_date_stamp_1": {
                "key": fields,
                "unique": True,
            }
        }
    )

    _ensure_compatible_index(collection, fields)

    assert collection.created == []


def test_ensure_compatible_index_reuses_non_unique_index_without_option_conflict():
    fields = [("code", 1), ("date_stamp", 1)]
    collection = _FakeCollection(
        {
            "code_1_date_stamp_1": {
                "key": fields,
            }
        }
    )

    _ensure_compatible_index(collection, fields)

    assert collection.created == []


def test_ensure_compatible_index_creates_missing_unique_key_pattern():
    fields = [("code", 1), ("date_stamp", 1)]
    collection = _FakeCollection({"_id_": {"key": [("_id", 1)]}})

    _ensure_compatible_index(collection, fields)

    assert collection.created == [
        {
            "fields": fields,
            "unique": True,
            "name": None,
        }
    ]


def test_index_min_runtime_initialization_reuses_legacy_index_until_migration():
    legacy_fields = [("code", 1), ("time_stamp", 1), ("date_stamp", 1)]
    collection = _FakeCollection(
        {
            "code_1_time_stamp_1_date_stamp_1": {
                "key": legacy_fields,
            }
        }
    )

    _ensure_canonical_index(collection, "index_min")

    assert collection.created == []


def test_canonical_index_migration_dry_run_execute_and_rerun_are_idempotent():
    index_day = _FakeCollection(
        {
            "_id_": {"key": [("_id", 1)]},
            "code_1_date_stamp_1": {"key": [("legacy", 1)]},
            "legacy_day_keys": {
                "key": [("code", 1), ("date_stamp", 1)],
            },
        }
    )
    index_min = _FakeCollection(
        {
            "_id_": {"key": [("_id", 1)]},
            "code_1_time_stamp_1_date_stamp_1": {
                "key": [
                    ("code", 1),
                    ("time_stamp", 1),
                    ("date_stamp", 1),
                ],
            },
        }
    )
    database = _FakeDatabase(index_day=index_day, index_min=index_min)

    dry_run = _migrate_canonical_indexes(database, execute=False)

    assert dry_run["mode"] == "dry-run"
    assert dry_run["ready_for_execute"] is True
    assert dry_run["changed"] == 0
    assert index_day.created == []
    assert index_day.dropped == []
    assert dry_run["collections"][0]["drop_indexes"] == [
        "code_1_date_stamp_1",
        "legacy_day_keys",
    ]

    executed = _migrate_canonical_indexes(database, execute=True)

    assert executed["ok"] is True
    assert executed["changed"] == 2
    assert index_day.dropped == ["code_1_date_stamp_1", "legacy_day_keys"]
    assert index_day.created == [
        {
            "fields": [("code", 1), ("date_stamp", 1)],
            "unique": True,
            "name": "code_1_date_stamp_1",
        }
    ]
    assert index_min.created == [
        {
            "fields": [
                ("code", 1),
                ("type", 1),
                ("time_stamp", 1),
                ("date_stamp", 1),
            ],
            "unique": True,
            "name": "code_1_type_1_time_stamp_1_date_stamp_1",
        }
    ]
    assert set(index_min.last_pipeline[0]["$group"]["_id"]) == {
        "code",
        "type",
        "time_stamp",
        "date_stamp",
    }

    rerun = _migrate_canonical_indexes(database, execute=True)

    assert rerun["ok"] is True
    assert rerun["changed"] == 0
    assert all(item["status"] == "canonical" for item in rerun["collections"])


def test_canonical_index_migration_blocks_all_changes_when_duplicates_exist():
    index_day = _FakeCollection(
        {
            "_id_": {"key": [("_id", 1)]},
            "code_1_date_stamp_1": {
                "key": [("code", 1), ("date_stamp", 1)],
            },
        },
        duplicate_groups=2,
    )
    index_min = _FakeCollection({"_id_": {"key": [("_id", 1)]}})
    database = _FakeDatabase(index_day=index_day, index_min=index_min)

    report = _migrate_canonical_indexes(database, execute=True)

    assert report["ok"] is False
    assert report["ready_for_execute"] is False
    assert report["changed"] == 0
    assert report["collections"][0]["status"] == "blocked"
    assert index_day.dropped == []
    assert index_day.created == []
    assert index_min.dropped == []
    assert index_min.created == []
