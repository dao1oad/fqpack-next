#!/usr/bin/env python3
"""Verify sealed CLX Python/native sources, then run a target in-process."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import runpy
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn, Sequence

SOURCE_ROOT = Path("/opt/clx-src")
ENGINE_ROOT = Path("/opt/clx-engine")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
STAGE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class EngineRuntimeError(RuntimeError):
    pass


def fail(message: str) -> NoReturn:
    raise EngineRuntimeError(message)


def module_file(module: ModuleType, name: str) -> Path:
    value = getattr(module, "__file__", None)
    if not isinstance(value, str) or not value:
        fail(f"{name} has no runtime module path")
    try:
        return Path(value).resolve(strict=True)
    except OSError as exc:
        raise EngineRuntimeError(f"{name} runtime path is unreadable: {value}") from exc


def verify_python_sources(target: Sequence[str]) -> dict[str, Any]:
    source_root = SOURCE_ROOT.resolve(strict=True)
    expected_packages = {
        "freshquant": source_root / "freshquant",
        "freshquant.backtest": source_root / "freshquant/backtest",
        "freshquant.backtest.clx": source_root / "freshquant/backtest/clx",
    }
    package_paths: dict[str, str] = {}
    for name, expected_parent in expected_packages.items():
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            fail(f"sealed Python package was not loaded before the runner: {name}")
        path = module_file(module, name)
        if path.parent != expected_parent:
            fail(f"{name} runtime path is outside sealed source: {path}")
        package_paths[name] = str(path)

    package_root = expected_packages["freshquant.backtest.clx"]
    runner_path = Path(__file__).resolve(strict=True)
    if runner_path.parent != package_root:
        fail(f"verified engine runner is outside sealed CLX source: {runner_path}")

    target_identity: dict[str, str | None] = {
        "target_kind": None,
        "target_module": None,
        "target_module_path": None,
    }
    if len(target) >= 2 and target[0] == "-m":
        module_name = target[1]
        if not module_name.startswith("freshquant.backtest.clx."):
            fail(f"target module is outside the sealed CLX package: {module_name}")
        spec = importlib.util.find_spec(module_name)
        if spec is None or not isinstance(spec.origin, str):
            fail(f"target module has no importable source: {module_name}")
        target_path = Path(spec.origin).resolve(strict=True)
        if package_root not in target_path.parents:
            fail(f"target module is outside sealed CLX source: {target_path}")
        target_identity = {
            "target_kind": "module",
            "target_module": module_name,
            "target_module_path": str(target_path),
        }
    elif target and target[0] == "-":
        target_identity = {
            "target_kind": "stdin",
            "target_module": None,
            "target_module_path": None,
        }
    else:
        fail("verified engine runner expects '-m MODULE ...' or '-' target")
    return {
        "package_paths": package_paths,
        "runner_path": str(runner_path),
        **target_identity,
    }


def verify_engine_runtime(stage: str, target: Sequence[str]) -> dict[str, Any]:
    if STAGE_RE.fullmatch(stage) is None:
        fail(f"invalid CLX engine runtime stage: {stage}")
    expected = os.environ.get("CLX_EXPECTED_ENGINE_SHA256", "").removeprefix("sha256:")
    if SHA256_RE.fullmatch(expected) is None:
        fail("CLX_EXPECTED_ENGINE_SHA256 must be a lowercase SHA-256 digest")

    import fqcopilot

    path = module_file(fqcopilot, "fqcopilot")
    engine_root = ENGINE_ROOT.resolve(strict=True)
    if path.parent != engine_root:
        fail(f"fqcopilot runtime path is outside the sealed engine root: {path}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        fail(f"fqcopilot runtime SHA-256 mismatch: expected={expected} actual={actual}")
    return {
        "module_path": str(path),
        "module_sha256": actual,
        "stage": stage,
        "status": "engine-runtime-verified",
        **verify_python_sources(target),
    }


def run_target(arguments: Sequence[str]) -> int:
    if len(arguments) >= 2 and arguments[0] == "-m":
        module_name = arguments[1]
        sys.argv = [module_name, *arguments[2:]]
        runpy.run_module(module_name, run_name="__main__", alter_sys=True)
        return 0
    if arguments and arguments[0] == "-":
        sys.argv = ["-", *arguments[1:]]
        source = sys.stdin.buffer.read()
        namespace = {
            "__name__": "__main__",
            "__file__": "<stdin>",
            "__package__": None,
            "__cached__": None,
        }
        exec(compile(source, "<stdin>", "exec"), namespace)
        return 0
    fail("verified engine runner expects '-m MODULE ...' or '-' target")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv or sys.argv[1:])
    if len(arguments) < 2:
        fail("verified engine runner requires STAGE and a Python target")
    evidence = verify_engine_runtime(arguments[0], arguments[1:])
    print(json.dumps(evidence, sort_keys=True), file=sys.stderr, flush=True)
    return run_target(arguments[1:])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EngineRuntimeError as exc:
        print(f"run_verified_engine_python: {exc}", file=sys.stderr)
        raise SystemExit(65) from exc
