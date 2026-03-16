from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

DEFAULT_ACCEPTED_STATUS_CODES = (200, 204, 301, 302, 405)


@dataclass(frozen=True)
class HealthCheckResult:
    url: str
    ok: bool
    status_code: int | None
    attempts: int
    error: str | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_deploy_plan_module():
    module_path = _repo_root() / "script" / "freshquant_deploy_plan.py"
    spec = importlib.util.spec_from_file_location("freshquant_deploy_plan", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load deploy plan module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_multi_values(values: list[str] | None) -> list[str]:
    tokens: list[str] = []
    for raw_value in values or []:
        for token in raw_value.split(","):
            normalized = token.strip()
            if normalized:
                tokens.append(normalized)
    return tokens


def unique_in_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def resolve_check_urls(
    surfaces: list[str] | None = None,
    extra_urls: list[str] | None = None,
) -> list[str]:
    urls: list[str] = []
    normalized_surfaces = parse_multi_values(surfaces)
    normalized_extra_urls = parse_multi_values(extra_urls)

    if normalized_surfaces:
        deploy_plan = _load_deploy_plan_module()
        plan = deploy_plan.build_deploy_plan(explicit_surfaces=normalized_surfaces)
        urls.extend(plan["health_checks"])

    urls.extend(normalized_extra_urls)
    return unique_in_order(urls)


def build_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch_status_code(url: str, timeout_seconds: float, opener) -> int:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "freshquant-health-check/1.0"},
        method="GET",
    )
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            return int(getattr(response, "status", response.getcode()))
    except urllib.error.HTTPError as error:
        return int(error.code)


def run_health_checks(
    urls: list[str],
    *,
    timeout_seconds: float,
    retries: int,
    retry_delay_seconds: float,
    accepted_status_codes: tuple[int, ...] = DEFAULT_ACCEPTED_STATUS_CODES,
    opener=None,
    fetch_status: Callable[[str, float, object], int] = fetch_status_code,
) -> list[HealthCheckResult]:
    active_opener = opener if opener is not None else build_opener()
    results: list[HealthCheckResult] = []

    for url in urls:
        last_status_code: int | None = None
        last_error: str | None = None
        ok = False

        for attempt in range(1, retries + 1):
            try:
                status_code = fetch_status(url, timeout_seconds, active_opener)
                last_status_code = status_code
                if status_code in accepted_status_codes:
                    ok = True
                    last_error = None
                    results.append(
                        HealthCheckResult(
                            url=url,
                            ok=True,
                            status_code=status_code,
                            attempts=attempt,
                        )
                    )
                    break

                last_error = f"unexpected status: {status_code}"
            except Exception as error:  # pragma: no cover - exercised via tests
                last_error = str(error)

            if attempt < retries:
                time.sleep(retry_delay_seconds)

        if not ok:
            results.append(
                HealthCheckResult(
                    url=url,
                    ok=False,
                    status_code=last_status_code,
                    attempts=retries,
                    error=last_error,
                )
            )

    return results


def build_payload(
    surfaces: list[str],
    urls: list[str],
    results: list[HealthCheckResult],
) -> dict[str, object]:
    failures = [result.url for result in results if not result.ok]
    return {
        "surfaces": surfaces,
        "urls": urls,
        "checks": [asdict(result) for result in results],
        "failures": failures,
        "passed": not failures,
    }


def render_summary(payload: dict[str, object]) -> str:
    surfaces = payload["surfaces"]
    checks = payload["checks"]
    failures = payload["failures"]
    lines = [
        "freshquant health check",
        f"surfaces: {', '.join(surfaces) if surfaces else '(custom urls only)'}",
        f"passed: {str(payload['passed']).lower()}",
        "checks:",
    ]
    for check in checks:
        status = check["status_code"] if check["status_code"] is not None else "ERR"
        outcome = "ok" if check["ok"] else "fail"
        detail = f"{outcome} {status} ({check['attempts']} attempts) {check['url']}"
        if check["error"]:
            detail += f" :: {check['error']}"
        lines.append(f"- {detail}")
    if failures:
        lines.append("failures:")
        for failure in failures:
            lines.append(f"- {failure}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run FreshQuant health checks without inheriting system proxy settings."
    )
    parser.add_argument(
        "--surface",
        action="append",
        default=[],
        help="Deployment surface names, comma-separated or repeated.",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Additional health-check URLs, comma-separated or repeated.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Per-request timeout in seconds.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Retry count per URL.",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=1.0,
        help="Delay between retries in seconds.",
    )
    parser.add_argument(
        "--format",
        choices=("summary", "json"),
        default="summary",
        help="Output format.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    surfaces = parse_multi_values(args.surface)
    urls = resolve_check_urls(surfaces=surfaces, extra_urls=args.url)
    if not urls:
        parser.error("At least one --surface or --url target is required.")

    results = run_health_checks(
        urls,
        timeout_seconds=args.timeout,
        retries=args.retries,
        retry_delay_seconds=args.retry_delay,
    )
    payload = build_payload(surfaces=surfaces, urls=urls, results=results)

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_summary(payload))

    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
