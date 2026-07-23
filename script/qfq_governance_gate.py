"""Governed XTData QFQ bootstrap and runtime evidence checks.

The governance runner treats this module as a normal command-line Gate.  The
module keeps deployment identity checks independent from the data checks so a
successful Mongo/API probe can never be attached to a different deployment.
All result files are JSON and may be redirected to a fixture directory in
tests with ``--evidence-root``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ISSUE_ID = "ISSUE-467"
DEFAULT_FORMAL_DEPLOY_ROOT = Path(
    os.environ.get("FQ_FORMAL_DEPLOY_ROOT", r"D:\fqpack\runtime\formal-deploy")
)
DEFAULT_EVIDENCE_ROOT = Path(
    os.environ.get(
        "FQ_QFQ_EVIDENCE_ROOT",
        rf"D:\fqpack\runtime\artifacts\{ISSUE_ID}\qfq-gates",
    )
)
DEFAULT_STATE_NAME = "production-state.json"
DEFAULT_API_URLS = (
    "http://127.0.0.1:15000/api/runtime/health/summary",
    "http://127.0.0.1:15000/api/stock_data?period=1d&symbol=sh600381&endDate=2012-05-14&barCount=300",
    "http://127.0.0.1:15000/api/stock_data?period=1d&symbol=sz159995&endDate=2026-07-06&barCount=300",
    "http://127.0.0.1:15000/api/stock_data?period=1d&symbol=sh000300&endDate=2026-07-06&barCount=300",
)
KNOWN_CHECKS = {
    "deployment",
    "qfq",
    "mongo",
    "api",
    "dagster",
    "coverage",
    "health",
    "runtime",
    "cleanup",
}
MARKET_JOB_NAMES = ("stock_data_job", "etf_data_job", "index_data_job")


class GateError(RuntimeError):
    """A deterministic Gate failure with a user-facing reason."""


@dataclass(frozen=True)
class DeploymentContext:
    repo_root: str
    head_sha: str | None
    origin_main_sha: str | None
    deployed_sha: str | None
    deployed_at: str | None
    latest_run_dir: str | None
    state_path: str
    formal_deploy_root: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalise_sha(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    return text or None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def run_git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise GateError(
            f"git {' '.join(args)} failed: {(completed.stderr or completed.stdout).strip()}"
        )
    return completed.stdout.strip()


def _latest_formal_result(
    formal_deploy_root: Path,
    deployed_sha: str | None = None,
) -> tuple[Path | None, dict[str, Any] | None, datetime | None]:
    runs_root = formal_deploy_root / "runs"
    candidates: list[tuple[datetime, Path, dict[str, Any]]] = []
    if not runs_root.exists():
        return None, None, None
    for result_path in runs_root.glob("*/result.json"):
        payload = _read_json(result_path)
        if not payload or payload.get("ok") is not True:
            continue
        current_sha = _normalise_sha(payload.get("current_sha"))
        if deployed_sha and current_sha and current_sha != _normalise_sha(deployed_sha):
            continue
        timestamp = None
        for key in ("finishedAt", "finished_at", "last_success_at", "deployedAt"):
            timestamp = parse_time(payload.get(key))
            if timestamp:
                break
        if timestamp is None:
            try:
                timestamp = datetime.fromtimestamp(
                    result_path.stat().st_mtime, tz=timezone.utc
                )
            except OSError:
                continue
        candidates.append((timestamp, result_path.parent, payload))
    if not candidates:
        return None, None, None
    timestamp, run_dir, payload = max(candidates, key=lambda item: item[0])
    return run_dir, payload, timestamp


def load_deployment_context(
    repo_root: Path | str | None = None,
    *,
    state_path: Path | str | None = None,
    formal_deploy_root: Path | str | None = None,
) -> DeploymentContext:
    root = Path(repo_root or Path(__file__).resolve().parents[1]).resolve()
    deploy_root = Path(formal_deploy_root or DEFAULT_FORMAL_DEPLOY_ROOT)
    state = Path(state_path or deploy_root / DEFAULT_STATE_NAME)
    state_payload = _read_json(state) or {}
    deployed_sha = _normalise_sha(state_payload.get("last_success_sha"))
    deployed_at = state_payload.get("last_success_at")
    run_dir, run_payload, run_time = _latest_formal_result(deploy_root, deployed_sha)
    # A state file can lag briefly while the formal deploy worker is writing
    # its result.  Treat a newer successful run artifact as the latest deploy
    # boundary, while still retaining the state SHA when the artifact omits it.
    latest_any_dir, latest_any_payload, latest_any_time = _latest_formal_result(
        deploy_root, None
    )
    state_time = parse_time(deployed_at)
    if latest_any_time and (state_time is None or latest_any_time > state_time):
        run_dir = latest_any_dir
        run_payload = latest_any_payload
        run_time = latest_any_time
        deployed_at = latest_any_time.isoformat().replace("+00:00", "Z")
        if latest_any_payload:
            deployed_sha = _normalise_sha(
                latest_any_payload.get("current_sha") or deployed_sha
            )
    if not deployed_at and run_payload:
        deployed_at = (
            run_payload.get("finishedAt")
            or run_payload.get("finished_at")
            or run_payload.get("last_success_at")
        )
    if not deployed_at and run_time:
        deployed_at = run_time.isoformat().replace("+00:00", "Z")

    head_sha: str | None = None
    origin_sha: str | None = None
    try:
        head_sha = _normalise_sha(run_git(root, "rev-parse", "HEAD"))
    except GateError:
        pass
    try:
        origin_sha = _normalise_sha(run_git(root, "rev-parse", "origin/main"))
    except GateError:
        pass
    return DeploymentContext(
        repo_root=str(root),
        head_sha=head_sha,
        origin_main_sha=origin_sha,
        deployed_sha=deployed_sha,
        deployed_at=str(deployed_at) if deployed_at else None,
        latest_run_dir=str(run_dir) if run_dir else None,
        state_path=str(state),
        formal_deploy_root=str(deploy_root),
    )


def deployment_identity_failures(context: DeploymentContext) -> list[str]:
    failures: list[str] = []
    if not context.deployed_sha:
        failures.append("formal deploy state has no last_success_sha")
    if not context.deployed_at:
        failures.append("formal deploy state has no last_success_at")
    if not context.head_sha:
        failures.append("current HEAD cannot be resolved")
    if not context.origin_main_sha:
        failures.append("origin/main cannot be resolved")
    values = {
        value
        for value in (context.head_sha, context.origin_main_sha, context.deployed_sha)
        if value
    }
    if len(values) > 1:
        failures.append(
            "HEAD, origin/main and deployed SHA differ: "
            f"head={context.head_sha} origin/main={context.origin_main_sha} "
            f"deployed={context.deployed_sha}"
        )
    return failures


def assert_deployed_main(
    repo_root: Path | str | None = None,
    *,
    state_path: Path | str | None = None,
    formal_deploy_root: Path | str | None = None,
) -> DeploymentContext:
    context = load_deployment_context(
        repo_root,
        state_path=state_path,
        formal_deploy_root=formal_deploy_root,
    )
    failures = deployment_identity_failures(context)
    if failures:
        raise GateError("deployed-main check failed: " + "; ".join(failures))
    return context


def assert_after_latest_deploy(
    finished_at: Any,
    context: DeploymentContext,
) -> None:
    finished = parse_time(finished_at)
    deployed = parse_time(context.deployed_at)
    if finished is None:
        raise GateError("result has no parseable finishedAt")
    if deployed is None:
        raise GateError("formal deploy has no parseable deployedAt")
    if finished <= deployed:
        raise GateError(
            f"result finishedAt must be later than deployedAt: {finished.isoformat()} <= {deployed.isoformat()}"
        )


def _check_identity(
    payload: Mapping[str, Any],
    context: DeploymentContext,
    *,
    require_after: bool,
) -> list[str]:
    failures: list[str] = []
    payload_sha = _normalise_sha(
        payload.get("deployedSha")
        or payload.get("deployed_sha")
        or payload.get("current_sha")
    )
    if not payload_sha:
        failures.append("evidence has no deployed SHA")
    elif not context.deployed_sha:
        failures.append("formal deploy context has no deployed SHA")
    elif payload_sha != context.deployed_sha:
        failures.append(
            f"evidence deployed SHA {payload_sha} does not match {context.deployed_sha}"
        )
    if require_after:
        try:
            result_time = next(
                (
                    payload.get(key)
                    for key in (
                        "finishedAt",
                        "finished_at",
                        "captured_at",
                        "capturedAt",
                        "verified_at",
                        "updated_at",
                    )
                    if payload.get(key)
                ),
                None,
            )
            assert_after_latest_deploy(result_time, context)
        except GateError as exc:
            failures.append(str(exc))
    return failures


def _evidence_paths(root: Path, names: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for name in names:
        candidate = root / f"{name}.json"
        if candidate.exists():
            paths.append(candidate)
        nested = root / name / "result.json"
        if nested.exists():
            paths.append(nested)
    return paths


def load_latest_evidence(
    evidence_root: Path | str,
    names: Iterable[str],
) -> tuple[Path | None, dict[str, Any] | None]:
    root = Path(evidence_root)
    candidates: list[tuple[datetime, Path, dict[str, Any]]] = []
    for path in _evidence_paths(root, names):
        payload = _read_json(path)
        if payload is None:
            continue
        timestamp = next(
            (
                parse_time(payload.get(key))
                for key in (
                    "finishedAt",
                    "finished_at",
                    "captured_at",
                    "capturedAt",
                    "verified_at",
                    "updated_at",
                )
                if payload.get(key)
            ),
            None,
        )
        if timestamp is None:
            try:
                timestamp = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                )
            except OSError:
                continue
        candidates.append((timestamp, path, payload))
    if not candidates:
        return None, None
    _, path, payload = max(candidates, key=lambda item: item[0])
    return path, payload


def persist_evidence(
    evidence_root: Path | str,
    name: str,
    payload: Mapping[str, Any],
    *,
    aliases: Iterable[str] = (),
) -> Path:
    root = Path(evidence_root)
    result = dict(payload)
    result.setdefault("schemaVersion", 1)
    result.setdefault("issue", ISSUE_ID)
    result.setdefault("finishedAt", iso_now())
    target = root / f"{name}.json"
    _write_json(target, result)
    for alias in aliases:
        _write_json(root / f"{alias}.json", result)
    return target


def _audit_is_clean(value: Mapping[str, Any]) -> bool:
    if value.get("ok") is not True:
        return False
    for key in ("missing", "extra", "invalid", "duplicates"):
        if key not in value:
            return False
        try:
            if int(value[key]) != 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _bootstrap_result_is_clean(
    payload: Mapping[str, Any], scopes: Sequence[str]
) -> list[str]:
    failures: list[str] = []
    if payload.get("ready") is not True:
        failures.append("bootstrap result is not ready")
    if payload.get("source") != "xtdata_preclose":
        failures.append("bootstrap source is not xtdata_preclose")
    if payload.get("writer") != "freshquant.market_data.xtdata.qfq":
        failures.append("bootstrap writer is not canonical")
    by_scope = payload.get("by_scope")
    if not isinstance(by_scope, Mapping):
        return ["bootstrap result has no by_scope statistics"]
    for scope in scopes:
        stats = by_scope.get(scope)
        if not isinstance(stats, Mapping):
            failures.append(f"bootstrap result has no {scope} statistics")
            continue
        try:
            failed = int(stats["failed"])
        except (KeyError, TypeError, ValueError):
            failures.append(f"{scope} has no valid failed count")
            failed = -1
        if failed != 0:
            failures.append(f"{scope} has failed downloads")
        audit = stats.get("audit")
        if not isinstance(audit, Mapping):
            failures.append(f"{scope} factor audit is missing")
        elif not _audit_is_clean(audit):
            failures.append(f"{scope} factor audit is not clean")
        if stats.get("published") is not True:
            failures.append(f"{scope} snapshot was not published")
        if stats.get("ready") not in ("ready", True):
            failures.append(f"{scope} ready marker is not ready")
    return failures


def _bootstrap_evidence_failures(payload: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    scopes = payload.get("scope")
    if not isinstance(scopes, Sequence) or isinstance(scopes, (str, bytes)):
        failures.append("bootstrap evidence has no scope list")
        parsed_scopes: list[str] = []
    else:
        parsed_scopes = [str(value).strip().lower() for value in scopes]
        if set(parsed_scopes) != {"stock", "etf"}:
            failures.append("bootstrap evidence must cover stock and etf")
    if payload.get("full") is not True:
        failures.append("bootstrap evidence is not a full snapshot")
    if payload.get("verify") is not True:
        failures.append("bootstrap evidence was not verified")
    for key, label in (("sync", "full"), ("incrementalSync", "incremental")):
        result = payload.get(key)
        if not isinstance(result, Mapping):
            failures.append(f"bootstrap evidence has no {label} writer result")
            continue
        failures.extend(
            f"{label}: {failure}"
            for failure in _bootstrap_result_is_clean(result, parsed_scopes)
        )
    return failures


def run_bootstrap(
    *,
    scope: str,
    full: bool,
    verify: bool,
    repo_root: Path | str | None = None,
    state_path: Path | str | None = None,
    formal_deploy_root: Path | str | None = None,
    evidence_root: Path | str | None = None,
    require_deployed_main: bool = False,
    require_after_latest_deploy: bool = False,
    sync_callable: Any | None = None,
) -> dict[str, Any]:
    scopes = [item.strip().lower() for item in scope.split(",") if item.strip()]
    if not scopes or any(item not in {"stock", "etf"} for item in scopes):
        raise GateError("bootstrap scope must contain only stock and/or etf")
    context = load_deployment_context(
        repo_root,
        state_path=state_path,
        formal_deploy_root=formal_deploy_root,
    )
    if require_deployed_main:
        failures = deployment_identity_failures(context)
        if failures:
            raise GateError("deployed-main check failed: " + "; ".join(failures))

    if sync_callable is None:
        from freshquant.market_data.xtdata.qfq import sync_qfq_factors

        sync_callable = sync_qfq_factors
    started_at = iso_now()
    run_prefix = (
        f"{ISSUE_ID.lower()}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    sync_result = sync_callable(
        scope=",".join(scopes),
        incremental=not full,
        run_id=f"{run_prefix}-bootstrap" if full else f"{run_prefix}-incremental",
    )
    if not isinstance(sync_result, Mapping):
        raise GateError("QFQ writer returned a non-object result")
    failures = _bootstrap_result_is_clean(sync_result, scopes) if verify else []
    incremental_result: Mapping[str, Any] | None = None
    if verify and full and not failures:
        incremental_result = sync_callable(
            scope=",".join(scopes),
            incremental=True,
            run_id=f"{run_prefix}-idempotency",
        )
        if not isinstance(incremental_result, Mapping):
            failures.append("QFQ incremental writer returned a non-object result")
        else:
            failures.extend(_bootstrap_result_is_clean(incremental_result, scopes))
            initial_scopes = sync_result.get("by_scope", {})
            repeated_scopes = incremental_result.get("by_scope", {})
            for item in scopes:
                initial_rows = (initial_scopes.get(item) or {}).get("rows")
                repeated_rows = (repeated_scopes.get(item) or {}).get("rows")
                if initial_rows is not None and repeated_rows != initial_rows:
                    failures.append(
                        f"{item} idempotency row count changed: {initial_rows} -> {repeated_rows}"
                    )
    finished_at = iso_now()
    result: dict[str, Any] = {
        "ok": not failures,
        "command": "bootstrap",
        "issue": ISSUE_ID,
        "scope": scopes,
        "full": bool(full),
        "verify": bool(verify),
        "startedAt": started_at,
        "finishedAt": finished_at,
        "deployedSha": context.deployed_sha,
        "deployedAt": context.deployed_at,
        "deployment": context.as_dict(),
        "sync": dict(sync_result),
        "incrementalSync": (
            dict(incremental_result)
            if isinstance(incremental_result, Mapping)
            else None
        ),
        "failures": failures,
    }
    if require_after_latest_deploy:
        assert_after_latest_deploy(finished_at, context)
    output = persist_evidence(
        evidence_root or DEFAULT_EVIDENCE_ROOT,
        "qfq-bootstrap-real",
        result,
        aliases=("bootstrap",),
    )
    result["evidencePath"] = str(output)
    if failures:
        raise GateError("bootstrap verification failed: " + "; ".join(failures))
    return result


def _check_mongo(scope: Sequence[str]) -> dict[str, Any]:
    try:
        from freshquant.db import DBQuantAxis
    except Exception as exc:  # pragma: no cover - depends on deployment extras
        return {"passed": False, "reason": f"Mongo client import failed: {exc}"}
    failures: list[str] = []
    markers: dict[str, Any] = {}
    try:
        for kind in scope:
            if kind == "index":
                day_count = int(DBQuantAxis["index_day"].count_documents({}))
                min_count = int(DBQuantAxis["index_min"].count_documents({}))
                markers[kind] = {
                    "mode": "BFQ",
                    "index_day_count": day_count,
                    "index_min_count": min_count,
                }
                if day_count <= 0 or min_count <= 0:
                    failures.append("index BFQ day/min collections must be non-empty")
                continue
            collection = f"{kind}_adj"
            marker = DBQuantAxis.qfq_ready.find_one(
                {"collection": collection}, {"_id": 0}
            )
            markers[kind] = marker
            if not marker:
                failures.append(f"missing qfq_ready marker for {collection}")
                continue
            if marker.get("status") != "ready":
                failures.append(f"{collection} marker status is not ready")
            if marker.get("source") != "xtdata_preclose":
                failures.append(f"{collection} marker source is not xtdata_preclose")
            if marker.get("writer") != "freshquant.market_data.xtdata.qfq":
                failures.append(f"{collection} marker writer is not canonical")
            for key in ("missing", "invalid", "duplicates"):
                if int(marker.get(key, 0) or 0) != 0:
                    failures.append(f"{collection} marker {key} is non-zero")
            if DBQuantAxis[collection].count_documents({}) <= 0:
                failures.append(f"{collection} is empty")
    except Exception as exc:  # pragma: no cover - live Mongo dependency
        failures.append(f"Mongo query failed: {exc}")
    return {"passed": not failures, "markers": markers, "failures": failures}


def _validate_api_payload(url: str, payload: Any) -> list[str]:
    """Validate the stable get_data_v2 response shape and QFQ sample dates."""

    if not isinstance(payload, Mapping):
        return [f"API response is not an object: {url}"]
    if "date" not in payload or "close" not in payload:
        # The health endpoint intentionally has a different shape.
        if "/runtime/" in url:
            return []
        return [f"API response lacks date/close: {url}"]
    dates = payload.get("date")
    closes = payload.get("close")
    if not isinstance(dates, Sequence) or isinstance(dates, (str, bytes)):
        return [f"API date field is not a sequence: {url}"]
    if not isinstance(closes, Sequence) or isinstance(closes, (str, bytes)):
        return [f"API close field is not a sequence: {url}"]
    if not dates or not closes:
        return [f"API response has no bars: {url}"]
    failures: list[str] = []
    target_date = None
    if "endDate=" in url:
        target_date = url.split("endDate=", 1)[1].split("&", 1)[0]
    if target_date and not any(str(item).startswith(target_date) for item in dates):
        failures.append(
            f"API response does not include requested endDate {target_date}: {url}"
        )
    # The issue acceptance samples are intentionally tolerance based.  The
    # exact source precision varies by XTData build and Mongo serialization.
    expected_close: float | None = None
    if "symbol=sh600381" in url:
        expected_close = 5.12
    elif "symbol=sz159995" in url:
        expected_close = 1.504
    if expected_close is not None:
        try:
            target_index = next(
                index
                for index, item in enumerate(dates)
                if not target_date or str(item).startswith(target_date)
            )
            actual = float(closes[target_index])
            if abs(actual - expected_close) > max(0.08, expected_close * 0.05):
                failures.append(
                    f"API sample close outside tolerance for {url}: actual={actual} expected={expected_close}"
                )
        except (StopIteration, IndexError, TypeError, ValueError):
            failures.append(f"API sample close is not numeric: {url}")
    return failures


def _check_api(urls: Sequence[str] = DEFAULT_API_URLS) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    failures: list[str] = []
    for url in urls:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read()
                status = int(getattr(response, "status", 200))
            parsed: Any = None
            parse_error = None
            if body:
                try:
                    parsed = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    parse_error = str(exc)
            payload_failures = [] if parse_error else _validate_api_payload(url, parsed)
            passed = (
                200 <= status < 300
                and bool(body)
                and not parse_error
                and not payload_failures
            )
            checks.append(
                {
                    "url": url,
                    "status": status,
                    "bytes": len(body),
                    "passed": passed,
                    "payload_failures": payload_failures,
                }
            )
            if not passed:
                failures.append(
                    f"API check failed: {url} status={status}"
                    + (f" parse={parse_error}" if parse_error else "")
                    + (f" details={payload_failures}" if payload_failures else "")
                )
        except (OSError, urllib.error.URLError) as exc:
            checks.append({"url": url, "passed": False, "error": str(exc)})
            failures.append(f"API check failed: {url}: {exc}")
    return {"passed": not failures, "checks": checks, "failures": failures}


def _check_evidence_file(
    name: str,
    *,
    evidence_root: Path,
    context: DeploymentContext,
    require_after: bool,
    aliases: Iterable[str] = (),
) -> dict[str, Any]:
    path, payload = load_latest_evidence(evidence_root, (name, *aliases))
    if path is None or payload is None:
        return {"passed": False, "failures": [f"missing evidence: {name}"]}
    failures = _check_identity(payload, context, require_after=require_after)
    if payload.get("ok") is not True:
        failures.append("evidence reports failed")
    if name == "qfq-bootstrap-real":
        failures.extend(_bootstrap_evidence_failures(payload))
    return {
        "passed": not failures,
        "path": str(path),
        "evidence": payload,
        "failures": failures,
    }


def _check_runtime_artifact(
    formal_deploy_root: Path,
    *,
    context: DeploymentContext,
    require_after: bool,
) -> dict[str, Any]:
    run_dir = Path(context.latest_run_dir) if context.latest_run_dir else None
    candidates = (
        sorted(run_dir.glob("runtime-verify*.json"), key=lambda p: p.stat().st_mtime)
        if run_dir and run_dir.exists()
        else []
    )
    if not candidates:
        return {
            "passed": False,
            "failures": ["no formal deploy runtime verify artifact"],
        }
    path = candidates[-1]
    payload = _read_json(path)
    if payload is None:
        return {
            "passed": False,
            "failures": [f"invalid runtime verify artifact: {path}"],
        }
    failures = _check_identity(payload, context, require_after=require_after)
    if payload.get("passed") is not True:
        failures.append("runtime verify artifact is not passed")
    if payload.get("failures"):
        failures.append("runtime verify artifact contains failures")
    return {"passed": not failures, "path": str(path), "failures": failures}


def _market_jobs_evidence_failures(payload: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    checks = payload.get("checks")
    if not isinstance(checks, Sequence) or isinstance(checks, (str, bytes)):
        failures.append("market-jobs evidence has no checks list")
        requested: set[str] = set()
    else:
        requested = {str(value).strip().lower() for value in checks}
    if not {"dagster", "coverage"}.issubset(requested):
        failures.append("market-jobs evidence must include dagster and coverage")

    results = payload.get("results")
    if not isinstance(results, Mapping):
        return [*failures, "market-jobs evidence has no results"]
    for name in ("dagster", "coverage"):
        result = results.get(name)
        if not isinstance(result, Mapping) or result.get("passed") is not True:
            failures.append(f"market-jobs {name} result is not passed")

    dagster = results.get("dagster")
    details = dagster.get("details") if isinstance(dagster, Mapping) else None
    jobs = details.get("jobs") if isinstance(details, Mapping) else None
    if not isinstance(jobs, Mapping):
        failures.append("market-jobs evidence has no Dagster job results")
    else:
        for job_name in MARKET_JOB_NAMES:
            records = jobs.get(job_name)
            if (
                not isinstance(records, Sequence)
                or isinstance(records, (str, bytes))
                or not records
            ):
                failures.append(f"market-jobs evidence has no {job_name} result")
    return failures


def _check_dagster_runtime(
    repo_root: Path,
    *,
    context: DeploymentContext,
    evidence_root: Path,
    require_after: bool,
    allow_persisted_evidence: bool,
) -> dict[str, Any]:
    """Validate definitions, shared writer concurrency and latest successful runs.

    A previously persisted market-jobs result is accepted only when it is
    bound to this deployment.  Otherwise the check performs the live
    definitions/run inspection and lets ``run_verify`` persist its result.
    """

    path, payload = load_latest_evidence(evidence_root, ("market-jobs-real",))
    if allow_persisted_evidence and path is not None and payload is not None:
        identity_failures = _check_identity(
            payload, context, require_after=require_after
        )
        evidence_failures = _market_jobs_evidence_failures(payload)
        if payload.get("ok") is True and not identity_failures and not evidence_failures:
            return {
                "passed": True,
                "path": str(path),
                "evidence": payload,
                "failures": [],
            }

    failures: list[str] = []
    details: dict[str, Any] = {"jobs": {}, "definitions": {}}
    schedule_path = (
        repo_root
        / "morningglory"
        / "fqdagster"
        / "src"
        / "fqdagster"
        / "defs"
        / "schedules"
        / "market_data.py"
    )
    schedule_text = ""
    try:
        schedule_text = schedule_path.read_text(encoding="utf-8")
    except OSError as exc:
        failures.append(f"market schedule source missing: {exc}")
    if schedule_text:
        if "AssetSelection.assets(" not in schedule_text:
            failures.append("market jobs do not use explicit AssetSelection.assets")
        if "cjsd" in schedule_text.lower():
            failures.append("market schedule source references cjsd")
        for job_name in MARKET_JOB_NAMES:
            if f'name="{job_name}"' not in schedule_text:
                failures.append(f"missing market job definition: {job_name}")
        try:
            import yaml  # type: ignore[import-untyped]

            config_path = (
                repo_root / "morningglory" / "fqdagsterconfig" / "dagster.yaml"
            )
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            limits = (
                config.get("run_coordinator", {})
                .get("config", {})
                .get("tag_concurrency_limits", [])
            )
            writer_limit = next(
                (
                    item
                    for item in limits
                    if item.get("key") == "freshquant/mongo_writer"
                    and item.get("value") == "quantaxis_market_data"
                ),
                None,
            )
            details["definitions"]["mongo_writer_limit"] = writer_limit
            if not writer_limit or int(writer_limit.get("limit", 0)) != 1:
                failures.append(
                    "quantaxis_market_data Mongo writer concurrency limit is not 1"
                )
        except Exception as exc:  # pragma: no cover - optional YAML/runtime dependency
            failures.append(f"Dagster config inspection failed: {exc}")

    try:
        source_root = repo_root / "morningglory" / "fqdagster" / "src"
        if str(source_root) not in sys.path:
            sys.path.insert(0, str(source_root))
        from dagster import DagsterInstance, DagsterRunStatus, RunsFilter

        instance = DagsterInstance.get()
        for job_name in MARKET_JOB_NAMES:
            records = instance.get_run_records(
                filters=RunsFilter(
                    job_name=job_name, statuses=[DagsterRunStatus.SUCCESS]
                ),
                limit=20,
            )
            accepted: list[dict[str, Any]] = []
            deployed_at = parse_time(context.deployed_at)
            for record in records:
                run = record.dagster_run
                end_time = getattr(record, "end_time", None)
                ended = (
                    datetime.fromtimestamp(float(end_time), tz=timezone.utc)
                    if end_time
                    else None
                )
                if ended is None:
                    continue
                if deployed_at and ended <= deployed_at:
                    continue
                accepted.append(
                    {
                        "run_id": getattr(run, "run_id", None),
                        "status": str(getattr(run, "status", "")),
                        "end_time": (
                            ended.isoformat().replace("+00:00", "Z") if ended else None
                        ),
                        "tags": dict(getattr(run, "tags", {}) or {}),
                    }
                )
            details["jobs"][job_name] = accepted[:3]
            if not accepted:
                failures.append(f"no successful {job_name} run after deployedAt")
    except Exception as exc:  # pragma: no cover - depends on live Dagster instance
        failures.append(f"Dagster run inspection failed: {exc}")

    details["asset_whitelist"] = {
        "source": str(schedule_path),
        "contains_cjsd": "cjsd" in schedule_text.lower(),
    }
    return {"passed": not failures, "details": details, "failures": failures}


def _check_coverage_runtime(repo_root: Path, scope: Sequence[str]) -> dict[str, Any]:
    """Run the repository's day/minute coverage assertions against live Mongo."""

    source_root = repo_root / "morningglory" / "fqdagster" / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    failures: list[str] = []
    details: dict[str, Any] = {}
    try:
        from fqdagster.defs.assets.market_data_freshness import (
            assert_etf_day_fresh,
            assert_etf_min_fresh,
            assert_stock_day_fresh,
            assert_stock_market_data_consistent,
            assert_stock_min_fresh,
        )

        if "stock" in scope:
            details["stock_day"] = assert_stock_day_fresh()
            details["stock_min"] = assert_stock_min_fresh()
            details["stock_integrity"] = assert_stock_market_data_consistent()
        if "etf" in scope:
            details["etf_day"] = assert_etf_day_fresh()
            details["etf_min"] = assert_etf_min_fresh()
        # Index is deliberately BFQ; a non-empty canonical day/min collection
        # is enough here because no factor collection is consulted.
        if "index" in scope:
            from freshquant.db import DBQuantAxis

            index_codes = {
                str(code).zfill(6)
                for code in DBQuantAxis["index_list"].distinct("code")
                if str(code).strip()
            }
            etf_codes = {
                str(code).zfill(6)
                for code in DBQuantAxis["etf_list"].distinct("code")
                if str(code).strip()
            }
            real_index_codes = sorted(index_codes - etf_codes)
            details["index_codes"] = len(real_index_codes)
            details["index_day_count"] = int(
                DBQuantAxis["index_day"].count_documents(
                    {"code": {"$in": real_index_codes}}
                )
            )
            details["index_min_count"] = int(
                DBQuantAxis["index_min"].count_documents(
                    {"code": {"$in": real_index_codes}}
                )
            )
            if not real_index_codes:
                failures.append("real Index universe is empty")
            if not details["index_day_count"] or not details["index_min_count"]:
                failures.append("index BFQ day/min collection is empty")
    except Exception as exc:  # pragma: no cover - depends on live Mongo/calendar
        failures.append(f"day/min coverage audit failed: {exc}")
    return {"passed": not failures, "details": details, "failures": failures}


def _check_cleanup(context: DeploymentContext) -> dict[str, Any]:
    state = _read_json(Path(context.state_path)) or {}
    failures: list[str] = []
    state_sha = _normalise_sha(state.get("last_success_sha"))
    if not state_sha:
        failures.append("production state has no successful deploy")
    elif state_sha != context.deployed_sha:
        failures.append("production state SHA does not match deployed SHA")
    if context.latest_run_dir:
        result = _read_json(Path(context.latest_run_dir) / "result.json")
        if not result or result.get("ok") is not True:
            failures.append("latest formal deploy result is not successful")

    repo_root = Path(context.repo_root)
    details: dict[str, Any] = {}
    try:
        branch = run_git(repo_root, "branch", "--show-current")
        details["branch"] = branch
        if branch != "main":
            failures.append(f"cleanup requires main branch, found {branch or 'detached'}")

        status_lines = [
            line
            for line in run_git(
                repo_root,
                "status",
                "--porcelain=v1",
                "--untracked-files=no",
            ).splitlines()
            if line.strip()
        ]
        allowed_runtime_files = {
            ".governance/board.html",
            ".governance/events.jsonl",
        }
        dirty: list[str] = []
        for line in status_lines:
            path = line[3:].replace("\\", "/") if len(line) > 3 else line
            if " -> " in path:
                path = path.rsplit(" -> ", 1)[-1]
            if path not in allowed_runtime_files:
                dirty.append(line)
        details["tracked_changes"] = dirty
        if dirty:
            failures.append("tracked worktree is not clean: " + ", ".join(dirty))

        refs = run_git(
            repo_root,
            "for-each-ref",
            "--format=%(refname:short)",
            "refs/heads",
            "refs/remotes/origin",
        ).splitlines()
        task_refs = sorted(
            ref for ref in refs if "issue-467" in ref.lower()
        )
        details["task_branch_refs"] = task_refs
        if task_refs:
            failures.append("Issue #467 branch refs remain: " + ", ".join(task_refs))
    except GateError as exc:
        failures.append(f"cleanup git inspection failed: {exc}")
    return {"passed": not failures, "details": details, "failures": failures}


def run_verify(
    *,
    checks: str,
    repo_root: Path | str | None = None,
    state_path: Path | str | None = None,
    formal_deploy_root: Path | str | None = None,
    evidence_root: Path | str | None = None,
    scope: str = "stock,etf,index",
    require_deployed_main: bool = False,
    require_after_latest_deploy: bool = False,
) -> dict[str, Any]:
    requested = [item.strip().lower() for item in checks.split(",") if item.strip()]
    if not requested:
        raise GateError("verify requires at least one check")
    unknown = sorted(set(requested) - KNOWN_CHECKS)
    if unknown:
        raise GateError("unknown verify checks: " + ", ".join(unknown))
    context = load_deployment_context(
        repo_root,
        state_path=state_path,
        formal_deploy_root=formal_deploy_root,
    )
    identity_failures = (
        deployment_identity_failures(context) if require_deployed_main else []
    )
    if identity_failures:
        raise GateError("deployed-main check failed: " + "; ".join(identity_failures))
    scopes = [item.strip().lower() for item in scope.split(",") if item.strip()]
    invalid_scopes = sorted(set(scopes) - {"stock", "etf", "index"})
    if invalid_scopes:
        raise GateError("verify scope must contain only stock, etf and/or index")
    evidence_dir = Path(evidence_root or DEFAULT_EVIDENCE_ROOT)
    requested_set = set(requested)
    formal_checks = {
        "deployment",
        "qfq",
        "mongo",
        "api",
        "dagster",
        "coverage",
        "health",
        "runtime",
        "cleanup",
    }
    is_formal_verify = formal_checks.issubset(requested_set)
    check_results: dict[str, Any] = {}
    for check in requested:
        if check == "deployment":
            check_results[check] = {
                "passed": not identity_failures,
                "deployment": context.as_dict(),
                "failures": identity_failures,
            }
        elif check == "mongo":
            check_results[check] = _check_mongo(scopes)
        elif check == "api":
            urls = (
                tuple(
                    item.strip()
                    for item in os.environ.get("FQ_QFQ_API_URLS", "").split(",")
                    if item.strip()
                )
                or DEFAULT_API_URLS
            )
            check_results[check] = _check_api(urls)
        elif check == "qfq":
            check_results[check] = _check_evidence_file(
                "qfq-bootstrap-real",
                evidence_root=evidence_dir,
                context=context,
                require_after=require_after_latest_deploy,
                aliases=("bootstrap",),
            )
        elif check == "coverage":
            check_results[check] = _check_coverage_runtime(
                Path(context.repo_root), scopes
            )
        elif check == "dagster":
            check_results[check] = _check_dagster_runtime(
                Path(context.repo_root),
                context=context,
                evidence_root=evidence_dir,
                require_after=require_after_latest_deploy,
                allow_persisted_evidence=is_formal_verify,
            )
        elif check in {"health", "runtime"}:
            check_results[check] = _check_runtime_artifact(
                Path(context.formal_deploy_root),
                context=context,
                require_after=require_after_latest_deploy,
            )
        elif check == "cleanup":
            check_results[check] = _check_cleanup(context)

    failures: list[str] = []
    for check, result in check_results.items():
        if result.get("passed") is not True:
            failures.extend(f"{check}: {value}" for value in result.get("failures", []))
            if not result.get("failures"):
                failures.append(f"{check}: check failed")
    finished_at = iso_now()
    result = {
        "ok": not failures,
        "command": "verify",
        "issue": ISSUE_ID,
        "checks": requested,
        "scope": scopes,
        "finishedAt": finished_at,
        "deployedSha": context.deployed_sha,
        "deployedAt": context.deployed_at,
        "deployment": context.as_dict(),
        "results": check_results,
        "failures": failures,
    }
    if require_after_latest_deploy:
        assert_after_latest_deploy(finished_at, context)
    if is_formal_verify:
        name, aliases = "formal-deploy-main", ("verify",)
    elif requested_set == {"dagster", "coverage"}:
        name, aliases = "market-jobs-real", ("dagster", "coverage")
    elif requested_set == {"mongo", "api"}:
        name, aliases = "qfq-runtime-audit", ("runtime-audit",)
    else:
        suffix = "-".join(sorted(requested_set))
        name, aliases = f"verify-{suffix}", ()
    output = persist_evidence(evidence_dir, name, result, aliases=aliases)
    result["evidencePath"] = str(output)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Issue #467 XTData QFQ governance checks"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--repo-root", default=None)
        command_parser.add_argument("--state-path", default=None)
        command_parser.add_argument("--formal-deploy-root", default=None)
        command_parser.add_argument("--evidence-root", default=None)
        command_parser.add_argument(
            "--output", default=None, help="Write the command result to this JSON path"
        )
        command_parser.add_argument("--require-deployed-main", action="store_true")
        command_parser.add_argument(
            "--require-after-latest-deploy", action="store_true"
        )

    bootstrap = subparsers.add_parser("bootstrap", help="Publish XTData QFQ factors")
    add_common(bootstrap)
    bootstrap.add_argument("--scope", default="stock,etf")
    bootstrap.add_argument(
        "--full", action="store_true", help="Run a full snapshot instead of incremental"
    )
    bootstrap.add_argument(
        "--verify", action="store_true", help="Audit the published snapshot"
    )

    verify = subparsers.add_parser("verify", help="Verify QFQ and runtime evidence")
    add_common(verify)
    verify.add_argument("--check", required=True, help="Comma-separated checks")
    verify.add_argument("--scope", default="stock,etf,index")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        common = {
            "repo_root": args.repo_root,
            "state_path": args.state_path,
            "formal_deploy_root": args.formal_deploy_root,
            "evidence_root": args.evidence_root,
            "require_deployed_main": bool(args.require_deployed_main),
            "require_after_latest_deploy": bool(args.require_after_latest_deploy),
        }
        if args.command == "bootstrap":
            result = run_bootstrap(
                scope=args.scope,
                full=bool(args.full),
                verify=bool(args.verify),
                **common,
            )
        else:
            result = run_verify(checks=args.check, scope=args.scope, **common)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        if args.output:
            _write_json(Path(args.output), result)
        return 0 if result.get("ok") is True else 1
    except Exception as exc:  # noqa: BLE001
        failure = {
            "ok": False,
            "command": getattr(args, "command", None),
            "issue": ISSUE_ID,
            "finishedAt": iso_now(),
            "failures": [str(exc)],
        }
        if getattr(args, "output", None):
            _write_json(Path(args.output), failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
