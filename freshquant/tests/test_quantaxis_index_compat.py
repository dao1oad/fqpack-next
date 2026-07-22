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
_ensure_compatible_index = _MODULE.ensure_compatible_index


class _FakeCollection:
    def __init__(self, indexes):
        self._indexes = indexes
        self.created = []

    def index_information(self):
        return self._indexes

    def create_index(self, fields):
        self.created.append(list(fields))


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


def test_ensure_compatible_index_creates_missing_key_pattern():
    fields = [("code", 1), ("date_stamp", 1)]
    collection = _FakeCollection({"_id_": {"key": [("_id", 1)]}})

    _ensure_compatible_index(collection, fields)

    assert collection.created == [fields]
