import importlib.util
import sys
import types
from pathlib import Path


def _load_module(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"failed to load spec for {module_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_quantaxis_mongo_runtime_prefers_freshquant_host_env(monkeypatch):
    monkeypatch.setenv("FRESHQUANT_MONGODB__HOST", "127.0.0.1")
    monkeypatch.setenv("FRESHQUANT_MONGODB__PORT", "27027")
    monkeypatch.delenv("MONGOURI", raising=False)
    monkeypatch.delenv("MONGODB", raising=False)
    monkeypatch.delenv("MONGODB_PORT", raising=False)

    module = _load_module(
        "qa_mongo_runtime_host",
        Path("sunflower/QUANTAXIS/QUANTAXIS/QAUtil/QAMongoRuntime.py"),
    )

    resolved = module.QA_util_resolve_mongo_runtime("mongodb://127.0.0.1:27017")

    assert resolved.host == "127.0.0.1"
    assert resolved.port == 27027
    assert resolved.uri == "mongodb://127.0.0.1:27027"


def test_quantaxis_mongo_runtime_keeps_non_local_legacy_target(monkeypatch):
    monkeypatch.delenv("FRESHQUANT_MONGODB__HOST", raising=False)
    monkeypatch.delenv("FRESHQUANT_MONGODB__PORT", raising=False)
    monkeypatch.delenv("MONGOURI", raising=False)
    monkeypatch.delenv("MONGODB", raising=False)
    monkeypatch.delenv("MONGODB_PORT", raising=False)

    module = _load_module(
        "qa_mongo_runtime_docker",
        Path("sunflower/QUANTAXIS/QUANTAXIS/QAUtil/QAMongoRuntime.py"),
    )

    resolved = module.QA_util_resolve_mongo_runtime("mongodb://fq_mongodb:27017")

    assert resolved.host == "fq_mongodb"
    assert resolved.port == 27017
    assert resolved.uri == "mongodb://fq_mongodb:27017"


def test_qifi_manager_uses_resolved_host_runtime_uri(monkeypatch):
    mongo_calls = []

    class _FakeCollection:
        def create_index(self, *args, **kwargs):
            return None

    class _FakeClient:
        def __init__(self, uri):
            mongo_calls.append(uri)
            self.QAREALTIME = types.SimpleNamespace(account=_FakeCollection())
            self.quantaxis = types.SimpleNamespace(history=_FakeCollection())

    pymongo_module = types.ModuleType("pymongo")
    pymongo_module.ASCENDING = 1
    pymongo_module.MongoClient = _FakeClient

    runtime_module = types.ModuleType("QUANTAXIS.QAUtil.QAMongoRuntime")
    runtime_module.QA_util_resolve_mongo_runtime = (
        lambda legacy_uri=None: types.SimpleNamespace(
            host="127.0.0.1",
            port=27027,
            uri="mongodb://127.0.0.1:27027",
        )
    )

    monkeypatch.setitem(sys.modules, "pymongo", pymongo_module)
    monkeypatch.setitem(
        sys.modules,
        "qaenv",
        types.SimpleNamespace(mongo_ip="mongodb://127.0.0.1:27017"),
    )
    monkeypatch.setitem(
        sys.modules, "numpy", types.SimpleNamespace(isnan=lambda value: False)
    )
    monkeypatch.setitem(
        sys.modules, "pandas", types.SimpleNamespace(DataFrame=object, Series=object)
    )
    monkeypatch.setitem(sys.modules, "pyfolio", types.ModuleType("pyfolio"))
    monkeypatch.setitem(sys.modules, "matplotlib", types.ModuleType("matplotlib"))
    monkeypatch.setitem(
        sys.modules, "matplotlib.pyplot", types.ModuleType("matplotlib.pyplot")
    )
    monkeypatch.setitem(sys.modules, "QUANTAXIS", types.ModuleType("QUANTAXIS"))
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QAUtil.QAMongoRuntime", runtime_module)

    module = _load_module(
        "qa_qifi_manager_runtime",
        Path("sunflower/QUANTAXIS/QUANTAXIS/QIFI/QifiManager.py"),
    )

    module.QA_QIFISMANAGER()

    assert mongo_calls == ["mongodb://127.0.0.1:27027"]


def test_qifi_manager_resolves_explicit_local_mongo_uri(monkeypatch):
    mongo_calls = []

    class _FakeCollection:
        def create_index(self, *args, **kwargs):
            return None

    class _FakeClient:
        def __init__(self, uri):
            mongo_calls.append(uri)
            self.QAREALTIME = types.SimpleNamespace(account=_FakeCollection())
            self.quantaxis = types.SimpleNamespace(history=_FakeCollection())

    pymongo_module = types.ModuleType("pymongo")
    pymongo_module.ASCENDING = 1
    pymongo_module.MongoClient = _FakeClient

    runtime_module = types.ModuleType("QUANTAXIS.QAUtil.QAMongoRuntime")
    runtime_module.QA_util_resolve_mongo_runtime = (
        lambda legacy_uri=None: types.SimpleNamespace(
            host="127.0.0.1",
            port=27027,
            uri="mongodb://127.0.0.1:27027",
        )
    )

    monkeypatch.setitem(sys.modules, "pymongo", pymongo_module)
    monkeypatch.setitem(
        sys.modules,
        "qaenv",
        types.SimpleNamespace(mongo_ip="mongodb://127.0.0.1:27017"),
    )
    monkeypatch.setitem(
        sys.modules, "numpy", types.SimpleNamespace(isnan=lambda value: False)
    )
    monkeypatch.setitem(
        sys.modules, "pandas", types.SimpleNamespace(DataFrame=object, Series=object)
    )
    monkeypatch.setitem(sys.modules, "pyfolio", types.ModuleType("pyfolio"))
    monkeypatch.setitem(sys.modules, "matplotlib", types.ModuleType("matplotlib"))
    monkeypatch.setitem(
        sys.modules, "matplotlib.pyplot", types.ModuleType("matplotlib.pyplot")
    )
    monkeypatch.setitem(sys.modules, "QUANTAXIS", types.ModuleType("QUANTAXIS"))
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QAUtil.QAMongoRuntime", runtime_module)

    module = _load_module(
        "qa_qifi_manager_explicit_runtime",
        Path("sunflower/QUANTAXIS/QUANTAXIS/QIFI/QifiManager.py"),
    )

    module.QA_QIFISMANAGER(mongo_ip="mongodb://127.0.0.1:27017")

    assert mongo_calls == ["mongodb://127.0.0.1:27027"]


def test_qifiserver_import_does_not_initialize_managers(monkeypatch):
    def _unexpected_manager(*args, **kwargs):
        raise AssertionError("manager should not be initialized at import time")

    monkeypatch.setitem(
        sys.modules,
        "qaenv",
        types.SimpleNamespace(mongo_ip="mongodb://127.0.0.1:27017"),
    )
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QAWebServer.basehandles",
        types.SimpleNamespace(QABaseHandler=object),
    )
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QAUtil",
        types.SimpleNamespace(QA_util_to_json_from_pandas=lambda value: value),
    )
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QIFI.QifiManager",
        types.SimpleNamespace(
            QA_QIFIMANAGER=object,
            QA_QIFISMANAGER=_unexpected_manager,
        ),
    )

    _load_module(
        "qa_qifiserver_runtime",
        Path("sunflower/QUANTAXIS/QUANTAXIS/QAWebServer/qifiserver.py"),
    )


def test_fetcher_resolves_legacy_local_default_uri(monkeypatch):
    sql_calls = []

    def _fake_sql(uri):
        sql_calls.append(uri)
        return types.SimpleNamespace(quantaxis=object())

    quantaxis_pkg = types.ModuleType("QUANTAXIS")
    quantaxis_pkg.__path__ = []
    qa_data_pkg = types.ModuleType("QUANTAXIS.QAData")
    qa_data_pkg.__path__ = []
    qa_fetch_pkg = types.ModuleType("QUANTAXIS.QAFetch")
    qa_fetch_pkg.__path__ = []
    qa_util_pkg = types.ModuleType("QUANTAXIS.QAUtil")
    qa_util_pkg.__path__ = []

    qa_fetch_pkg.QAEastMoney = types.ModuleType("QUANTAXIS.QAFetch.QAEastMoney")
    qa_fetch_pkg.QAQuery = types.ModuleType("QUANTAXIS.QAFetch.QAQuery")
    qa_fetch_pkg.QAQuery_Advance = types.ModuleType("QUANTAXIS.QAFetch.QAQuery_Advance")
    qa_fetch_pkg.QAQuery_Async = types.ModuleType("QUANTAXIS.QAFetch.QAQuery_Async")
    qa_fetch_pkg.QATdx = types.SimpleNamespace(select_best_ip=lambda: "best-ip")
    qa_fetch_pkg.QAThs = types.ModuleType("QUANTAXIS.QAFetch.QAThs")
    qa_fetch_pkg.QATushare = types.ModuleType("QUANTAXIS.QAFetch.QATushare")

    runtime_module = types.ModuleType("QUANTAXIS.QAUtil.QAMongoRuntime")
    runtime_module.QA_util_resolve_mongo_runtime = (
        lambda legacy_uri=None: types.SimpleNamespace(
            uri="mongodb://127.0.0.1:27027",
        )
    )

    monkeypatch.setitem(sys.modules, "pandas", types.ModuleType("pandas"))
    monkeypatch.setitem(sys.modules, "QUANTAXIS", quantaxis_pkg)
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QAData", qa_data_pkg)
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QAData.QADataStruct",
        types.SimpleNamespace(
            QA_DataStruct_Future_day=object,
            QA_DataStruct_Future_min=object,
            QA_DataStruct_Future_realtime=object,
            QA_DataStruct_Stock_day=object,
            QA_DataStruct_Stock_min=object,
            QA_DataStruct_Stock_realtime=object,
            QA_DataStruct_Index_day=object,
            QA_DataStruct_Index_min=object,
        ),
    )
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QAFetch", qa_fetch_pkg)
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QAUtil", qa_util_pkg)
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QAUtil.QAParameter",
        types.SimpleNamespace(
            DATABASE_TABLE=object(),
            DATASOURCE=types.SimpleNamespace(
                TDX=object(), MONGO=object(), AUTO=object()
            ),
            FREQUENCE=types.SimpleNamespace(
                DAY="day",
                WEEK="week",
                ONE_MIN="1min",
                FIVE_MIN="5min",
                FIFTEEN_MIN="15min",
                THIRTY_MIN="30min",
                SIXTY_MIN="60min",
            ),
            MARKET_TYPE=types.SimpleNamespace(STOCK_CN="stock", FUTURE_CN="future"),
            OUTPUT_FORMAT=types.SimpleNamespace(DATAFRAME="dataframe"),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QAUtil.QASql",
        types.SimpleNamespace(QA_util_sql_mongo_setting=_fake_sql),
    )
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QAUtil.QADate_trade",
        types.SimpleNamespace(QA_util_get_next_period=lambda *args, **kwargs: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QAData.data_resample",
        types.SimpleNamespace(QA_data_day_resample=lambda data: data),
    )
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QASU",
        types.SimpleNamespace(
            save_tdx=types.SimpleNamespace(now_time=lambda: "2024-01-01 15:00:00")
        ),
    )
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QAUtil.QAMongoRuntime", runtime_module)

    module = _load_module(
        "qa_fetcher_runtime",
        Path("sunflower/QUANTAXIS/QUANTAXIS/QAFetch/Fetcher.py"),
    )

    module.QA_Fetcher()

    assert sql_calls == ["mongodb://127.0.0.1:27027/quantaxis"]


def test_feature_backtest_resolves_trade_host_before_creating_account(monkeypatch):
    account_trade_hosts = []

    class _FakeAccount:
        def __init__(self, *args, **kwargs):
            account_trade_hosts.append(kwargs["trade_host"])

        def initial(self):
            return None

    class _FakeGrouped:
        def apply(self, fn):
            return "preload"

    class _FakeLevel(list):
        def tolist(self):
            return list(self)

    class _FakeIndex:
        levels = [
            _FakeLevel(["2024-01-02", "2024-01-03"]),
            _FakeLevel(["000001"]),
        ]

    class _FakeFeature:
        columns = ["factor"]
        index = _FakeIndex()

        def reset_index(self):
            return self

        def drop_duplicates(self, columns):
            return self

        def set_index(self, columns):
            return self

        def sort_index(self):
            return self

        def dropna(self):
            return self

        def groupby(self, *args, **kwargs):
            return _FakeGrouped()

    class _FakeClosePanel:
        def bfill(self):
            return self

    class _FakeDataCenter:
        closepanel = _FakeClosePanel()

    class _FakeClickhouseClient:
        def __init__(self, *args, **kwargs):
            return None

        def get_stock_day_qfq_adv(self, *args, **kwargs):
            return _FakeDataCenter()

    runtime_module = types.ModuleType("QUANTAXIS.QAUtil.QAMongoRuntime")
    runtime_module.QA_util_resolve_mongo_runtime = (
        lambda legacy_uri=None: types.SimpleNamespace(
            uri="mongodb://127.0.0.1:27027",
        )
    )

    dateutil_module = types.ModuleType("dateutil")
    dateutil_parser = types.SimpleNamespace(parse=lambda value: value)
    dateutil_module.parser = dateutil_parser

    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QAUtil",
        types.SimpleNamespace(
            QA_util_get_last_day=lambda *args, **kwargs: "2024-01-02",
            QA_util_get_trade_range=lambda *args, **kwargs: [],
            QA_util_code_change_format=lambda code: code,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QAFactor.featureView",
        types.SimpleNamespace(QAFeatureView=object),
    )
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QIFI.QifiAccount",
        types.SimpleNamespace(QIFI_Account=_FakeAccount),
    )
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QAFetch.QAClickhouse",
        types.SimpleNamespace(QACKClient=_FakeClickhouseClient),
    )
    monkeypatch.setitem(sys.modules, "dateutil", dateutil_module)
    monkeypatch.setitem(sys.modules, "dateutil.parser", dateutil_parser)
    monkeypatch.setitem(
        sys.modules,
        "qaenv",
        types.SimpleNamespace(
            clickhouse_ip="127.0.0.1",
            clickhouse_password="password",
            clickhouse_user="default",
            clickhouse_port=9000,
            mongo_ip="mongodb://127.0.0.1:27017",
        ),
    )
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QAUtil.QAMongoRuntime", runtime_module)

    module = _load_module(
        "qa_feature_backtest_runtime",
        Path("sunflower/QUANTAXIS/QUANTAXIS/QAFactor/featurebacktest.py"),
    )

    module.QAFeatureBacktest(_FakeFeature())

    assert account_trade_hosts == ["mongodb://127.0.0.1:27027"]


def test_qactabase_resolves_explicit_local_mongo_uri(monkeypatch):
    quantaxis_pkg = types.ModuleType("QUANTAXIS")
    quantaxis_pkg.__path__ = []

    runtime_module = types.ModuleType("QUANTAXIS.QAUtil.QAMongoRuntime")
    runtime_module.QA_util_resolve_mongo_runtime = (
        lambda legacy_uri=None: types.SimpleNamespace(
            host="127.0.0.1",
            port=27027,
            uri="mongodb://127.0.0.1:27027",
        )
    )

    monkeypatch.setitem(sys.modules, "pandas", types.ModuleType("pandas"))
    monkeypatch.setitem(sys.modules, "pymongo", types.ModuleType("pymongo"))
    monkeypatch.setitem(sys.modules, "requests", types.ModuleType("requests"))
    monkeypatch.setitem(
        sys.modules,
        "qaenv",
        types.SimpleNamespace(
            eventmq_amqp="amqp://guest:guest@127.0.0.1:5672",
            eventmq_ip="127.0.0.1",
            eventmq_password="guest",
            eventmq_port=5672,
            eventmq_username="guest",
            mongo_ip="mongodb://127.0.0.1:27017",
            mongo_uri="mongodb://127.0.0.1:27017",
        ),
    )
    monkeypatch.setitem(sys.modules, "QUANTAXIS", quantaxis_pkg)
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QAPubSub.consumer",
        types.SimpleNamespace(
            subscriber=object,
            subscriber_routing=object,
            subscriber_topic=object,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QAPubSub.producer",
        types.SimpleNamespace(
            publisher_routing=object,
            publisher_topic=object,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QAStrategy.util",
        types.SimpleNamespace(QA_data_futuremin_resample=lambda *args, **kwargs: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QIFI.QifiAccount",
        types.SimpleNamespace(ORDER_DIRECTION=object(), QIFI_Account=object),
    )
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QAMarket.market_preset",
        types.SimpleNamespace(MARKET_PRESET=lambda: object()),
    )
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QAEngine.QAThreadEngine",
        types.SimpleNamespace(QA_Thread=object),
    )
    monkeypatch.setitem(
        sys.modules,
        "QUANTAXIS.QAUtil.QAParameter",
        types.SimpleNamespace(
            MARKET_TYPE=types.SimpleNamespace(FUTURE_CN="future", STOCK_CN="stock"),
            RUNNING_ENVIRONMENT=object(),
        ),
    )
    monkeypatch.setitem(sys.modules, "QUANTAXIS.QAUtil.QAMongoRuntime", runtime_module)

    module = _load_module(
        "qa_qactabase_runtime",
        Path("sunflower/QUANTAXIS/QUANTAXIS/QAStrategy/qactabase.py"),
    )
    module.QAStrategyCtaBase.user_init = lambda self: None

    strategy = module.QAStrategyCtaBase(mongo_ip="mongodb://127.0.0.1:27017")

    assert strategy.mongo_ip == "mongodb://127.0.0.1:27027"
