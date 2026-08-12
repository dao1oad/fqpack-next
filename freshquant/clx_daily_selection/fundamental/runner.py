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
import hashlib
import json
import os
import pathlib
import shutil
import sys
import urllib.request
from typing import Any

from .contracts import (
    ANALYSIS_DIR_NAME,
    DEEP_TIER_LIMIT,
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
from .local_quotes import build_local_quotes_payload, write_quotes_file
from .data_fetch import fetch_business, fetch_financials, write_symbol_files
from .compact import (
    build_compact,
    latest_report_period,
    merge_compact_metrics,
    write_compact,
)
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


def api_get(url: str, timeout: int = 60) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


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


def cmd_bootstrap(args: argparse.Namespace) -> None:
    """按 official ready 契约拉取正式结果（仓库内自包含）。

    只接受 ready marker 锚定的 official generation：调用
    `/api/clx-daily-selection/official?trade_date=...&direction_mode=all`，
    校验 status/trade_date/batch_id/content_hash 后保存 raw；不通过
    list_batches 猜测“最近 final 批次”。
    """
    run_dir = default_run_dir(args.run_dir)
    trade_date = args.trade_date
    api_base = str(args.api_base).rstrip("/")
    rows: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    cursor = ""
    seen_cursors: set[str] = set()
    while True:
        url = (
            f"{api_base}/api/clx-daily-selection/official"
            f"?trade_date={trade_date}&direction_mode=all&limit=200"
        )
        if cursor:
            url += f"&cursor={cursor}"
        resp = api_get(url)
        status = str(resp.get("status") or "")
        if status != "ready":
            raise SystemExit(
                f"official ready not available for {trade_date}: status={status}"
            )
        resp_trade_date = str(resp.get("trade_date") or "")
        if resp_trade_date and resp_trade_date != trade_date:
            raise SystemExit(
                f"official trade_date mismatch: requested={trade_date} got={resp_trade_date}"
            )
        batch_id = str(resp.get("batch_id") or "")
        content_hash = str(resp.get("content_hash") or "")
        generation_id = str(resp.get("generation_id") or "")
        if not batch_id or not content_hash or not generation_id:
            raise SystemExit(
                f"official payload missing non-empty batch_id/content_hash/"
                f"generation_id: batch_id={batch_id!r} content_hash={content_hash!r} "
                f"generation_id={generation_id!r}"
            )
        if resp.get("is_final") is not True:
            raise SystemExit(f"official ready generation is not final: {batch_id}")
        if not meta:
            meta = dict(resp)
        page = resp.get("rows") or resp.get("items") or []
        rows.extend(page)
        # 翻页 generation 一致性：每页 batch_id/content_hash/generation_id
        # 必须存在、非空且与第一页严格一致；缺失/不一致 fail-closed
        for key in ("batch_id", "content_hash", "generation_id"):
            page_value = str(resp.get(key) or "")
            first_value = str(meta.get(key) or "")
            if not page_value or page_value != first_value:
                raise SystemExit(
                    f"official pagination generation mismatch at {key}: "
                    f"first={first_value!r} page={page_value!r}"
                )
        nxt = str(resp.get("next_cursor") or "")
        if not nxt:
            break
        if nxt in seen_cursors:
            raise SystemExit(f"official endpoint returned a repeated cursor: {nxt}")
        seen_cursors.add(nxt)
        cursor = nxt
    payload = {
        "schema_version": "clx-daily-selection.v2",
        "status": "completed",
        "release_status": "final",
        "batch_id": str(meta["batch_id"]),
        "trade_date": trade_date,
        "evaluation_profile_id": meta.get("evaluation_profile_id"),
        "content_hash": str(meta["content_hash"]),
        "generation_id": meta.get("generation_id"),
        "generation_order": meta.get("generation_order"),
        "publication_id": meta.get("publication_id"),
        "result_time": meta.get("result_time"),
        "counts": meta.get("counts"),
        "total": len(rows),
        "rows": rows,
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    raw = run_dir / "clx-official-raw.json"
    raw.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (run_dir / "clx-batch-identity.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "bootstrap_ok": True,
                "batch_id": str(meta["batch_id"]),
                "generation_id": meta.get("generation_id"),
                "trade_date": trade_date,
                "rows": len(rows),
                "raw_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                "run_dir": str(run_dir),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


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


def cmd_data(args: argparse.Namespace) -> None:
    """多源数据包：本机行情 + 财务/业务（akshare/baostock）+ compact 预聚合。

    prepare 之后、rank 之前调用。产出 run_dir/data/：
      quotes_local_<date>.json        本机行情（全部 pure-buy）
      financials_<symbol>.json        财务摘要/指标/季频（多源降级）
      business_<symbol>.json          公司概况/主营构成/业绩预告
      compact_<symbol>.json           深析单文件（30 指标×6 期 + 增速 + 主营）
      data_report.json                每只成功/失败/来源

    单只失败不阻塞：compact 用可用部分生成，快排回退 THS 指标，深析由 agent
    按 evidence_gap 纪律处理。
    """
    run_dir = default_run_dir(args.run_dir)
    input_path = run_dir / INPUT_JSON_NAME
    if not input_path.is_file():
        raise SystemExit(f"missing input: {input_path} (run prepare first)")
    input_payload = json.loads(input_path.read_text(encoding="utf-8"))
    packages = input_payload.get("packages") or []
    trade_date = input_payload["tradeDate"]
    as_of = f"{trade_date}T15:00:00+08:00"
    latest_period = latest_report_period(trade_date)
    symbols = [clean_text(p.get("symbol")) for p in packages]
    symbols = [s for s in symbols if s]
    report: dict[str, Any] = {
        "schemaVersion": "clx-fundamental-data.v1",
        "runDir": run_dir.name,
        "tradeDate": trade_date,
        "latestPeriod": latest_period,
        "generatedAt": utc_now(),
        "symbols": {},
    }

    quotes = build_local_quotes_payload(symbols, trade_date)
    for symbol in symbols:
        q = quotes.get(symbol)
        if q is None:
            report["symbols"].setdefault(symbol, {})["quote"] = "missing"
    write_quotes_file(run_dir, quotes, trade_date)

    def fetch_one(symbol: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
        financials = fetch_financials(symbol)
        business = fetch_business(symbol)
        return symbol, financials, business

    data_dir = run_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    pending = [
        s for s in symbols
        if not (data_dir / f"compact_{s}.json").is_file()
    ]
    for s in symbols:
        if s not in pending:
            report["symbols"][s] = {"status": "skipped", "compact": True}

    # akshare 的 py_mini_racer（新浪财务指标）非线程安全，并发会触发
    # mini_racer.dll 崩溃，且第三方库会残留非 daemon 线程导致进程挂起；
    # 网络抓取整体放入子进程（顺序执行），子进程退出即清理线程，主进程
    # 不受影响（避免 os._exit 影响 pytest/CI 调用方）。
    partial = run_dir / "data" / "data_report_partial.json"
    if pending:
        import multiprocessing

        ctx = multiprocessing.get_context("spawn")
        proc = ctx.Process(
            target=_data_fetch_worker,
            args=(str(run_dir), pending, latest_period, str(partial)),
        )
        proc.start()
        proc.join(3600)
        if proc.exitcode != 0:
            raise SystemExit(
                f"data fetch worker failed with exit={proc.exitcode}; "
                f"see {partial}"
            )
    if partial.is_file():
        partial_payload = json.loads(partial.read_text(encoding="utf-8"))
        report["symbols"].update(partial_payload.get("symbols") or {})
        report["fetchErrors"] = partial_payload.get("fetchErrors", 0)

    (run_dir / "data_report.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    compact_ok = sum(
        1 for v in report["symbols"].values() if v.get("compact")
    )
    print(
        json.dumps(
            {
                "data_ok": True,
                "trade_date": trade_date,
                "latest_period": latest_period,
                "symbols": len(symbols),
                "compact_ok": compact_ok,
                "compact_missing": len(symbols) - compact_ok,
                "quote_ok": sum(1 for s in symbols if quotes.get(s)),
                "data_dir": str(run_dir / "data"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _data_fetch_worker(
    run_dir_str: str,
    pending: list[str],
    latest_period: str,
    partial_path: str,
) -> None:
    """子进程：串行抓取财务/业务数据并写文件；退出即清理第三方残留线程。"""
    run_dir = pathlib.Path(run_dir_str)
    symbols_payload = {
        "generatedAt": utc_now(),
        "symbols": {},
        "fetchErrors": 0,
    }
    for symbol in pending:
        try:
            financials = fetch_financials(symbol, latest_period=latest_period)
            business = fetch_business(symbol, latest_period=latest_period)
        except Exception as exc:  # noqa: BLE001
            symbols_payload["symbols"][symbol] = {"error": f"fetch: {exc}"}
            symbols_payload["fetchErrors"] += 1
            continue
        write_symbol_files(run_dir, symbol, financials, business)
        quotes_path = run_dir / "data"
        import json as _json

        quotes_files = list(quotes_path.glob("quotes_local_*.json"))
        quotes = {}
        if quotes_files:
            quotes = _json.loads(quotes_files[0].read_text(encoding="utf-8")).get(
                symbol
            ) or {}
        compact = build_compact(
            symbol,
            quotes,
            financials,
            business,
            latest_period=latest_period,
        )
        write_compact(run_dir, symbol, compact)
        symbols_payload["symbols"][symbol] = {
            "financials": sorted(financials.keys()),
            "business": sorted(business.keys()),
            "compact": True,
            "quote": bool(quotes),
        }
        if len(symbols_payload["symbols"]) % 10 == 0:
            print(f"  data progress: {len(symbols_payload['symbols'])}", flush=True)
    pathlib.Path(partial_path).write_text(
        json.dumps(symbols_payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    sys.exit(0)


def cmd_rank(args: argparse.Namespace) -> None:
    run_dir = default_run_dir(args.run_dir)
    input_path = run_dir / INPUT_JSON_NAME
    if not input_path.is_file():
        raise SystemExit(f"missing input: {input_path} (run prepare first)")
    input_payload = json.loads(input_path.read_text(encoding="utf-8"))
    packages = input_payload.get("packages") or []
    # 快排指标源优先使用 compact 多源数据（覆盖 THS 缓存；缺失回退）
    data_dir = run_dir / "data"
    compact_used = 0
    for package in packages:
        symbol = clean_text(package.get("symbol"))
        compact_path = data_dir / f"compact_{symbol}.json"
        if compact_path.is_file():
            try:
                compact = json.loads(compact_path.read_text(encoding="utf-8"))
                package["metrics"] = merge_compact_metrics(package, compact)
                compact_used += 1
            except (json.JSONDecodeError, OSError):
                pass
    trade_date = input_payload["tradeDate"]
    batch_id = input_payload.get("batchId") or ""
    content_hash = input_payload.get("contentHash") or ""
    run_id = args.run_id or frontend_run_id(trade_date, batch_id)
    as_of = f"{trade_date}T15:00:00+08:00"
    generated_at = utc_now()
    rows = compute_quick_rank(packages, as_of=as_of, deep_limit=args.deep_limit)
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
                "compact_metrics_used": compact_used,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_deep_run(args: argparse.Namespace) -> None:
    from .deep_executor import DeepExecutor

    run_dir = default_run_dir(args.run_dir)
    executor = DeepExecutor(
        run_dir,
        workers=args.workers,
        max_attempts=args.max_attempts,
        agent_command=args.agent_command,
        dry_run=args.dry_run,
        timeout=args.timeout,
    )
    report = executor.run()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))


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
    from .validate import validate_analysis_doc

    ranking_path = run_dir / RANKING_JSON_NAME
    payload = read_ranking_json(ranking_path)
    for row in payload.get("rows") or []:
        symbol = row["symbol"]
        tier = row.get("tier")
        row["analysis_href"] = ""
        row["snapshot_href"] = ""
        if tier == TIER_DEEP:
            doc_path = run_dir / ANALYSIS_DIR_NAME / f"{symbol}.json"
            doc_ok = False
            if doc_path.is_file():
                try:
                    doc = json.loads(doc_path.read_text(encoding="utf-8"))
                    doc_ok, _ = validate_analysis_doc(doc)
                except (json.JSONDecodeError, OSError):
                    doc_ok = False
            if doc_ok:
                row["analysis_href"] = f"{base_href}/{ANALYSIS_DIR_NAME}/{symbol}.json"
        else:
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

    b = sub.add_parser(
        "bootstrap", help="fetch official CLX batch (repo self-contained)"
    )
    b.add_argument("--run-dir", type=pathlib.Path, required=True)
    b.add_argument("--trade-date", required=True)
    b.add_argument("--api-base", default="http://127.0.0.1:15000")
    b.set_defaults(func=cmd_bootstrap)

    r = sub.add_parser("rank", help="deterministic quick rank + deep merge + snapshots")
    r.add_argument("--run-dir", type=pathlib.Path, required=True)
    r.add_argument("--analysis-dir", type=pathlib.Path, default=None)
    r.add_argument("--run-id", default="")
    r.add_argument("--deep-limit", type=int, default=DEEP_TIER_LIMIT)
    r.set_defaults(func=cmd_rank)

    d = sub.add_parser("deep-run", help="run top-100 deep analysis via repo adapter")
    d.add_argument("--run-dir", type=pathlib.Path, required=True)
    d.add_argument("--workers", type=int, default=2)
    d.add_argument("--max-attempts", type=int, default=2)
    d.add_argument("--timeout", type=int, default=1500)
    d.add_argument("--agent-command", default=None)
    d.add_argument("--dry-run", action="store_true")
    d.set_defaults(func=cmd_deep_run)

    data = sub.add_parser(
        "data", help="multi-source data pack: local quotes + financials + compact"
    )
    data.add_argument("--run-dir", type=pathlib.Path, required=True)
    data.add_argument("--workers", type=int, default=6)
    data.set_defaults(func=cmd_data)

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
