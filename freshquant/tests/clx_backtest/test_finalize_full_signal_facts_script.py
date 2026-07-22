from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FINALIZE_SCRIPT = REPO_ROOT / "script/clx_backtest/finalize_full_signal_facts.sh"
RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
SIGNAL_DIGEST = "a" * 64
SNAPSHOT_ID = "snapshot-fixture"
SNAPSHOT_MANIFEST_SHA256 = "b" * 64
ENGINE_SHA256 = "c" * 64
IMAGE_ID = "sha256:" + "d" * 64
IMAGE_SOURCE_COMMIT = "e" * 40


def _inline_program() -> str:
    source = FINALIZE_SCRIPT.read_text(encoding="utf-8")
    marker = "python3 - <<'PY'\n"
    return source.split(marker, maxsplit=1)[1].split("\nPY\n", maxsplit=1)[0]


def _write_with_sidecar(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.with_name(f"{path.stem}.sha256").write_text(
        hashlib.sha256(payload).hexdigest() + "\n",
        encoding="ascii",
    )


def _fixture_environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    run_root = tmp_path / "run"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    manifest = {
        "state": "COMPLETE",
        "run_id": RUN_ID,
        "signal_set_id": f"sha256:{SIGNAL_DIGEST}",
        "snapshot": {
            "snapshot_id": SNAPSHOT_ID,
            "manifest_sha256": SNAPSHOT_MANIFEST_SHA256,
        },
        "engine": {"native_module_sha256": ENGINE_SHA256},
        # The sealed runner image intentionally contains no .git directory.
        "code": {"git_commit": None},
        "config": {"wave_opt": 1560, "stretch_opt": 0, "ext_opt": 0},
        "counts": {"signal_revisions": 4, "tradable_signal_facts": 3},
        "completed_buckets": [0, 1],
    }
    manifest_payload = (json.dumps(manifest, sort_keys=True) + "\n").encode("utf-8")
    _write_with_sidecar(
        run_root / "facts/manifest.json",
        manifest_payload,
    )
    contract = {
        "run_id": RUN_ID,
        "git_commit": "f" * 40,
        "holdout_state": "LOCKED",
        "source": {
            "image_source_commit": IMAGE_SOURCE_COMMIT,
            "image_host_source_commit": "1" * 40,
        },
        "snapshot": {
            "snapshot_id": SNAPSHOT_ID,
            "manifest_sha256": SNAPSHOT_MANIFEST_SHA256,
            "rows": 3,
        },
        "engine": {
            "image_id": IMAGE_ID,
            "module_sha256": ENGINE_SHA256,
            "wave_opt": 1560,
            "stretch_opt": 0,
            "trend_opt": 0,
            "image_identity": {
                "id": IMAGE_ID,
                "source_commit": IMAGE_SOURCE_COMMIT,
                "host_source_commit": "1" * 40,
                "native_module_sha256": ENGINE_SHA256,
            },
        },
    }
    _write_with_sidecar(
        run_root / "run-contract.json",
        (json.dumps(contract, sort_keys=True) + "\n").encode("utf-8"),
    )
    (run_root / ".runner").mkdir()
    for path in (run_root / "facts").rglob("*"):
        path.chmod(0o444 if path.is_file() else 0o555)
    (run_root / "facts").chmod(0o555)
    env = os.environ.copy()
    env.update(
        {
            "VERIFY_JSON": json.dumps(
                {
                    "status": "verified",
                    "deep": True,
                    "signal_set_id": f"sha256:{SIGNAL_DIGEST}",
                    "snapshot_id": SNAPSHOT_ID,
                    "manifest_sha256": hashlib.sha256(manifest_payload).hexdigest(),
                    "completed_buckets": 2,
                    "signal_revisions": 4,
                    "tradable_signal_facts": 3,
                }
            ),
            "RUN_ROOT": str(run_root),
            "EVIDENCE_ROOT": str(evidence_root),
            "CLX_ENGINE_IMAGE_ID": IMAGE_ID,
            "IMAGE_SOURCE_COMMIT": IMAGE_SOURCE_COMMIT,
            "IMAGE_HOST_SOURCE_COMMIT": "1" * 40,
            "IMAGE_ENGINE_SHA256": ENGINE_SHA256,
        }
    )
    return env, evidence_root


def _run_inline(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _inline_program()],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )


def test_finalizer_contract_uses_exclusive_immutable_publication() -> None:
    source = FINALIZE_SCRIPT.read_text(encoding="utf-8")

    assert "os.O_EXCL" in source
    assert "os.link(temporary, path)" in source
    assert "path.read_bytes() != payload" in source
    assert "os.fchmod(target_descriptor, 0o444)" in source
    assert "fsync_directory(path.parent)" in source
    assert 'contract.get("run_id") != run_id' in source
    assert 'verify.get("signal_set_id") != signal_set_id' in source
    assert 'contract_source.get("image_source_commit") != image_source_commit' in source
    assert 'run_root / ".runner" / "finalized"' in source
    assert 'f"v2-causal-signal-{run_id}-{signal_digest}.json"' in source
    assert 'target.with_name(f"{target.name}.sha256")' in source


@pytest.mark.skipif(
    os.name == "nt",
    reason="The finalizer is a Linux artifact-runtime contract.",
)
def test_finalizer_reuses_only_byte_identical_evidence(tmp_path: Path) -> None:
    env, evidence_root = _fixture_environment(tmp_path)
    target = evidence_root / f"v2-causal-signal-{RUN_ID}-{SIGNAL_DIGEST}.json"
    sidecar = target.with_name(f"{target.name}.sha256")

    first = _run_inline(env)
    assert first.returncode == 0, first.stderr
    evidence_bytes = target.read_bytes()
    sidecar_bytes = sidecar.read_bytes()
    assert json.loads(evidence_bytes)["run_id"] == RUN_ID
    assert sidecar_bytes == (
        f"{hashlib.sha256(evidence_bytes).hexdigest()}  {target.name}\n".encode("ascii")
    )
    assert stat.S_IMODE(target.stat().st_mode) == 0o444
    assert stat.S_IMODE(sidecar.stat().st_mode) == 0o444
    marker = Path(env["RUN_ROOT"]) / ".runner/finalized"
    marker_document = json.loads(marker.read_text(encoding="utf-8"))
    assert marker_document["run_id"] == RUN_ID
    assert marker_document["signal_set_id"] == f"sha256:{SIGNAL_DIGEST}"
    assert stat.S_IMODE(marker.stat().st_mode) == 0o444

    repeated = _run_inline(env)
    assert repeated.returncode == 0, repeated.stderr
    assert target.read_bytes() == evidence_bytes
    assert sidecar.read_bytes() == sidecar_bytes

    sidecar.chmod(0o644)
    sidecar.write_bytes(b"different sidecar\n")
    sidecar.chmod(0o444)
    sidecar_conflict = _run_inline(env)
    assert sidecar_conflict.returncode != 0
    assert "immutable evidence conflict" in sidecar_conflict.stderr

    sidecar.chmod(0o644)
    sidecar.write_bytes(sidecar_bytes)
    sidecar.chmod(0o444)
    target.chmod(0o644)
    target.write_bytes(b"different evidence\n")
    target.chmod(0o444)
    evidence_conflict = _run_inline(env)
    assert evidence_conflict.returncode != 0
    assert "immutable evidence conflict" in evidence_conflict.stderr


@pytest.mark.skipif(
    os.name == "nt",
    reason="The finalizer is a Linux artifact-runtime contract.",
)
def test_finalizer_rejects_cross_identity_manifest_contract_or_verify(
    tmp_path: Path,
) -> None:
    env, evidence_root = _fixture_environment(tmp_path)
    contract_path = Path(env["RUN_ROOT"]) / "run-contract.json"
    contract_path.chmod(0o644)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["run_id"] = "DIFFERENT_RUN"
    contract_payload = (json.dumps(contract, sort_keys=True) + "\n").encode("utf-8")
    contract_path.write_bytes(contract_payload)
    contract_path.chmod(0o444)
    sidecar = contract_path.with_name("run-contract.sha256")
    sidecar.chmod(0o644)
    sidecar.write_text(
        hashlib.sha256(contract_payload).hexdigest() + "\n", encoding="ascii"
    )
    sidecar.chmod(0o444)

    mismatched_contract = _run_inline(env)
    assert mismatched_contract.returncode != 0
    assert "run_id differ" in mismatched_contract.stderr
    assert not list(evidence_root.iterdir())

    contract["run_id"] = RUN_ID
    contract["source"]["image_host_source_commit"] = "1" * 40
    contract_payload = (json.dumps(contract, sort_keys=True) + "\n").encode("utf-8")
    contract_path.chmod(0o644)
    contract_path.write_bytes(contract_payload)
    contract_path.chmod(0o444)
    sidecar.chmod(0o644)
    sidecar.write_text(
        hashlib.sha256(contract_payload).hexdigest() + "\n", encoding="ascii"
    )
    sidecar.chmod(0o444)
    contract["source"]["image_source_commit"] = "0" * 40
    contract_payload = (json.dumps(contract, sort_keys=True) + "\n").encode("utf-8")
    contract_path.chmod(0o644)
    contract_path.write_bytes(contract_payload)
    contract_path.chmod(0o444)
    sidecar.chmod(0o644)
    sidecar.write_text(
        hashlib.sha256(contract_payload).hexdigest() + "\n", encoding="ascii"
    )
    sidecar.chmod(0o444)

    mismatched_source = _run_inline(env)
    assert mismatched_source.returncode != 0
    assert "source commit differs" in mismatched_source.stderr
    assert not list(evidence_root.iterdir())

    contract["source"]["image_source_commit"] = IMAGE_SOURCE_COMMIT
    contract_payload = (json.dumps(contract, sort_keys=True) + "\n").encode("utf-8")
    contract_path.chmod(0o644)
    contract_path.write_bytes(contract_payload)
    contract_path.chmod(0o444)
    sidecar.chmod(0o644)
    sidecar.write_text(
        hashlib.sha256(contract_payload).hexdigest() + "\n", encoding="ascii"
    )
    sidecar.chmod(0o444)
    verify = json.loads(env["VERIFY_JSON"])
    verify["signal_set_id"] = "sha256:" + "9" * 64
    env["VERIFY_JSON"] = json.dumps(verify)

    mismatched_verify = _run_inline(env)
    assert mismatched_verify.returncode != 0
    assert "signal_set_id differs" in mismatched_verify.stderr
    assert not list(evidence_root.iterdir())
