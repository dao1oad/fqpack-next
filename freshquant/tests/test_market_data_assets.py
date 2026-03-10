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


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = [dict(item) for item in (documents or [])]
        self.created_indexes = []
        self.deleted_queries = []
        self.inserted_batches = []

    def create_index(self, fields, **kwargs):
        self.created_indexes.append((fields, kwargs))

    def delete_many(self, query):
        normalized = dict(query)
        self.deleted_queries.append(normalized)
        source = normalized.get("source")
        if source is None:
            self.documents = []
        else:
            self.documents = [
                dict(item) for item in self.documents if item.get("source") != source
            ]

    def insert_many(self, documents, ordered=False):
        batch = [dict(item) for item in (documents or [])]
        self.inserted_batches.append((batch, ordered))
        self.documents.extend(batch)


def test_refresh_stock_block_keeps_existing_docs_when_all_sources_fail(monkeypatch):
    module = _import_market_data_module(monkeypatch)
    monkeypatch.setattr(module, "_load_local_tdx_infoharbor_docs", lambda log: [])
    collection = FakeCollection(
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
    assert collection.deleted_queries == []
    assert collection.inserted_batches == []
    assert collection.documents == [
        {"code": "600000", "blockname": "沪深300", "source": "tdx"},
        {"code": "000001", "blockname": "上证50", "source": "tushare"},
    ]
    assert any(
        "keeping existing collection unchanged" in msg for msg in log.warning_messages
    )


def test_refresh_stock_block_replaces_only_successful_sources(monkeypatch):
    module = _import_market_data_module(monkeypatch)
    monkeypatch.setattr(module, "_load_local_tdx_infoharbor_docs", lambda log: [])
    collection = FakeCollection(
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
    assert collection.deleted_queries == [{"source": "tdx"}]
    assert collection.documents == [
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
    collection = FakeCollection(
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
    assert collection.deleted_queries == [{"source": "tdx_infoharbor"}]
    assert collection.documents == [
        {"code": "600000", "blockname": "旧沪深300", "source": "tdx"},
        {"code": "000001", "blockname": "旧上证50", "source": "tushare"},
        {"code": "000001", "blockname": "沪深300", "source": "tdx_infoharbor"},
        {"code": "600028", "blockname": "中证央企", "source": "tdx_infoharbor"},
    ]
