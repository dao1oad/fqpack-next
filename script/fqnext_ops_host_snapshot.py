"""FreshQuant 运维控制台 S3：宿主机只读快照采集脚本。

支持两种运行模式：

- 单次（默认）：采集一次并退出（供手工/测试使用）。
- ``--daemon``：常驻循环（默认每 5 分钟采集一次），由仓库 supervisor 托管
  （program ``fqnext_ops_host_snapshot``），不依赖外部计划任务。

只读采集：

- Supervisor XML-RPC ``supervisor.getAllProcessInfo()``（程序状态表）
- ``docker ps -a``（容器状态表）

输出 JSON 快照到 ``ops-snapshot/host-runtime.json``，由 ``fq_apiserver`` 容器
只读挂载读取（方案 B：宿主侧采集 -> JSON 快照 -> apiserver ro bind mount）。

任一数据源失败时对应字段携带 ``error`` 且该部分列表为空，其他字段保留，
页面据此显式降级，不把缺失当健康，也不阻塞其他卡片。

本脚本只读：不调用任何 Supervisor 写方法、不启动/停止容器、不改配置。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import xmlrpc.client
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_RPC_URL = "http://127.0.0.1:10011/RPC2"
DEFAULT_SNAPSHOT_PATH = "D:/fqpack/freshquant-2026.2.23/ops-snapshot/host-runtime.json"
DEFAULT_EXPECTED_SUPERVISOR = 9
DEFAULT_EXPECTED_DOCKER = 10
DEFAULT_COMPOSE_PROJECT = "fqnext_20260223"
DEFAULT_INTERVAL_SECONDS = 300

SUPERVISOR_RUNNING_STATE = "RUNNING"
DOCKER_RUNNING_STATE = "running"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_supervisor_programs(rpc_url: str) -> dict[str, Any]:
    """只读调用 supervisor.getAllProcessInfo()。"""
    try:
        proxy = xmlrpc.client.ServerProxy(rpc_url)
        infos = proxy.supervisor.getAllProcessInfo()
        programs = []
        for info in infos or []:
            start_ts = info.get("start")
            programs.append(
                {
                    "name": str(info.get("name") or ""),
                    "group": str(info.get("group") or ""),
                    "state": str(info.get("statename") or ""),
                    "pid": int(info.get("pid") or 0),
                    "uptime_s": (
                        max(0, int(time.time()) - int(start_ts))
                        if start_ts
                        else None
                    ),
                    "description": str(info.get("description") or ""),
                }
            )
        return {"ok": True, "error": None, "programs": programs}
    except Exception as exc:  # pragma: no cover - 防御降级
        return {
            "ok": False,
            "error": f"supervisor XML-RPC 失败: {exc}",
            "programs": [],
        }


def fetch_docker_containers() -> dict[str, Any]:
    """只读执行 docker ps -a 并解析 JSON 行。"""
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15.0,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            return {
                "ok": False,
                "error": f"docker ps 失败: {detail or result.returncode}",
                "containers": [],
            }
        containers = []
        for line in result.stdout.splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except json.JSONDecodeError:
                continue
            compose_project, compose_service = _parse_compose_labels(
                item.get("Labels") or item.get("Label")
            )
            containers.append(
                {
                    "name": str(item.get("Names") or ""),
                    "image": str(item.get("Image") or ""),
                    "state": str(item.get("State") or ""),
                    "status": str(item.get("Status") or ""),
                    "compose_project": compose_project,
                    "compose_service": compose_service,
                }
            )
        return {"ok": True, "error": None, "containers": containers}
    except Exception as exc:  # pragma: no cover - 防御降级
        return {
            "ok": False,
            "error": f"docker ps 失败: {exc}",
            "containers": [],
        }


def _parse_compose_labels(raw: Any) -> tuple[str | None, str | None]:
    """从 docker ps Labels 字段（k=v,k=v 字符串）解析 compose project/service。"""
    if not isinstance(raw, str) or not raw.strip():
        return None, None
    project = None
    service = None
    for pair in raw.split(","):
        key, separator, value = pair.partition("=")
        key = key.strip()
        value = value.strip()
        if not separator:
            continue
        if key == "com.docker.compose.project":
            project = value
        elif key == "com.docker.compose.service":
            service = value
    return project, service


def build_snapshot(
    *,
    rpc_url: str,
    expected_supervisor: int,
    expected_docker: int,
    compose_project: str,
) -> dict[str, Any]:
    supervisor = fetch_supervisor_programs(rpc_url)
    docker = fetch_docker_containers()
    project_containers = [
        container
        for container in docker["containers"]
        if str(container.get("compose_project") or "") == compose_project
    ]
    running_programs = sum(
        1
        for program in supervisor["programs"]
        if str(program.get("state") or "").upper() == SUPERVISOR_RUNNING_STATE
    )
    running_containers = sum(
        1
        for container in project_containers
        if str(container.get("state") or "").lower() == DOCKER_RUNNING_STATE
    )
    return {
        "captured_at": _utc_iso(),
        "expected": {
            "supervisor_programs": int(expected_supervisor),
            "docker_containers": int(expected_docker),
        },
        "supervisor": {
            "ok": supervisor["ok"],
            "error": supervisor["error"],
            "running_count": running_programs,
            "expected_count": int(expected_supervisor),
            "programs": supervisor["programs"],
        },
        "docker": {
            "ok": docker["ok"],
            "error": docker["error"],
            "running_count": running_containers,
            "expected_count": int(expected_docker),
            "compose_project": compose_project,
            "containers": project_containers,
        },
    }


def write_snapshot(path: Path, snapshot: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    os.replace(temp_path, path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="FreshQuant 运维控制台宿主机只读快照采集（S3）"
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="常驻循环模式（默认每 5 分钟采集一次），由 supervisor 托管",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("FQ_OPS_SNAPSHOT_INTERVAL") or DEFAULT_INTERVAL_SECONDS),
        help=f"daemon 模式采集间隔秒数（默认 {DEFAULT_INTERVAL_SECONDS}s）",
    )
    parser.add_argument(
        "--rpc-url",
        default=os.environ.get("FQ_OPS_SUPERVISOR_RPC_URL") or DEFAULT_RPC_URL,
        help="Supervisor XML-RPC 地址",
    )
    parser.add_argument(
        "--snapshot-path",
        default=os.environ.get("FQ_OPS_SNAPSHOT_PATH") or DEFAULT_SNAPSHOT_PATH,
        help="快照 JSON 输出路径",
    )
    parser.add_argument(
        "--expected-supervisor",
        type=int,
        default=int(os.environ.get("FQ_OPS_EXPECTED_SUPERVISOR") or DEFAULT_EXPECTED_SUPERVISOR),
        help="期望的 Supervisor 程序数（默认 9）",
    )
    parser.add_argument(
        "--expected-docker",
        type=int,
        default=int(os.environ.get("FQ_OPS_EXPECTED_DOCKER") or DEFAULT_EXPECTED_DOCKER),
        help="期望的 Docker 容器数（默认 10，ta_backend 已废弃删除）",
    )
    parser.add_argument(
        "--compose-project",
        default=os.environ.get("FQ_OPS_COMPOSE_PROJECT") or DEFAULT_COMPOSE_PROJECT,
        help="只统计该 compose 项目的容器（默认 fqnext_20260223）",
    )
    args = parser.parse_args()

    interval = max(int(args.interval or DEFAULT_INTERVAL_SECONDS), 10)
    path = Path(args.snapshot_path)

    def _collect_once() -> None:
        snapshot = build_snapshot(
            rpc_url=args.rpc_url,
            expected_supervisor=args.expected_supervisor,
            expected_docker=args.expected_docker,
            compose_project=args.compose_project,
        )
        write_snapshot(path, snapshot)
        print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True), flush=True)
        print(f"snapshot written: {path}", file=os.sys.stderr, flush=True)

    if not args.daemon:
        _collect_once()
        return 0

    # 常驻循环：supervisor 托管，崩溃由 autorestart 拉起；单次失败不中断循环。
    print(
        f"daemon mode: interval={interval}s snapshot={path}",
        file=os.sys.stderr,
        flush=True,
    )
    while True:
        try:
            _collect_once()
        except Exception as exc:  # pragma: no cover - 防御：循环不因单次失败退出
            print(f"snapshot collect failed: {exc}", file=os.sys.stderr, flush=True)
        time.sleep(interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
