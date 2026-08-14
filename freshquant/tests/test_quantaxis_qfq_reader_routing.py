import ast
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import freshquant.quantaxis.qadata.qadatastruct as qadatastruct
from freshquant.data.qfq_reader import QFQDataNotReadyError

TEMPORARY_OFFLINE_QFACTOR_ALLOWLIST = {
    (
        "sunflower/QUANTAXIS/QUANTAXIS/QAAnalysis/QAAnalysis_block.py",
        45,
    ): (
        "vendored offline QAAnalysis helper; it has no FreshQuant, CLX, or "
        "QAWebServer deployed callsite"
    ),
    (
        "sunflower/QUANTAXIS/QUANTAXIS/QAFetch/QAClickhouse.py",
        255,
    ): (
        "vendored offline QAFactor ClickHouse helper; QACKClient is exported "
        "but has no FreshQuant, CLX, or QAWebServer deployed callsite"
    ),
}

CANONICAL_ADJUSTMENT_COLLECTION_NAMES = {
    "stock_adj_qfq_a",
    "stock_adj_qfq_b",
    "etf_adj_qfq_a",
    "etf_adj_qfq_b",
    "stock_adj_intraday",
    "etf_adj_intraday",
    "stock_adj",
    "etf_adj",
}

TEMPORARY_DIRECT_ADJUSTMENT_COLLECTION_ALLOWLIST = {
    ("freshquant/data/etf_adj_sync.py", 115, "literal:etf_adj"): (
        "PR2a transitional legacy ETF writer cleanup"
    ),
    ("freshquant/data/etf_adj_sync.py", 683, "attribute:etf_adj"): (
        "PR2a transitional legacy ETF writer"
    ),
    ("freshquant/data/qfq_reader.py", 162, "fragment:_adj_intraday"): (
        "shared strict QFQ reader"
    ),
    (
        "freshquant/market_data/xtdata/adj_refresh_service.py",
        109,
        "literal:stock_adj",
    ): "PR2a transitional legacy anchor evidence",
    (
        "freshquant/market_data/xtdata/adj_refresh_service.py",
        109,
        "literal:etf_adj",
    ): "PR2a transitional legacy anchor evidence",
    (
        "freshquant/market_data/xtdata/adj_refresh_service.py",
        141,
        "literal:stock_adj_intraday",
    ): "snapshot-bound intraday override writer",
    (
        "freshquant/market_data/xtdata/adj_refresh_service.py",
        141,
        "literal:etf_adj_intraday",
    ): "snapshot-bound intraday override writer",
    ("freshquant/market_data/xtdata/qfq.py", 32, "literal:stock_adj_qfq_a"): (
        "shared QFQ writer"
    ),
    ("freshquant/market_data/xtdata/qfq.py", 33, "literal:stock_adj_qfq_b"): (
        "shared QFQ writer"
    ),
    ("freshquant/market_data/xtdata/qfq.py", 36, "literal:etf_adj_qfq_a"): (
        "shared QFQ writer"
    ),
    ("freshquant/market_data/xtdata/qfq.py", 37, "literal:etf_adj_qfq_b"): (
        "shared QFQ writer"
    ),
    ("freshquant/market_data/xtdata/qfq.py", 40, "literal:stock_adj"): (
        "shared QFQ writer legacy-copy input"
    ),
    ("freshquant/market_data/xtdata/qfq.py", 40, "literal:etf_adj"): (
        "shared QFQ writer legacy-copy input"
    ),
    (
        "freshquant/market_data/xtdata/qfq.py",
        42,
        "literal:stock_adj_intraday",
    ): "shared QFQ writer override rebind",
    (
        "freshquant/market_data/xtdata/qfq.py",
        43,
        "literal:etf_adj_intraday",
    ): "shared QFQ writer override rebind",
    (
        "sunflower/QUANTAXIS/QUANTAXIS/QAData/QADataStruct.py",
        79,
        "attribute:stock_adj",
    ): "vendored transitional legacy path; PR2b closure",
    (
        "sunflower/QUANTAXIS/QUANTAXIS/QAFetch/QAClickhouse.py",
        131,
        "embedded:stock_adj",
    ): "vendored transitional legacy path; PR2b closure",
    (
        "sunflower/QUANTAXIS/QUANTAXIS/QAFetch/QAQuery.py",
        149,
        "attribute:stock_adj",
    ): "vendored transitional legacy path; PR2b closure",
    (
        "sunflower/QUANTAXIS/QUANTAXIS/QASU/save_tdx.py",
        632,
        "attribute:stock_adj",
    ): "vendored transitional legacy writer; PR2b closure",
    (
        "sunflower/QUANTAXIS/QUANTAXIS/QASU/save_tdx.py",
        650,
        "literal:stock_adj",
    ): "vendored transitional legacy writer; PR2b closure",
    (
        "sunflower/QUANTAXIS/QUANTAXIS/QASU/save_tdx.py",
        651,
        "attribute:stock_adj",
    ): "vendored transitional legacy writer; PR2b closure",
}

TEMPORARY_FILL_ONE_ALLOWLIST = {
    ("freshquant/data/adj_intraday.py", 117): (
        "transitional legacy helper with no runtime callsite"
    ),
    ("freshquant/data/adj_intraday.py", 122): (
        "transitional legacy helper with no runtime callsite"
    ),
    ("freshquant/data/etf_adj.py", 95): (
        "transitional legacy ETF factor implementation; PR2b closure"
    ),
    ("freshquant/data/etf_adj.py", 144): (
        "transitional legacy ETF factor implementation; PR2b closure"
    ),
    ("sunflower/QUANTAXIS/config/data_init.py", 945): (
        "vendored transitional legacy factor path; PR2b closure"
    ),
    ("sunflower/QUANTAXIS/config/data_init.py", 947): (
        "vendored transitional legacy factor path; PR2b closure"
    ),
    ("sunflower/QUANTAXIS/QUANTAXIS/QAData/data_fq.py", 154): (
        "vendored transitional legacy factor path; PR2b closure"
    ),
    ("sunflower/QUANTAXIS/QUANTAXIS/QAData/data_fq.py", 157): (
        "vendored transitional legacy factor path; PR2b closure"
    ),
    ("sunflower/QUANTAXIS/QUANTAXIS/QAFetch/QAClickhouse.py", 47): (
        "vendored transitional legacy factor path; PR2b closure"
    ),
    ("sunflower/QUANTAXIS/QUANTAXIS/QAFetch/QAClickhouse.py", 147): (
        "vendored transitional legacy factor path; PR2b closure"
    ),
    ("sunflower/QUANTAXIS/QUANTAXIS/QAFetch/QAClickhouse.py", 189): (
        "vendored transitional legacy factor path; PR2b closure"
    ),
    ("sunflower/QUANTAXIS/QUANTAXIS/QAFetch/QAClickhouse.py", 219): (
        "vendored transitional legacy factor path; PR2b closure"
    ),
}


def _runtime_python_files(repo_root):
    for runtime_root in (
        repo_root / "freshquant",
        repo_root / "sunflower" / "QUANTAXIS",
    ):
        for path in runtime_root.rglob("*.py"):
            relative_path = path.relative_to(repo_root)
            lowered_parts = {part.lower() for part in relative_path.parts}
            if lowered_parts & {
                "tests",
                "__pycache__",
                "build",
                "dist",
                ".tox",
                ".venv",
            }:
                continue
            yield path, relative_path.as_posix()


def _docstring_node_ids(tree):
    result = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not body or not isinstance(body, list):
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            result.add(id(first.value))
    return result


def _direct_adjustment_collection_hits(repo_root):
    hits = set()
    search_terms = {*CANONICAL_ADJUSTMENT_COLLECTION_NAMES, "_adj_intraday"}
    for path, relative_path in _runtime_python_files(repo_root):
        source = path.read_text(encoding="utf-8-sig", errors="replace")
        if not any(term in source for term in search_terms):
            continue
        tree = ast.parse(source)
        docstrings = _docstring_node_ids(tree)
        for node in ast.walk(tree):
            kind = None
            value = None
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                if node.value in CANONICAL_ADJUSTMENT_COLLECTION_NAMES:
                    kind, value = "literal", node.value
                elif "_adj_intraday" in node.value:
                    kind, value = "fragment", "_adj_intraday"
                elif "quantaxis.stock_adj" in node.value:
                    kind, value = "embedded", "stock_adj"
                elif "quantaxis.etf_adj" in node.value:
                    kind, value = "embedded", "etf_adj"
            elif isinstance(node, ast.Attribute) and node.attr in {
                "stock_adj",
                "etf_adj",
            }:
                kind, value = "attribute", node.attr
            if kind:
                hits.add((relative_path, node.lineno, f"{kind}:{value}"))
    return hits


def _fill_one_hits(repo_root):
    hits = set()
    for path, relative_path in _runtime_python_files(repo_root):
        source = path.read_text(encoding="utf-8-sig", errors="replace")
        if "fillna" not in source:
            continue
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Call)
                or not isinstance(node.func, ast.Attribute)
                or node.func.attr != "fillna"
            ):
                continue
            value = (
                node.args[0]
                if node.args
                else next(
                    (
                        keyword.value
                        for keyword in node.keywords
                        if keyword.arg == "value"
                    ),
                    None,
                )
            )
            if (
                isinstance(value, ast.Constant)
                and type(value.value) in {int, float}
                and float(value.value) == 1.0
            ):
                hits.add((relative_path, node.lineno))
    return hits


def _fake_reader(calls):
    def apply(data, *, scope, code, ohlc_cols):
        calls.append((scope, code, tuple(ohlc_cols)))
        result = data.copy()
        factor = 0.5 if code == "000001" else 0.8
        for column in ohlc_cols:
            if column in result.columns:
                result[column] = result[column] * factor
        return result, SimpleNamespace(effective_version=f"snapshot-{code}")

    return apply


def test_custom_stock_day_to_qfq_routes_each_code_through_strict_reader(
    monkeypatch,
):
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2026-01-02"), "000001"),
            (pd.Timestamp("2026-01-02"), "600000"),
        ],
        names=["date", "code"],
    )
    data = pd.DataFrame(
        {
            "open": [10.0, 20.0],
            "high": [11.0, 21.0],
            "low": [9.0, 19.0],
            "close": [10.5, 20.5],
            "volume": [100.0, 200.0],
            "high_limit": [12.0, 22.0],
            "low_limit": [8.0, 18.0],
        },
        index=index,
    )
    calls = []
    monkeypatch.setattr(qadatastruct, "apply_qfq_to_bars", _fake_reader(calls))

    result = qadatastruct.QA_DataStruct_Stock_day(data).to_qfq()

    assert result.if_fq == "qfq"
    assert result.data.loc[(pd.Timestamp("2026-01-02"), "000001"), "close"] == 5.25
    assert result.data.loc[
        (pd.Timestamp("2026-01-02"), "600000"), "close"
    ] == pytest.approx(16.4)
    assert [item[:2] for item in calls] == [
        ("stock", "000001"),
        ("stock", "600000"),
    ]


def test_custom_stock_min_to_qfq_propagates_strict_reader_failure(monkeypatch):
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2026-01-02 09:35:00"), "000001")],
        names=["datetime", "code"],
    )
    data = pd.DataFrame(
        {
            "open": [10.0],
            "high": [11.0],
            "low": [9.0],
            "close": [10.5],
            "volume": [100.0],
            "amount": [1000.0],
            "type": ["5min"],
        },
        index=index,
    )

    def fail(*_args, **_kwargs):
        raise QFQDataNotReadyError("factor gap", scope="stock", code="000001")

    monkeypatch.setattr(qadatastruct, "apply_qfq_to_bars", fail)

    with pytest.raises(QFQDataNotReadyError, match="factor gap"):
        qadatastruct.QA_DataStruct_Stock_min(data).to_qfq()


def test_runtime_to_qfq_calls_are_strict_or_exactly_offline_allowlisted():
    repo_root = Path(__file__).resolve().parents[2]
    hits = set()
    for path, relative_path in _runtime_python_files(repo_root):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8-sig", errors="replace").splitlines(),
            start=1,
        ):
            if ".to_qfq(" in line:
                hits.add((relative_path, line_number))

    assert hits == set(TEMPORARY_OFFLINE_QFACTOR_ALLOWLIST)
    assert all(TEMPORARY_OFFLINE_QFACTOR_ALLOWLIST.values())
    assert _direct_adjustment_collection_hits(repo_root) == set(
        TEMPORARY_DIRECT_ADJUSTMENT_COLLECTION_ALLOWLIST
    )
    assert all(TEMPORARY_DIRECT_ADJUSTMENT_COLLECTION_ALLOWLIST.values())
    assert _fill_one_hits(repo_root) == set(TEMPORARY_FILL_ONE_ALLOWLIST)
    assert all(TEMPORARY_FILL_ONE_ALLOWLIST.values())

    clickhouse_path = (
        repo_root
        / "sunflower"
        / "QUANTAXIS"
        / "QUANTAXIS"
        / "QAFetch"
        / "QAClickhouse.py"
    )
    clickhouse_lines = clickhouse_path.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines()
    assert {
        line_number
        for line_number, line in enumerate(clickhouse_lines, start=1)
        if "quantaxis.stock_adj" in line
    } == {131}
    assert {
        line_number
        for line_number, line in enumerate(clickhouse_lines, start=1)
        if ".fillna(1)" in line
    } == {47, 148, 189, 220}


def test_qfq_adjusted_outputs_are_not_memoized_without_snapshot_version():
    repo_root = Path(__file__).resolve().parents[2]
    adjusted_functions = {
        "freshquant/KlineDataTool.py": {"get_stock_data"},
        "freshquant/data/stock.py": {"fq_data_stock_fetch_atr"},
        "freshquant/data/astock/holding.py": {
            "_compute_atr_last_stock",
            "_query_grid_interval",
        },
        "freshquant/strategy/toolkit/threshold.py": {"_compute_atr_last_stock"},
        "freshquant/quote/etf.py": {"queryEtfCandleSticks"},
        "freshquant/quote/stock.py": {"fq_quote_QA_fetch_stock_day_adv"},
    }

    for relative_path, expected_names in adjusted_functions.items():
        tree = ast.parse((repo_root / relative_path).read_text(encoding="utf-8"))
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in expected_names
        }
        assert set(functions) == expected_names
        for function in functions.values():
            decorators = [ast.unparse(item) for item in function.decorator_list]
            assert not any("memoize" in item for item in decorators)
