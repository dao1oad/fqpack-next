"""Serve the local CLX18 target-hit report on a fixed localhost address."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import mimetypes
from datetime import date, datetime
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "freshquant" / "backtest" / "clx_target_hit" / "web"
DATA_ROOT = ROOT / "outputs" / "clx18_target_hit"
EXPORT_SUFFIXES = {".csv", ".json", ".parquet", ".tsv", ".xls", ".xlsx", ".zip"}
GRID_PATH = DATA_ROOT / "final_grid.parquet"
GRID_DIMENSIONS = (
    "model_code",
    "stage",
    "trigger_view",
    "trigger_key",
    "filter_key",
)
GRID_OPTIONAL_DIMENSIONS = ("horizon", "target_bps")
GRID_QUERY_KEYS = frozenset((*GRID_DIMENSIONS, *GRID_OPTIONAL_DIMENSIONS))
MAX_GRID_ROWS = 522


class GridQueryError(ValueError):
    """A client grid query does not satisfy the bounded report contract."""


class GridDataError(RuntimeError):
    """The local aggregate backend is missing or malformed."""


def _signature(path: Path) -> tuple[str, int, int]:
    stat = path.stat()
    return str(path.resolve()), stat.st_size, stat.st_mtime_ns


@lru_cache(maxsize=8)
def _read_json_cached(
    path: str,
    _size: int,
    _mtime_ns: int,
) -> dict[str, object]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("JSON root must be an object")
    return payload


def _current_report() -> tuple[dict[str, object], tuple[str, int, int]]:
    signature = _signature(DATA_ROOT / "report.json")
    return _read_json_cached(*signature), signature


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _json_bytes(payload: object) -> bytes:
    return json.dumps(
        _json_safe(payload),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _facet_values(report: dict[str, object], key: str) -> set[str]:
    facets = report.get("facets")
    if isinstance(facets, dict) and isinstance(facets.get(key), list):
        return {str(value) for value in facets[key]}
    contract = report.get("contract")
    if isinstance(contract, dict):
        if key == "horizon" and isinstance(contract.get("horizons"), list):
            return {str(value) for value in contract["horizons"]}
        if key == "target_bps" and isinstance(contract.get("targets_pct"), list):
            return {str(int(value) * 100) for value in contract["targets_pct"]}
    grid = report.get("grid")
    if isinstance(grid, list):
        return {
            str(row[key])
            for row in grid
            if isinstance(row, dict) and row.get(key) is not None
        }
    return set()


def _parse_grid_query(
    query: str,
    report: dict[str, object],
) -> tuple[tuple[str, object], ...]:
    try:
        pairs = parse_qsl(
            query,
            keep_blank_values=True,
            strict_parsing=False,
            max_num_fields=16,
        )
    except ValueError as exc:
        raise GridQueryError("query contains too many fields") from exc
    names = [name for name, _ in pairs]
    unknown = sorted(set(names).difference(GRID_QUERY_KEYS))
    if unknown:
        raise GridQueryError(f"unknown query parameters: {unknown}")
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise GridQueryError(f"duplicate query parameters: {duplicates}")
    supplied = dict(pairs)
    missing = sorted(set(GRID_DIMENSIONS).difference(supplied))
    if missing:
        raise GridQueryError(f"missing required query parameters: {missing}")
    filters: list[tuple[str, object]] = []
    for key in (*GRID_DIMENSIONS, *GRID_OPTIONAL_DIMENSIONS):
        if key not in supplied:
            continue
        raw = supplied[key]
        if not raw or len(raw) > 128:
            raise GridQueryError(f"{key} is empty or too long")
        if key in GRID_OPTIONAL_DIMENSIONS:
            try:
                value: object = int(raw)
            except ValueError as exc:
                raise GridQueryError(f"{key} must be an integer") from exc
            if str(value) != raw:
                raise GridQueryError(f"{key} must use canonical integer syntax")
        else:
            value = raw
        allowed = _facet_values(report, key)
        if not allowed or str(value) not in allowed:
            raise GridQueryError(f"{key} is outside the report facets")
        filters.append((key, value))
    return tuple(filters)


def _filter_fixture_grid(
    report: dict[str, object],
    filters: tuple[tuple[str, object], ...],
) -> list[dict[str, object]]:
    grid = report.get("grid")
    if not isinstance(grid, list):
        raise GridDataError("report grid is not a list")
    selected = [
        row
        for row in grid
        if isinstance(row, dict)
        and all(str(row.get(key)) == str(value) for key, value in filters)
    ]
    return sorted(
        selected,
        key=lambda row: (int(row.get("horizon", 0)), int(row.get("target_bps", 0))),
    )


def _filter_parquet_grid(
    signature: tuple[str, int, int],
    filters: tuple[tuple[str, object], ...],
) -> list[dict[str, object]]:
    try:
        import pyarrow.dataset as arrow_dataset

        dataset = arrow_dataset.dataset(signature[0], format="parquet")
        names = set(dataset.schema.names)
        missing = sorted(GRID_QUERY_KEYS.difference(names))
        if missing:
            raise GridDataError(f"final_grid.parquet is missing columns: {missing}")
        predicate = None
        for key, value in filters:
            term = arrow_dataset.field(key) == value
            predicate = term if predicate is None else predicate & term
        row_count = dataset.count_rows(filter=predicate)
        if row_count > MAX_GRID_ROWS:
            raise GridQueryError(
                f"grid query exceeds the {MAX_GRID_ROWS}-row response limit"
            )
        table = dataset.to_table(filter=predicate)
        if table.num_rows != row_count:
            raise GridDataError("grid row count changed during the query")
        if table.num_rows:
            table = table.sort_by(
                [("horizon", "ascending"), ("target_bps", "ascending")]
            )
        return table.to_pylist()
    except GridQueryError:
        raise
    except GridDataError:
        raise
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        raise GridDataError(
            f"parquet grid backend error: {type(exc).__name__}"
        ) from exc


@lru_cache(maxsize=128)
def _grid_payload_cached(
    report_signature: tuple[str, int, int],
    grid_signature: tuple[str, int, int] | None,
    filters: tuple[tuple[str, object], ...],
) -> bytes:
    report = _read_json_cached(*report_signature)
    if grid_signature is None:
        rows = _filter_fixture_grid(report, filters)
        source = "report.grid"
    else:
        rows = _filter_parquet_grid(grid_signature, filters)
        source = "final_grid.parquet"
    if len(rows) > MAX_GRID_ROWS:
        raise GridQueryError(
            f"grid query exceeds the {MAX_GRID_ROWS}-row response limit"
        )
    return _json_bytes(
        {
            "source": source,
            "selection": dict(filters),
            "row_count": len(rows),
            "grid_total_rows": report.get(
                "grid_total_rows", len(report.get("grid", []))
            ),
            "rows": rows,
        }
    )


@lru_cache(maxsize=8)
def _trigger_keys_by_view_cached(
    report_signature: tuple[str, int, int],
    grid_signature: tuple[str, int, int] | None,
) -> dict[str, list[str]]:
    report = _read_json_cached(*report_signature)
    recommended = report.get("recommended_selection")
    recommended = recommended if isinstance(recommended, dict) else {}
    pairs: set[tuple[str, str]] = set()
    recommended_counts: dict[tuple[str, str], int] = {}

    def add_pair(
        view: object,
        key: object,
        model_code: object,
        stage: object,
        filter_key: object,
    ) -> None:
        if view is None or key is None:
            return
        pair = str(view), str(key)
        pairs.add(pair)
        if (
            recommended
            and str(model_code) == str(recommended.get("model_code"))
            and str(stage) == str(recommended.get("stage"))
            and str(filter_key) == str(recommended.get("filter_key"))
        ):
            recommended_counts[pair] = recommended_counts.get(pair, 0) + 1

    if grid_signature is None:
        grid = report.get("grid")
        if not isinstance(grid, list):
            raise GridDataError("report grid is not a list")
        for row in grid:
            if isinstance(row, dict):
                add_pair(
                    row.get("trigger_view"),
                    row.get("trigger_key"),
                    row.get("model_code"),
                    row.get("stage"),
                    row.get("filter_key"),
                )
    else:
        try:
            import pyarrow.dataset as arrow_dataset

            dataset = arrow_dataset.dataset(grid_signature[0], format="parquet")
            columns = [
                "trigger_view",
                "trigger_key",
                "model_code",
                "stage",
                "filter_key",
            ]
            required = set(columns)
            missing = sorted(required.difference(dataset.schema.names))
            if missing:
                raise GridDataError(f"final_grid.parquet is missing columns: {missing}")
            for batch in dataset.to_batches(
                columns=columns,
                batch_size=262_144,
            ):
                values = [batch.column(index).to_pylist() for index in range(5)]
                for row in zip(*values, strict=True):
                    add_pair(*row)
        except GridDataError:
            raise
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            raise GridDataError(
                f"parquet facet backend error: {type(exc).__name__}"
            ) from exc

    def sort_key(value: str) -> tuple[int, int, str]:
        try:
            return 0, int(value), ""
        except ValueError:
            special = {"3_PLUS": 3, "ALL": 4}
            return (1, special[value], "") if value in special else (2, 0, value)

    result: dict[str, list[str]] = {}
    for view, key in pairs:
        result.setdefault(view, []).append(key)
    return {
        view: sorted(
            set(keys),
            key=lambda key: (
                (
                    0
                    if (
                        view == str(recommended.get("trigger_view"))
                        and key == str(recommended.get("trigger_key"))
                    )
                    else (
                        1
                        if recommended_counts.get((view, key), 0) >= MAX_GRID_ROWS
                        else 2 if recommended_counts.get((view, key), 0) > 0 else 3
                    )
                ),
                sort_key(key),
            ),
        )
        for view, keys in sorted(result.items())
    }


@lru_cache(maxsize=8)
def _facets_payload_cached(
    report_signature: tuple[str, int, int],
    grid_signature: tuple[str, int, int] | None,
) -> bytes:
    report = _read_json_cached(*report_signature)
    facets = {
        key: sorted(
            _facet_values(report, key),
            key=lambda value: (len(value), value),
        )
        for key in GRID_DIMENSIONS
    }
    return _json_bytes(
        {
            "facets": facets,
            "trigger_keys_by_view": _trigger_keys_by_view_cached(
                report_signature,
                grid_signature,
            ),
            "recommended_selection": report.get("recommended_selection", {}),
            "horizons": sorted(
                (int(value) for value in _facet_values(report, "horizon"))
            ),
            "targets_bps": sorted(
                (int(value) for value in _facet_values(report, "target_bps"))
            ),
            "grid_total_rows": report.get(
                "grid_total_rows", len(report.get("grid", []))
            ),
            "grid_export": report.get("grid_export"),
        }
    )


@lru_cache(maxsize=64)
def _sha256_cached(path: str, _size: int, _mtime_ns: int) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Handler(BaseHTTPRequestHandler):
    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        attachment: str | None = None,
    ) -> None:
        self.send_response(status)
        if content_type.startswith(("application/json", "text/")):
            content_type = f"{content_type}; charset=utf-8"
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'",
        )
        if attachment is not None:
            self.send_header(
                "Content-Disposition",
                f"attachment; filename*=UTF-8''{quote(attachment)}",
            )
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in {"/health", "/healthz"}:
            payload, healthy = self._health()
            self._send(
                HTTPStatus.OK if healthy else HTTPStatus.SERVICE_UNAVAILABLE,
                payload,
                "application/json",
            )
            return
        if parsed.path == "/api/manifest":
            self._send(HTTPStatus.OK, self._manifest(), "application/json")
            return
        if parsed.path == "/api/facets":
            self._facets()
            return
        if parsed.path == "/api/grid":
            self._grid(parsed.query)
            return
        if parsed.path == "/api/report":
            self._file(DATA_ROOT / "report.json", "application/json")
            return
        if parsed.path.startswith("/exports/"):
            name = unquote(parsed.path.removeprefix("/exports/"))
            if (
                Path(name).name != name
                or Path(name).suffix.lower() not in EXPORT_SUFFIXES
            ):
                self._send(HTTPStatus.BAD_REQUEST, b"bad path", "text/plain")
                return
            self._file(DATA_ROOT / name, attachment=name)
            return
        relative = "index.html" if parsed.path in {"", "/"} else parsed.path.lstrip("/")
        self._file(WEB_ROOT / relative)

    def _facets(self) -> None:
        try:
            report, report_signature = _current_report()
            grid_export = report.get("grid_export")
            if grid_export and str(grid_export) != GRID_PATH.name:
                raise GridDataError("report grid_export is not final_grid.parquet")
            grid_signature = _signature(GRID_PATH) if grid_export else None
            payload = _facets_payload_cached(report_signature, grid_signature)
        except (
            GridDataError,
            OSError,
            TypeError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            self._send(
                HTTPStatus.SERVICE_UNAVAILABLE,
                _json_bytes(
                    {
                        "status": "facet_backend_error",
                        "error": type(exc).__name__,
                    }
                ),
                "application/json",
            )
            return
        self._send(HTTPStatus.OK, payload, "application/json")

    def _grid(self, query: str) -> None:
        try:
            report, report_signature = _current_report()
            filters = _parse_grid_query(query, report)
            grid_export = report.get("grid_export")
            if grid_export and str(grid_export) != GRID_PATH.name:
                raise GridDataError("report grid_export is not final_grid.parquet")
            grid_signature = _signature(GRID_PATH) if grid_export else None
            payload = _grid_payload_cached(
                report_signature,
                grid_signature,
                filters,
            )
        except GridQueryError as exc:
            self._send(
                HTTPStatus.BAD_REQUEST,
                _json_bytes({"status": "bad_request", "error": str(exc)}),
                "application/json",
            )
            return
        except (
            GridDataError,
            OSError,
            TypeError,
            UnicodeError,
            json.JSONDecodeError,
        ) as exc:
            self._send(
                HTTPStatus.SERVICE_UNAVAILABLE,
                _json_bytes(
                    {
                        "status": "grid_backend_error",
                        "error": type(exc).__name__,
                    }
                ),
                "application/json",
            )
            return
        self._send(HTTPStatus.OK, payload, "application/json")

    def _health(self) -> tuple[bytes, bool]:
        details: dict[str, object] = {
            "status": "degraded",
            "report": False,
            "checks_passed": False,
        }
        try:
            report, _ = _current_report()
            required = {
                "contract",
                "checks",
                "data_status",
                "generated_at",
                "grid",
                "provenance",
            }
            missing = sorted(required.difference(report))
            provenance = report.get("provenance", {})
            if not isinstance(provenance, dict):
                provenance = {}
            provenance_hash = provenance.get("grid_sha256") or provenance.get("sha256")
            if not provenance_hash:
                missing.append("provenance.sha256")
            grid_export = report.get("grid_export")
            grid_backend_exists = not grid_export or (
                str(grid_export) == GRID_PATH.name and GRID_PATH.is_file()
            )
            if not grid_backend_exists:
                missing.append("grid_export")
            details.update(
                {
                    "report": not missing,
                    "checks_passed": report.get("checks", {}).get("passed") is True,
                    "data_status": report.get("data_status"),
                    "generated_at": report.get("generated_at"),
                    "provenance_sha256": provenance_hash,
                    "grid_rows": len(report.get("grid", [])),
                    "grid_total_rows": report.get(
                        "grid_total_rows", len(report.get("grid", []))
                    ),
                    "grid_backend": (
                        str(grid_export) if grid_export else "report.grid"
                    ),
                    "grid_backend_exists": grid_backend_exists,
                    "grid_response_max_rows": MAX_GRID_ROWS,
                    "missing_keys": missing,
                }
            )
            healthy = (
                not missing
                and isinstance(report.get("grid"), list)
                and details["checks_passed"] is True
            )
        except (
            AttributeError,
            OSError,
            TypeError,
            UnicodeError,
            json.JSONDecodeError,
        ) as exc:
            details["error"] = type(exc).__name__
            healthy = False
        details["status"] = "ok" if healthy else "degraded"
        return (
            json.dumps(details, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            ),
            healthy,
        )

    def _manifest(self) -> bytes:
        exports = []
        declared_hashes: dict[str, dict[str, object]] = {}
        final_manifest = DATA_ROOT / "final_manifest.json"
        try:
            manifest = _read_json_cached(*_signature(final_manifest))
            outputs = manifest.get("outputs", [])
            if isinstance(outputs, list):
                declared_hashes = {
                    Path(str(item["path"])).name: item
                    for item in outputs
                    if isinstance(item, dict) and item.get("path")
                }
        except (
            AttributeError,
            OSError,
            TypeError,
            UnicodeError,
            json.JSONDecodeError,
        ):
            declared_hashes = {}
        try:
            files = sorted(
                path
                for path in DATA_ROOT.iterdir()
                if path.is_file()
                and not path.name.startswith(".")
                and path.suffix.lower() in EXPORT_SUFFIXES
            )
        except OSError:
            files = []
        for path in files:
            declared = declared_hashes.get(path.name, {})
            declared_size = declared.get("size")
            declared_sha = declared.get("sha256")
            signature = _signature(path)
            exports.append(
                {
                    "name": path.name,
                    "size": signature[1],
                    "sha256": (
                        declared_sha
                        if declared_sha and declared_size == signature[1]
                        else _sha256_cached(*signature)
                    ),
                    "url": f"/exports/{quote(path.name)}",
                }
            )
        payload = {
            "local_only": True,
            "report_url": "/api/report",
            "facets_url": "/api/facets",
            "grid_url": "/api/grid",
            "grid_response_max_rows": MAX_GRID_ROWS,
            "health_urls": ["/health", "/healthz"],
            "exports": exports,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )

    def _file(
        self,
        path: Path,
        content_type: str | None = None,
        *,
        attachment: str | None = None,
    ) -> None:
        try:
            resolved = path.resolve(strict=True)
            roots = {WEB_ROOT.resolve(), DATA_ROOT.resolve()}
            if not any(root == resolved or root in resolved.parents for root in roots):
                raise FileNotFoundError
            body = resolved.read_bytes()
        except (FileNotFoundError, OSError):
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
            return
        if content_type is None and resolved.suffix.lower() == ".csv":
            media = "text/csv"
        else:
            media = (
                content_type
                or mimetypes.guess_type(resolved.name)[0]
                or "application/octet-stream"
            )
        self._send(HTTPStatus.OK, body, media, attachment=attachment)

    def log_message(self, message: str, *args: object) -> None:
        print(f"[clx-target-hit] {self.address_string()} {message % args}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve the CLX18 report on a loopback-only local address."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18765)
    args = parser.parse_args()
    try:
        address = ipaddress.ip_address(args.host)
    except ValueError:
        if args.host.lower() != "localhost":
            parser.error("--host must be 127.0.0.1, ::1, or localhost")
    else:
        if not address.is_loopback:
            parser.error("--host must be a loopback address")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"CLX18 target-hit report: http://{args.host}:{args.port}")
    print(f"Health check: http://{args.host}:{args.port}/healthz")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCLX18 target-hit report stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
