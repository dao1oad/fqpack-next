"""前 100 深析执行器：有限并发、逐标的失败记录/重试、输出 schema 校验。

自动主链在 `rank` 之后调用本执行器，对全部 `tier=deep` 标的执行标准单股
深析（通过仓库内 `agent_run.py` 适配器启动隔离 agent 会话）。执行器：

- 幂等：已存在且通过 schema 校验的 `fundamental-analysis/<symbol>.json`
  直接跳过（状态 skipped），不重复调用；
- 有限并发：`--workers`（默认 2）线程池；
- 失败不伪造：只接受 agent 写入且通过校验的产物；失败记录 error 并按
  `--max-attempts` 重试；最终状态写入 `fundamental-deep-run.json`；
- 产出合格性由最终 `stats` 质量门（deepCompletionRate=1.0）把关。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shlex
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from .contracts import (
    ANALYSIS_DIR_NAME,
    RANKING_JSON_NAME,
    SPEC_DIR_NAME,
    TIER_DEEP,
)
from .deep_analysis import load_analysis_docs
from .quick_rank import read_ranking_json
from .validate import validate_analysis_doc

RUN_STATE_NAME = "fundamental-deep-run.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc(value: str) -> str:
    return value or utc_now()


class DeepExecutor:
    def __init__(
        self,
        run_dir: pathlib.Path,
        *,
        workers: int = 2,
        max_attempts: int = 2,
        agent_command: str | None = None,
        dry_run: bool = False,
        timeout: int = 1500,
        env: dict[str, str] | None = None,
    ) -> None:
        self.run_dir = pathlib.Path(run_dir)
        self.analysis_dir = self.run_dir / ANALYSIS_DIR_NAME
        self.spec_dir = self.run_dir / SPEC_DIR_NAME
        self.state_path = self.run_dir / RUN_STATE_NAME
        self.workers = max(1, workers)
        self.max_attempts = max(1, max_attempts)
        self.timeout = timeout
        self.dry_run = dry_run
        self.agent_command = agent_command
        self.env = env
        self._lock = threading.Lock()

    @property
    def adapter_path(self) -> pathlib.Path:
        return pathlib.Path(__file__).parent / "agent_run.py"

    def deep_rows(self) -> list[dict[str, Any]]:
        payload = read_ranking_json(self.run_dir / RANKING_JSON_NAME)
        return [
            row for row in (payload.get("rows") or []) if row.get("tier") == TIER_DEEP
        ]

    def load_state(self) -> dict[str, dict[str, Any]]:
        if not self.state_path.is_file():
            return {}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            return {
                str(symbol): entry
                for symbol, entry in (payload.get("symbols") or {}).items()
            }
        except (json.JSONDecodeError, OSError):
            return {}

    def save_state(self, state: dict[str, dict[str, Any]]) -> None:
        payload = {
            "schemaVersion": "clx-fundamental-deep-run.v1",
            "runDir": self.run_dir.name,
            "updatedAt": utc_now(),
            "symbols": state,
        }
        self.state_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )

    def output_path(self, symbol: str) -> pathlib.Path:
        return self.analysis_dir / f"{symbol}.json"

    def spec_path(self, symbol: str) -> pathlib.Path:
        return self.spec_dir / f"{symbol}.md"

    def render_command(self, symbol: str) -> list[str]:
        """渲染 agent 命令。

        `agent_command` 为 None 时使用仓库内置适配器（直接列表，不经 shell）；
        自定义模板支持占位符 {symbol}/{spec_path}/{output_path}/{work_dir}/{python}，
        先按 posix 分词（占位符是独立 token，路径替换发生在分词之后，避免
        Windows 反斜杠被转义）。
        """
        if self.agent_command is None:
            return [
                sys.executable,
                str(self.adapter_path),
                "--symbol",
                symbol,
                "--spec",
                str(self.spec_path(symbol)),
                "--output",
                str(self.output_path(symbol)),
                "--timeout",
                "900",
            ]
        tokens = shlex.split(self.agent_command)
        return [
            token.replace("{symbol}", symbol)
            .replace("{spec_path}", self.spec_path(symbol).as_posix())
            .replace("{output_path}", self.output_path(symbol).as_posix())
            .replace("{work_dir}", self.run_dir.as_posix())
            .replace("{python}", sys.executable.replace("\\", "/"))
            for token in tokens
        ]

    def existing_valid_doc(self, symbol: str) -> dict[str, Any] | None:
        path = self.output_path(symbol)
        if not path.is_file():
            return None
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        ok, _ = validate_analysis_doc(doc)
        return doc if ok else None

    def run_symbol(
        self,
        symbol: str,
        state: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "symbol": symbol,
            "status": "pending",
            "attempts": 0,
            "error": "",
            "started_at": _utc(""),
            "finished_at": "",
        }
        with self._lock:
            previous = state.get(symbol)
            if previous and previous.get("status") in {"ok", "skipped"}:
                if self.existing_valid_doc(symbol) is not None:
                    return previous
            if self.existing_valid_doc(symbol) is not None:
                entry.update(
                    {
                        "status": "skipped",
                        "started_at": (
                            previous.get("started_at", entry["started_at"])
                            if previous
                            else entry["started_at"]
                        ),
                        "finished_at": _utc(""),
                        "error": "existing valid deep JSON",
                    }
                )
                state[symbol] = entry
                return entry
            state[symbol] = entry
            entry["started_at"] = utc_now()
        if self.dry_run:
            entry["status"] = "pending"
            entry["error"] = "dry-run: scheduled only"
            return entry
        for attempt in range(1, self.max_attempts + 1):
            entry["attempts"] = attempt
            try:
                result = subprocess.run(
                    self.render_command(symbol),
                    cwd=str(self.run_dir),
                    env=self.env,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )
                command_ok = result.returncode == 0
            except subprocess.TimeoutExpired:
                command_ok = False
                result = None
            doc = self.existing_valid_doc(symbol)
            if command_ok and doc is not None:
                entry.update(
                    {
                        "status": "ok",
                        "error": "",
                        "finished_at": utc_now(),
                    }
                )
                break
            tail = ""
            if result is not None:
                tail = (
                    f" exit={result.returncode} stdout={result.stdout[-800:]!r}"
                    f" stderr={result.stderr[-800:]!r}"
                )
            entry["error"] = (
                f"attempt {attempt}/{self.max_attempts}: "
                f"{'invalid or missing output JSON' if command_ok else 'command failed'}{tail}"
            )
            entry["finished_at"] = utc_now()
        if entry["status"] == "pending":
            entry["status"] = "failed"
        with self._lock:
            state[symbol] = entry
        return entry

    def run(self) -> dict[str, Any]:
        rows = self.deep_rows()
        state = self.load_state()
        entries: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {
                pool.submit(self.run_symbol, str(row["symbol"]), state): str(
                    row["symbol"]
                )
                for row in rows
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    entries.append(future.result())
                except Exception as exc:  # noqa: BLE001 - per-symbol isolation
                    entry = {
                        "symbol": symbol,
                        "status": "failed",
                        "attempts": self.max_attempts,
                        "error": f"executor exception: {exc}",
                        "started_at": utc_now(),
                        "finished_at": utc_now(),
                    }
                    state[symbol] = entry
                    entries.append(entry)
        summary = {
            "total": len(entries),
            "ok": sum(1 for entry in entries if entry.get("status") == "ok"),
            "skipped": sum(1 for entry in entries if entry.get("status") == "skipped"),
            "failed": sum(1 for entry in entries if entry.get("status") == "failed"),
            "pending": sum(1 for entry in entries if entry.get("status") == "pending"),
        }
        report = {
            "schemaVersion": "clx-fundamental-deep-run-report.v1",
            "runDir": self.run_dir.name,
            "dryRun": self.dry_run,
            "workers": self.workers,
            "maxAttempts": self.max_attempts,
            "summary": summary,
            "symbols": entries,
        }
        (self.run_dir / "fundamental-deep-run-report.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        with self._lock:
            self.save_state(state)
        return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=pathlib.Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=1500)
    parser.add_argument("--agent-command", default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    executor = DeepExecutor(
        args.run_dir,
        workers=args.workers,
        max_attempts=args.max_attempts,
        agent_command=args.agent_command,
        dry_run=args.dry_run,
        timeout=args.timeout,
    )
    report = executor.run()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()


def deep_rows_from_ranking(run_dir: pathlib.Path) -> list[dict[str, Any]]:
    """供测试与外部工具读取深析名单。"""
    return DeepExecutor(run_dir).deep_rows()


def analysis_docs_ok(run_dir: pathlib.Path) -> bool:
    docs = load_analysis_docs(run_dir)
    return all(ok for ok, _ in (validate_analysis_doc(doc) for doc in docs.values()))
