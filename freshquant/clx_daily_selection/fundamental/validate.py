"""产物校验：JSON Schema + 结构规则 + 排序确定性检查。"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from .contracts import (
    ANALYSIS_SCHEMA_VERSION,
    RANKING_JSON_NAME,
    RANKING_SCHEMA_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    STATS_JSON_NAME,
    STATS_SCHEMA_VERSION,
    TIER_DEEP,
)
from .deep_analysis import validate_doc


def load_schema(name: str) -> dict[str, Any]:
    path = pathlib.Path(__file__).parent / "schemas" / name
    return json.loads(path.read_text(encoding="utf-8"))


def validate_schema(
    payload: dict[str, Any], schema: dict[str, Any]
) -> tuple[bool, list[str]]:
    try:
        import jsonschema

        validator = jsonschema.Draft7Validator(schema)
        errors = sorted(error.message for error in validator.iter_errors(payload))
        return (not errors, errors)
    except ImportError:
        return (True, [])


def validate_ranking(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    schema = load_schema("clx-fundamental-ranking.schema.json")
    ok, errors = validate_schema(payload, schema)
    if payload.get("schemaVersion") != RANKING_SCHEMA_VERSION:
        errors.append(f"unexpected schemaVersion: {payload.get('schemaVersion')!r}")
    rows = payload.get("rows") or []
    if payload.get("counts", {}).get("total") != len(rows):
        errors.append("counts.total != rows length")
    deep = [row for row in rows if row.get("tier") == TIER_DEEP]
    snapshot = [row for row in rows if row.get("tier") != TIER_DEEP]
    if payload.get("counts", {}).get("deep") != len(deep):
        errors.append("counts.deep != deep rows")
    if payload.get("counts", {}).get("snapshot") != len(snapshot):
        errors.append("counts.snapshot != snapshot rows")
    ranks = [int(row.get("rank", 0)) for row in rows]
    if ranks != list(range(1, len(rows) + 1)):
        errors.append("rank column must be 1..N sequential")
    symbols = [str(row.get("symbol", "")) for row in rows]
    if len(set(symbols)) != len(symbols):
        errors.append("duplicate symbols")
    return not errors, errors


def validate_analysis_doc(doc: dict[str, Any]) -> tuple[bool, list[str]]:
    schema = load_schema("fundamental-analysis.schema.json")
    ok, errors = validate_schema(doc, schema)
    if doc.get("schemaVersion") != ANALYSIS_SCHEMA_VERSION:
        errors.append(f"unexpected schemaVersion: {doc.get('schemaVersion')!r}")
    structural_ok, structural = validate_doc(doc, deep=True)
    if not structural_ok:
        errors.extend(structural)
    return ok and not errors, errors


def validate_snapshot_doc(doc: dict[str, Any]) -> tuple[bool, list[str]]:
    schema = load_schema("fundamental-snapshot.schema.json")
    ok, errors = validate_schema(doc, schema)
    if doc.get("schemaVersion") != SNAPSHOT_SCHEMA_VERSION:
        errors.append(f"unexpected schemaVersion: {doc.get('schemaVersion')!r}")
    structural_ok, structural = validate_doc(doc, deep=False)
    if not structural_ok:
        errors.extend(structural)
    return ok and not errors, errors


def validate_stats(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    schema = load_schema("fundamental-stats.schema.json")
    ok, errors = validate_schema(payload, schema)
    if payload.get("schemaVersion") != STATS_SCHEMA_VERSION:
        errors.append(f"unexpected schemaVersion: {payload.get('schemaVersion')!r}")
    summary = payload.get("summary") or {}
    gates = payload.get("qualityGates") or {}
    if summary.get("deepCompleteRate") is not None and summary.get("deep") not in {
        None,
        0,
    }:
        if not (0 <= summary["deepCompleteRate"] <= 1):
            errors.append("deepCompleteRate out of range")
    required_gates = (
        "deepCompletionRate",
        "evidenceABShare",
        "evidenceDCount",
        "collectionCompleteness",
    )
    for name in required_gates:
        if name not in gates:
            errors.append(f"missing quality gate: {name}")
    return not errors, errors


def check_deterministic_csv(
    path_a: pathlib.Path, path_b: pathlib.Path
) -> tuple[bool, str]:
    if not path_a.is_file() or not path_b.is_file():
        return False, "missing csv path"
    bytes_a = path_a.read_bytes()
    bytes_b = path_b.read_bytes()
    if bytes_a == bytes_b:
        return True, "byte-identical"
    return False, f"differ ({len(bytes_a)} vs {len(bytes_b)} bytes)"


def validate_run_dir(run_dir: pathlib.Path) -> dict[str, Any]:
    """校验 run 目录内全部产物，返回结构化结果。"""
    run_dir = pathlib.Path(run_dir)
    ranking_path = run_dir / RANKING_JSON_NAME
    results: dict[str, Any] = {
        "schemaVersion": "fundamental-validation.v1",
        "checks": {},
        "passed": True,
    }
    if ranking_path.is_file():
        payload = json.loads(ranking_path.read_text(encoding="utf-8"))
        ok, errors = validate_ranking(payload)
        results["checks"]["ranking"] = {"passed": ok, "errors": errors}
        results["passed"] = results["passed"] and ok
    analysis_dir = run_dir / "fundamental-analysis"
    analysis_checks = {}
    for path in sorted(analysis_dir.glob("*.json")) if analysis_dir.is_dir() else []:
        doc = json.loads(path.read_text(encoding="utf-8"))
        ok, errors = validate_analysis_doc(doc)
        analysis_checks[path.stem] = {"passed": ok, "errors": errors}
        results["passed"] = results["passed"] and ok
    results["checks"]["analysis"] = analysis_checks
    snapshot_dir = run_dir / "fundamental-snapshot"
    snapshot_checks = {}
    for path in sorted(snapshot_dir.glob("*.json")) if snapshot_dir.is_dir() else []:
        if path.name == "manifest.json":
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        ok, errors = validate_snapshot_doc(doc)
        snapshot_checks[path.stem] = {"passed": ok, "errors": errors}
        results["passed"] = results["passed"] and ok
    results["checks"]["snapshot"] = snapshot_checks
    stats_path = run_dir / STATS_JSON_NAME
    if stats_path.is_file():
        payload = json.loads(stats_path.read_text(encoding="utf-8"))
        ok, errors = validate_stats(payload)
        results["checks"]["stats"] = {"passed": ok, "errors": errors}
        results["passed"] = results["passed"] and ok
    return results
