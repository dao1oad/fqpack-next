"""CLX 基本面评价每日跑批编排入口。

子命令：
  prepare   从 CLX 正式批次提取 pure-buy Stock，装配证据包（含缓存复用）
  rank      全量确定性快排 + 深析合并 + 快照 + 深析规格生成
  stats     统计聚合 + 批次质量门
  consistency  与上一运行对比深析等级一致率
  validate  产物 schema/结构校验
  publish   写入外部数据目录并扩展 latest.json / index.json
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import shutil
from typing import Any

from .contracts import (
    ANALYSIS_DIR_NAME,
    INPUT_JSON_NAME,
    INPUT_SCHEMA_VERSION,
    LATEST_SCHEMA_VERSION,
    RANKING_CSV_NAME,
    RANKING_JSON_NAME,
    SIX_DIMENSIONS,
    SNAPSHOT_DIR_NAME,
    SPEC_DIR_NAME,
    STATS_JSON_NAME,
    TIER_DEEP,
    TIER_SNAPSHOT,
    VALIDATION_JSON_NAME,
)
from .deep_analysis import (
    load_analysis_docs,
    merge_deep_docs,
    validate_doc,
    write_deep_specs,
    write_snapshots,
)
from .evidence import EvidenceCache, clean_text, normalize_symbol
from .history import apply_consecutive_counts
from .quick_rank import (
    compute_quick_rank,
    ranking_payload,
    read_ranking_json,
    write_ranking_csv,
    write_ranking_json,
)
from .stats import aggregate_stats, write_stats
from .validate import validate_run_dir


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def classify_direction_mode(directions: Any) -> str:
    normalized = sorted(
        {
            str(item or "").strip()
            for item in (directions or [])
            if str(item or "").strip() in {"buy", "sell"}
        }
    )
    if not normalized:
        return "no_signal"
    if normalized == ["buy"]:
        return "pure_buy"
    if normalized == ["sell"]:
        return "pure_sell"
    return "mixed"


def frontend_run_id(trade_date: str, batch_id: str) -> str:
    suffix = str(batch_id).rsplit("-", 1)[-1]
    return f"{trade_date}-fundamental-{suffix}"


def default_run_dir(run_dir: pathlib.Path) -> pathlib.Path:
    return run_dir.resolve()


def read_raw_rows(raw_path: pathlib.Path) -> list[dict[str, Any]]:
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    return payload.get("rows") or []


def cmd_prepare(args: argparse.Namespace) -> None:
    run_dir = default_run_dir(args.run_dir)
    raw_path = (args.raw or run_dir / "clx-official-raw.json").resolve()
    if not raw_path.is_file():
        raise SystemExit(f"missing official raw: {raw_path}")
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    trade_date = args.trade_date or clean_text(payload.get("trade_date"))
    if not trade_date:
        raise SystemExit("trade_date required (--trade-date or raw payload)")
    evidence_root = args.evidence_dir or run_dir / "evidence"
    evidence_root = evidence_root.resolve()
    cache_root = (args.evidence_cache or evidence_root).resolve()
    cache = EvidenceCache(cache_root)
    rows = payload.get("rows") or []
    pure_buy = [
        row
        for row in rows
        if clean_text(row.get("asset_type") or "").lower() == "stock"
        and classify_direction_mode(row.get("directions")) == "pure_buy"
    ]
    pure_buy.sort(
        key=lambda row: clean_text(row.get("symbol") or row.get("code") or "")
    )
    packages: list[dict[str, Any]] = []
    for index, row in enumerate(pure_buy, start=1):
        symbol = normalize_symbol(row.get("symbol") or row.get("code"))
        package = cache.evidence_package(symbol, args.financial_cutoff, trade_date)
        package["name"] = clean_text(row.get("name")) or package.get("name", "")
        package["latest_price"] = (
            float(row["latest_price"]) if row.get("latest_price") is not None else None
        )
        package["original_clx_rank"] = index
        package["distinct_model_count"] = int(row.get("distinct_model_count") or 0)
        package["distinct_condition_count"] = int(
            row.get("distinct_condition_count") or 0
        )
        package["independent_signal_family_count"] = int(
            row.get("independent_signal_family_count") or 0
        )
        packages.append(package)
    input_payload = {
        "schemaVersion": INPUT_SCHEMA_VERSION,
        "tradeDate": trade_date,
        "batchId": clean_text(payload.get("batch_id")),
        "contentHash": clean_text(payload.get("content_hash")),
        "financialCutoff": args.financial_cutoff,
        "pureBuyStockCount": len(packages),
        "packages": packages,
    }
    output = (run_dir / INPUT_JSON_NAME).resolve()
    output.write_text(
        json.dumps(
            input_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "prepare_ok": True,
                "trade_date": trade_date,
                "pure_buy_stock_count": len(packages),
                "output": str(output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_rank(args: argparse.Namespace) -> None:
    run_dir = default_run_dir(args.run_dir)
    input_path = run_dir / INPUT_JSON_NAME
    if not input_path.is_file():
        raise SystemExit(f"missing input: {input_path} (run prepare first)")
    input_payload = json.loads(input_path.read_text(encoding="utf-8"))
    packages = input_payload.get("packages") or []
    trade_date = input_payload["tradeDate"]
    batch_id = input_payload.get("batchId") or ""
    content_hash = input_payload.get("contentHash") or ""
    run_id = args.run_id or frontend_run_id(trade_date, batch_id)
    as_of = f"{trade_date}T15:00:00+08:00"
    generated_at = utc_now()
    rows = compute_quick_rank(packages, as_of=as_of)
    analysis_docs = load_analysis_docs(args.analysis_dir or run_dir)
    rows, merged_count = merge_deep_docs(
        rows, analysis_docs, deep_limit=args.deep_limit
    )
    payload = ranking_payload(
        rows,
        trade_date=trade_date,
        run_id=run_id,
        batch_id=batch_id,
        content_hash=content_hash,
        generated_at=generated_at,
        as_of=as_of,
    )
    write_ranking_json(run_dir / RANKING_JSON_NAME, payload)
    write_ranking_csv(run_dir / RANKING_CSV_NAME, rows)
    write_snapshots(run_dir, rows, as_of)
    spec_paths = write_deep_specs(run_dir, rows, as_of)
    validation = validate_run_dir(run_dir)
    (run_dir / VALIDATION_JSON_NAME).write_text(
        json.dumps(validation, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    deep = [row for row in rows if row.get("tier") == TIER_DEEP]
    print(
        json.dumps(
            {
                "rank_ok": True,
                "run_id": run_id,
                "total": len(rows),
                "deep": len(deep),
                "snapshot": len(rows) - len(deep),
                "deep_merged": merged_count,
                "deep_missing": len(deep) - merged_count,
                "specs": len(spec_paths),
                "validation_passed": validation["passed"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_stats(args: argparse.Namespace) -> None:
    run_dir = default_run_dir(args.run_dir)
    payload = read_ranking_json(run_dir / RANKING_JSON_NAME)
    rows = payload.get("rows") or []
    rerun_consistency_pct = None
    if args.previous_run_dir:
        rerun_consistency_pct = compute_rerun_consistency(
            run_dir, args.previous_run_dir.resolve()
        )
    stats = aggregate_stats(
        rows,
        trade_date=payload["tradeDate"],
        run_id=payload["runId"],
        batch_id=payload["batchId"],
        content_hash=payload["contentHash"],
        generated_at=payload["generatedAt"],
        as_of=payload["asOf"],
        rerun_consistency_pct=rerun_consistency_pct,
    )
    write_stats(run_dir, stats)
    print(
        json.dumps(
            {
                "stats_ok": True,
                "summary": stats["summary"],
                "quality_gate_status": stats["qualityGateStatus"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def compute_rerun_consistency(
    run_dir: pathlib.Path, previous_run_dir: pathlib.Path
) -> float | None:
    """对比当前与上一运行的深析六维等级一致率（同 symbol 同报告期）。"""
    current = load_analysis_docs(run_dir)
    previous = load_analysis_docs(previous_run_dir)
    pairs = []
    for symbol, doc in current.items():
        prev = previous.get(symbol)
        if not prev:
            continue
        if doc.get("financialReportDate") != prev.get("financialReportDate"):
            continue
        pairs.append((doc, prev))
    if not pairs:
        return None
    agree = 0
    total = 0
    for doc, prev in pairs:
        for dimension in SIX_DIMENSIONS:
            current_grade = (
                (doc.get("sixDimensionScores") or {}).get(dimension, {}).get("grade")
            )
            previous_grade = (
                (prev.get("sixDimensionScores") or {}).get(dimension, {}).get("grade")
            )
            if current_grade is None or previous_grade is None:
                continue
            total += 1
            if current_grade == previous_grade:
                agree += 1
    return agree / total if total else None


def cmd_consistency(args: argparse.Namespace) -> None:
    run_dir = default_run_dir(args.run_dir)
    pct = compute_rerun_consistency(run_dir, args.previous_run_dir.resolve())
    report = {
        "schemaVersion": "fundamental-consistency.v1",
        "runId": run_dir.name,
        "previousRunDir": str(args.previous_run_dir.resolve()),
        "rerunConsistencyPct": pct,
        "threshold": 0.95,
        "passed": pct is not None and pct >= 0.95,
    }
    path = run_dir / "fundamental-consistency.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


def cmd_validate(args: argparse.Namespace) -> None:
    run_dir = default_run_dir(args.run_dir)
    validation = validate_run_dir(run_dir)
    (run_dir / VALIDATION_JSON_NAME).write_text(
        json.dumps(validation, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    if not validation["passed"]:
        raise SystemExit("validation failed")


def _patch_hrefs(
    run_dir: pathlib.Path, run_id: str, trade_date: str, base_href: str
) -> None:
    ranking_path = run_dir / RANKING_JSON_NAME
    payload = read_ranking_json(ranking_path)
    for row in payload.get("rows") or []:
        symbol = row["symbol"]
        tier = row.get("tier")
        if tier == TIER_DEEP:
            row["analysis_href"] = f"{base_href}/{ANALYSIS_DIR_NAME}/{symbol}.json"
        row["snapshot_href"] = f"{base_href}/{SNAPSHOT_DIR_NAME}/{symbol}.json"
    write_ranking_json(ranking_path, payload)
    write_ranking_csv(run_dir / RANKING_CSV_NAME, payload.get("rows") or [])


def cmd_publish(args: argparse.Namespace) -> None:
    run_dir = default_run_dir(args.run_dir)
    data_dir = args.data_dir.resolve()
    ranking_path = run_dir / RANKING_JSON_NAME
    if not ranking_path.is_file():
        raise SystemExit(f"missing ranking: {ranking_path}")
    payload = read_ranking_json(ranking_path)
    trade_date = payload["tradeDate"]
    batch_id = payload["batchId"]
    run_id = (
        args.run_id or payload.get("runId") or frontend_run_id(trade_date, batch_id)
    )
    deep_rows = [
        row for row in payload.get("rows") or [] if row.get("tier") == TIER_DEEP
    ]
    deep_complete = [row for row in deep_rows if row.get("grade_source") == "deep"]
    if len(deep_complete) != len(deep_rows) and not args.allow_incomplete_deep:
        missing = sorted(
            row["symbol"] for row in deep_rows if row.get("grade_source") != "deep"
        )
        raise SystemExit(
            f"deep analysis incomplete ({len(deep_complete)}/{len(deep_rows)}); "
            f"missing={','.join(missing[:20])}; use --allow-incomplete-deep to publish with amber gate"
        )
    target = data_dir / "runs" / trade_date / run_id
    target.mkdir(parents=True, exist_ok=True)
    base_href = f"/data/clx-evaluator/runs/{trade_date}/{run_id}"
    _patch_hrefs(run_dir, run_id, trade_date, base_href)
    payload = read_ranking_json(ranking_path)
    rows = payload.get("rows") or []
    apply_consecutive_counts(rows, data_dir, trade_date)
    write_ranking_json(ranking_path, payload)
    write_ranking_csv(run_dir / RANKING_CSV_NAME, rows)

    stats_path = run_dir / STATS_JSON_NAME
    if not stats_path.is_file():
        raise SystemExit(f"missing stats: {stats_path} (run stats first)")

    for name in (
        RANKING_JSON_NAME,
        RANKING_CSV_NAME,
        STATS_JSON_NAME,
        VALIDATION_JSON_NAME,
    ):
        shutil.copy2(run_dir / name, target / name)
    for sub in (ANALYSIS_DIR_NAME, SNAPSHOT_DIR_NAME, SPEC_DIR_NAME):
        source = run_dir / sub
        if source.is_dir():
            shutil.copytree(source, target / sub, dirs_exist_ok=True)
    manifest = {
        "schemaVersion": "clx-fundamental-run.v1",
        "runId": run_id,
        "tradeDate": trade_date,
        "batchId": batch_id,
        "contentHash": payload["contentHash"],
        "generatedAt": payload["generatedAt"],
        "status": "published",
        "qualityGateStatus": json.loads(stats_path.read_text(encoding="utf-8"))[
            "qualityGateStatus"
        ],
        "artifacts": {
            "ranking": f"{base_href}/{RANKING_JSON_NAME}",
            "rankingCsv": f"{base_href}/{RANKING_CSV_NAME}",
            "stats": f"{base_href}/{STATS_JSON_NAME}",
            "validation": f"{base_href}/{VALIDATION_JSON_NAME}",
        },
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )

    ranking_href = f"{base_href}/{RANKING_JSON_NAME}"
    stats_href = f"{base_href}/{STATS_JSON_NAME}"
    latest: dict[str, Any] = {
        "schemaVersion": LATEST_SCHEMA_VERSION,
        "tradeDate": trade_date,
        "runId": run_id,
        "href": "",
        "fundamentalRankingHref": ranking_href,
        "fundamentalRankingCsvHref": f"{base_href}/{RANKING_CSV_NAME}",
        "statsHref": stats_href,
        "promotedAt": payload["generatedAt"],
    }
    latest_path = data_dir / "latest.json"
    previous_latest: dict[str, Any] = {}
    if latest_path.is_file():
        try:
            previous_latest = json.loads(latest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous_latest = {}
    latest["href"] = previous_latest.get("href", "")
    latest_path.write_text(
        json.dumps(latest, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )

    index_path = data_dir / "index.json"
    index: dict[str, Any] = {"schemaVersion": "clx-eval-index.v1", "runs": []}
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            index = {"schemaVersion": "clx-eval-index.v1", "runs": []}
    entry = {
        "tradeDate": trade_date,
        "runId": run_id,
        "status": "published",
        "generatedAt": payload["generatedAt"],
        "fundamentalRankingHref": ranking_href,
        "statsHref": stats_href,
    }
    index["runs"] = [entry] + [
        row for row in index.get("runs", []) if row.get("runId") != run_id
    ]
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "publish_ok": True,
                "run_id": run_id,
                "target": str(target),
                "latest": str(latest_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "prepare", help="extract pure-buy stocks and assemble evidence packages"
    )
    p.add_argument("--run-dir", type=pathlib.Path, required=True)
    p.add_argument("--trade-date", default="")
    p.add_argument("--raw", type=pathlib.Path, default=None)
    p.add_argument("--evidence-dir", type=pathlib.Path, default=None)
    p.add_argument("--evidence-cache", type=pathlib.Path, default=None)
    p.add_argument("--financial-cutoff", default="2026-06-30")
    p.set_defaults(func=cmd_prepare)

    r = sub.add_parser("rank", help="deterministic quick rank + deep merge + snapshots")
    r.add_argument("--run-dir", type=pathlib.Path, required=True)
    r.add_argument("--analysis-dir", type=pathlib.Path, default=None)
    r.add_argument("--run-id", default="")
    r.add_argument("--deep-limit", type=int, default=100)
    r.set_defaults(func=cmd_rank)

    s = sub.add_parser("stats", help="aggregate stats and quality gates")
    s.add_argument("--run-dir", type=pathlib.Path, required=True)
    s.add_argument("--previous-run-dir", type=pathlib.Path, default=None)
    s.set_defaults(func=cmd_stats)

    c = sub.add_parser("consistency", help="compare deep grades with previous run")
    c.add_argument("--run-dir", type=pathlib.Path, required=True)
    c.add_argument("--previous-run-dir", type=pathlib.Path, required=True)
    c.set_defaults(func=cmd_consistency)

    v = sub.add_parser("validate", help="validate run-dir artifacts")
    v.add_argument("--run-dir", type=pathlib.Path, required=True)
    v.set_defaults(func=cmd_validate)

    pub = sub.add_parser("publish", help="publish to external data dir + latest/index")
    pub.add_argument("--run-dir", type=pathlib.Path, required=True)
    pub.add_argument("--data-dir", type=pathlib.Path, required=True)
    pub.add_argument("--run-id", default="")
    pub.add_argument("--allow-incomplete-deep", action="store_true")
    pub.set_defaults(func=cmd_publish)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
