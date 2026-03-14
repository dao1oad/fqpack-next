from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from html import unescape
from typing import Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import ProxyHandler, Request, build_opener


SCRIPT_SRC_PATTERN = re.compile(
    r"<script[^>]+src=[\"'](?P<src>[^\"']+\.js[^\"']*)[\"']",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    body: str


def fetch_text(url: str) -> FetchResult:
    request = Request(url, headers={"User-Agent": "freshquant-release-probe/1.0"})
    hostname = (urlparse(url).hostname or "").lower()
    opener = (
        build_opener(ProxyHandler({}))
        if hostname in {"127.0.0.1", "localhost", "::1"}
        else build_opener()
    )
    with opener.open(request, timeout=5) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        body = response.read().decode(charset, errors="replace")
        return FetchResult(url=url, status=response.getcode(), body=body)


def extract_script_paths(html: str) -> list[str]:
    return [unescape(match.group("src")) for match in SCRIPT_SRC_PATTERN.finditer(html)]


def choose_bundle_paths(page_path: str, script_paths: Iterable[str]) -> list[str]:
    paths = list(dict.fromkeys(script_paths))
    if "runtime-observability" in page_path:
        preferred = [path for path in paths if "runtime-observability" in path]
        if preferred:
            return preferred
    return paths


def probe_frontend_release(
    *,
    base_url: str,
    page_path: str = "/runtime-observability",
    fallback_page_path: str = "/",
    markers: list[str] | None = None,
    container_name: str | None = None,
) -> dict[str, object]:
    markers = markers or []
    tried_paths = [page_path]
    page_result: FetchResult | None = None
    used_fallback = False

    for candidate_path in tried_paths + ([fallback_page_path] if fallback_page_path not in tried_paths else []):
        try:
            page_result = fetch_text(urljoin(base_url.rstrip("/") + "/", candidate_path.lstrip("/")))
            used_fallback = candidate_path != page_path
            break
        except Exception:
            continue

    if page_result is None:
        return {
            "base_url": base_url,
            "page_path": page_path,
            "fallback_page_path": fallback_page_path,
            "used_fallback": False,
            "container_name": container_name,
            "bundle_path": None,
            "bundle_paths": [],
            "markers": {marker: False for marker in markers},
            "passed": False,
            "reason": "unable to fetch target page",
        }

    script_paths = extract_script_paths(page_result.body)
    bundle_paths = choose_bundle_paths(page_result.url, script_paths)
    bundle_fetches = [
        fetch_text(urljoin(base_url.rstrip("/") + "/", bundle_path.lstrip("/")))
        for bundle_path in bundle_paths
    ]

    marker_hits = {
        marker: any(marker in bundle.body for bundle in bundle_fetches) for marker in markers
    }
    bundle_match_counts = {
        bundle.url: sum(marker in bundle.body for marker in markers)
        for bundle in bundle_fetches
    }

    selected_bundle_path = None
    if bundle_fetches:
        selected_bundle_path = bundle_fetches[0].url.removeprefix(base_url.rstrip("/"))
        best_bundle = max(bundle_fetches, key=lambda bundle: bundle_match_counts[bundle.url])
        if bundle_match_counts[best_bundle.url] > 0:
            selected_bundle_path = best_bundle.url.removeprefix(base_url.rstrip("/"))

    return {
        "base_url": base_url,
        "page_path": page_path,
        "fallback_page_path": fallback_page_path,
        "used_fallback": used_fallback,
        "container_name": container_name,
        "bundle_path": selected_bundle_path,
        "bundle_paths": [bundle.url.removeprefix(base_url.rstrip("/")) for bundle in bundle_fetches],
        "markers": marker_hits,
        "passed": bool(bundle_fetches) and all(marker_hits.values()),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe FreshQuant frontend release bundles")
    parser.add_argument("--base-url", required=True, help="Base URL of the running web UI")
    parser.add_argument(
        "--page-path",
        default="/runtime-observability",
        help="Primary page path to inspect",
    )
    parser.add_argument(
        "--fallback-page-path",
        default="/",
        help="Fallback page path when the primary page is unavailable",
    )
    parser.add_argument(
        "--marker",
        action="append",
        default=[],
        help="Required marker string; repeat for multiple markers",
    )
    parser.add_argument(
        "--container-name",
        help="Optional container name for evidence output",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = probe_frontend_release(
        base_url=args.base_url,
        page_path=args.page_path,
        fallback_page_path=args.fallback_page_path,
        markers=args.marker,
        container_name=args.container_name,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
