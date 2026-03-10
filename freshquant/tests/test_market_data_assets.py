import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _build_dagster_stub():
    module = ModuleType("dagster")

    class AssetExecutionContext:  # pragma: no cover - test stub only
        pass

    def asset(fn=None, **kwargs):
        if fn is None:
            return lambda inner: inner
        return fn

    module.AssetExecutionContext = AssetExecutionContext
    module.asset = asset
    return module


def _build_qasu_main_stub():
    module = ModuleType("QUANTAXIS.QASU.main")
    for name in (
        "QA_SU_save_bond_day",
        "QA_SU_save_bond_list",
        "QA_SU_save_bond_min",
        "QA_SU_save_etf_day",
        "QA_SU_save_etf_list",
        "QA_SU_save_etf_min",
        "QA_SU_save_future_day_all",
        "QA_SU_save_future_list",
        "QA_SU_save_future_min_all",
        "QA_SU_save_index_day",
        "QA_SU_save_index_list",
        "QA_SU_save_index_min",
        "QA_SU_save_stock_block",
        "QA_SU_save_stock_day",
        "QA_SU_save_stock_list",
        "QA_SU_save_stock_min",
        "QA_SU_save_stock_xdxr",
    ):
        setattr(module, name, lambda *args, **kwargs: None)
    return module


def _build_qautil_stub():
    module = ModuleType("QUANTAXIS.QAUtil")
    module.QA_util_to_json_from_pandas = lambda dataframe: list(dataframe or [])
    return module


def _build_etf_adj_sync_stub():
    module = ModuleType("freshquant.data.etf_adj_sync")
    module.sync_etf_adj_all = lambda *args, **kwargs: None
    module.sync_etf_xdxr_all = lambda *args, **kwargs: None
    return module


def _import_market_data_module(monkeypatch):
    project_root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(project_root))

    dagster_module = _build_dagster_stub()
    qasu_main_module = _build_qasu_main_stub()
    qautil_module = _build_qautil_stub()
    qasu_package = ModuleType("QUANTAXIS.QASU")
    quantaxis_package = ModuleType("QUANTAXIS")
    qasu_package.main = qasu_main_module
    quantaxis_package.QASU = qasu_package

    monkeypatch.setitem(sys.modules, "dagster", dagster_module)
    monkeypatch.setitem(sys.modules, "QUANTAXIS", quantaxis_package)
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QASU", qasu_package)
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QASU.main", qasu_main_module)
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QAUtil", qautil_module)
    monkeypatch.setitem(
        sys.modules,
        "freshquant.data.etf_adj_sync",
        _build_etf_adj_sync_stub(),
    )

    module_path = (
        project_root
        / "morningglory"
        / "fqdagster"
        / "src"
        / "fqdagster"
        / "defs"
        / "assets"
        / "market_data.py"
    )
    spec = importlib.util.spec_from_file_location(
        "test_market_data_assets_module",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeLog:
    def __init__(self):
        self.info_messages = []
        self.warning_messages = []

    def info(self, message, *args):
        self.info_messages.append(message % args if args else message)

    def warning(self, message, *args):
        self.warning_messages.append(message % args if args else message)


class FakeDatabase:
    def __init__(self):
        self.collections = {}
        self.collection_fail_insert_on_calls = {}

    def __getitem__(self, name):
        key = str(name)
        collection = self.collections.get(key)
        if collection is None:
            collection = FakeCollection(database=self, name=key)
            collection.fail_insert_on_calls = set(
                self.collection_fail_insert_on_calls.get(key, set())
            )
            self.collections[key] = collection
        return collection

    def drop_collection(self, name):
        target_name = getattr(name, "name", name)
        self.collections.pop(str(target_name), None)


class FakeCollection:
    def __init__(self, documents=None, *, database=None, name="stock_block"):
        self.database = database or FakeDatabase()
        self.name = str(name)
        self.documents = [dict(item) for item in (documents or [])]
        self.created_indexes = []
        self.inserted_batches = []
        self.find_queries = []
        self.rename_calls = []
        self.fail_insert_on_calls = set()
        self.insert_call_count = 0

    def create_index(self, fields, **kwargs):
        self.created_indexes.append((fields, kwargs))

    def find(self, query=None):
        normalized = dict(query or {})
        self.find_queries.append(normalized)

        def _matches(document):
            for key, expected in normalized.items():
                actual = document.get(key)
                if isinstance(expected, dict) and "$nin" in expected:
                    if actual in set(expected["$nin"]):
                        return False
                    continue
                if actual != expected:
                    return False
            return True

        return [dict(item) for item in self.documents if _matches(item)]

    def insert_many(self, documents, ordered=False):
        self.insert_call_count += 1
        if self.insert_call_count in self.fail_insert_on_calls:
            raise RuntimeError(
                f"insert failed for {self.name} call={self.insert_call_count}"
            )
        batch = [dict(item) for item in (documents or [])]
        self.inserted_batches.append((batch, ordered))
        self.documents.extend(batch)

    def rename(self, new_name, dropTarget=False):
        target_name = str(new_name)
        self.rename_calls.append((target_name, dropTarget))
        if dropTarget:
            self.database.drop_collection(target_name)
        self.database.collections.pop(self.name, None)
        self.name = target_name
        self.database.collections[target_name] = self
        return self


def _build_stock_block_collection(documents):
    database = FakeDatabase()
    collection = FakeCollection(
        documents,
        database=database,
        name="stock_block",
    )
    database.collections["stock_block"] = collection
    return database, collection


def test_refresh_stock_block_keeps_existing_docs_when_all_sources_fail(monkeypatch):
    module = _import_market_data_module(monkeypatch)
    monkeypatch.setattr(module, "_load_local_tdx_infoharbor_docs", lambda log: [])
    database, collection = _build_stock_block_collection(
        [
            {"code": "600000", "blockname": "沪深300", "source": "tdx"},
            {"code": "000001", "blockname": "上证50", "source": "tushare"},
        ]
    )
    log = FakeLog()

    def fetch_block_dataframe(source):
        raise RuntimeError(f"{source} down")

    def to_json(frame):
        raise AssertionError("to_json should not be called when fetch fails")

    result = module._refresh_stock_block_collection(
        collection=collection,
        fetch_block_dataframe=fetch_block_dataframe,
        to_json=to_json,
        log=log,
    )

    assert result["total_docs"] == 0
    assert result["refreshed_sources"] == []
    assert collection.inserted_batches == []
    assert database["stock_block"].documents == [
        {"code": "600000", "blockname": "沪深300", "source": "tdx"},
        {"code": "000001", "blockname": "上证50", "source": "tushare"},
    ]
    assert any(
        "keeping existing collection unchanged" in msg for msg in log.warning_messages
    )


def test_refresh_stock_block_replaces_only_successful_sources(monkeypatch):
    module = _import_market_data_module(monkeypatch)
    monkeypatch.setattr(module, "_load_local_tdx_infoharbor_docs", lambda log: [])
    database, collection = _build_stock_block_collection(
        [
            {"code": "600000", "blockname": "旧沪深300", "source": "tdx"},
            {"code": "000001", "blockname": "旧上证50", "source": "tushare"},
        ]
    )
    log = FakeLog()

    def fetch_block_dataframe(source):
        if source == "tdx":
            return [{"code": "600519", "blockname": "沪深300"}]
        raise RuntimeError("tushare down")

    def to_json(frame):
        return [dict(item) for item in frame]

    result = module._refresh_stock_block_collection(
        collection=collection,
        fetch_block_dataframe=fetch_block_dataframe,
        to_json=to_json,
        log=log,
    )

    assert result["total_docs"] == 1
    assert result["refreshed_sources"] == ["tdx"]
    assert database["stock_block"].documents == [
        {"code": "000001", "blockname": "旧上证50", "source": "tushare"},
        {"code": "600519", "blockname": "沪深300", "source": "tdx"},
    ]
    assert any("tushare" in msg for msg in log.warning_messages)


def test_parse_tdx_infoharbor_block_text_parses_quality_blocks(monkeypatch):
    module = _import_market_data_module(monkeypatch)
    text = "\n".join(
        [
            "#FG_活跃ETF,96,880676,20230719,20260309,,",
            "0#159001,1#510050,",
            "#ZS_沪深300,300,,20050408,,,",
            "0#000001,1#600000,",
            "#ZS_中证央企,451,,20090330,,,",
            "0#000008,1#600028,",
        ]
    )

    documents = module._parse_tdx_infoharbor_block_text(text)

    assert documents == [
        {"code": "159001", "blockname": "活跃ETF", "source": "tdx_infoharbor"},
        {"code": "510050", "blockname": "活跃ETF", "source": "tdx_infoharbor"},
        {"code": "000001", "blockname": "沪深300", "source": "tdx_infoharbor"},
        {"code": "600000", "blockname": "沪深300", "source": "tdx_infoharbor"},
        {"code": "000008", "blockname": "中证央企", "source": "tdx_infoharbor"},
        {"code": "600028", "blockname": "中证央企", "source": "tdx_infoharbor"},
    ]


def test_refresh_stock_block_uses_local_infoharbor_when_remote_sources_fail(
    monkeypatch,
):
    module = _import_market_data_module(monkeypatch)
    database, collection = _build_stock_block_collection(
        [
            {"code": "600000", "blockname": "旧沪深300", "source": "tdx"},
            {"code": "000001", "blockname": "旧上证50", "source": "tushare"},
            {"code": "000008", "blockname": "旧中证央企", "source": "tdx_infoharbor"},
        ]
    )
    log = FakeLog()

    monkeypatch.setattr(
        module,
        "_load_local_tdx_infoharbor_docs",
        lambda log: [
            {
                "code": "000001",
                "blockname": "沪深300",
                "source": "tdx_infoharbor",
            },
            {
                "code": "600028",
                "blockname": "中证央企",
                "source": "tdx_infoharbor",
            },
        ],
    )

    def fetch_block_dataframe(source):
        raise RuntimeError(f"{source} down")

    def to_json(frame):
        raise AssertionError("to_json should not be called when remote fetch fails")

    result = module._refresh_stock_block_collection(
        collection=collection,
        fetch_block_dataframe=fetch_block_dataframe,
        to_json=to_json,
        log=log,
    )

    assert result["total_docs"] == 2
    assert result["refreshed_sources"] == ["tdx_infoharbor"]
    assert database["stock_block"].documents == [
        {"code": "600000", "blockname": "旧沪深300", "source": "tdx"},
        {"code": "000001", "blockname": "旧上证50", "source": "tushare"},
        {"code": "000001", "blockname": "沪深300", "source": "tdx_infoharbor"},
        {"code": "600028", "blockname": "中证央企", "source": "tdx_infoharbor"},
    ]


def test_refresh_stock_block_keeps_existing_docs_when_staging_insert_fails(
    monkeypatch,
):
    module = _import_market_data_module(monkeypatch)
    monkeypatch.setattr(module, "_load_local_tdx_infoharbor_docs", lambda log: [])
    monkeypatch.setattr(
        module,
        "_stock_block_staging_collection_name",
        lambda collection_name: f"{collection_name}__staging",
    )
    database, collection = _build_stock_block_collection(
        [
            {"code": "600000", "blockname": "旧沪深300", "source": "tdx"},
            {"code": "000001", "blockname": "旧上证50", "source": "tushare"},
        ]
    )
    database.collection_fail_insert_on_calls["stock_block__staging"] = {2}
    log = FakeLog()

    def fetch_block_dataframe(source):
        if source == "tdx":
            return [{"code": "600519", "blockname": "沪深300"}]
        raise RuntimeError("tushare down")

    def to_json(frame):
        return [dict(item) for item in frame]

    result = module._refresh_stock_block_collection(
        collection=collection,
        fetch_block_dataframe=fetch_block_dataframe,
        to_json=to_json,
        log=log,
    )

    assert result["total_docs"] == 0
    assert result["refreshed_sources"] == []
    assert database["stock_block"].documents == [
        {"code": "600000", "blockname": "旧沪深300", "source": "tdx"},
        {"code": "000001", "blockname": "旧上证50", "source": "tushare"},
    ]
    assert any("source=tdx" in msg for msg in log.warning_messages)
    assert any(
        "keeping existing collection unchanged" in msg for msg in log.warning_messages
    )
