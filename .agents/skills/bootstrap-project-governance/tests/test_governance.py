from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = SKILL_ROOT / "scripts" / "bootstrap_governance.py"


class GovernanceFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="governance-test-")
        self.repo = Path(self.temp.name) / "项目 fixture"
        self.repo.mkdir()
        self.run_process(
            [
                sys.executable,
                "-X",
                "utf8",
                str(BOOTSTRAP),
                "apply",
                "--repo",
                str(self.repo),
                "--project-name",
                "测试 <项目>",
            ],
            check=True,
        )
        self.run_process(["git", "init"], cwd=self.repo, check=True)
        (self.repo / "src").mkdir()
        (self.repo / "src" / "app.txt").write_text("initial\n", encoding="utf-8")
        self.configure(exit_code=0)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_process(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        input_text: str | None = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=cwd,
            input=input_text,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=check,
        )

    @property
    def tool(self) -> Path:
        return self.repo / "tools" / "governance.py"

    def gov(
        self, *args: str, input_value: dict | None = None
    ) -> subprocess.CompletedProcess[str]:
        return self.run_process(
            [
                sys.executable,
                "-X",
                "utf8",
                str(self.tool),
                *args,
                "--repo",
                str(self.repo),
            ],
            cwd=self.repo,
            input_text=json.dumps(input_value) if input_value is not None else None,
        )

    def configure(
        self,
        *,
        exit_code: int,
        max_check_runs: int = 10,
        max_stop_continuations: int = 6,
        max_no_progress_stops: int = 3,
        same_failure_limit: int = 2,
        max_age_seconds: int | None = None,
    ) -> None:
        project_path = self.repo / ".governance" / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["outcome"] = "交付一个经过真实模式验证的纵向切片"
        project["nonGoals"] = ["生产部署"]
        project["hardConstraints"] = ["最终证据使用 real 数据模式"]
        project["budgets"].update(
            {
                "maxCheckRuns": max_check_runs,
                "maxStopContinuations": max_stop_continuations,
                "maxNoProgressStops": max_no_progress_stops,
                "sameFailureLimit": same_failure_limit,
            }
        )
        for key in project["preflight"]:
            project["preflight"][key] = True
        project["fallbacks"] = [
            {"when": "external_unready", "action": "continue_independent_slices"}
        ]
        project["finalAcceptance"]["claims"] = [
            {
                "id": "CLAIM-001",
                "description": "真实模式检查通过",
                "itemRef": "WI-001",
                "gateRef": "e2e-real",
                "level": "V2",
                "dataMode": "real",
            }
        ]
        project_path.write_text(
            json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        command = [sys.executable, "-c", f"import sys; sys.exit({exit_code})"]
        work: dict[str, Any] = {
            "schemaVersion": 1,
            "revision": 1,
            "gates": [
                {
                    "id": "e2e-real",
                    "level": "V2",
                    "dataMode": "real",
                    "command": command,
                    "commandWindows": command,
                    "subjectPaths": ["src/**"],
                    "timeoutSeconds": 30,
                }
            ],
            "items": [
                {
                    "id": "WI-001",
                    "title": "Slice <script>alert(1)</script>",
                    "bucket": "NOW",
                    "pathScopes": ["src/**"],
                    "gateRefs": ["e2e-real"],
                    "requiredForFinal": True,
                    "nextCheckpoint": "Run & inspect",
                }
            ],
        }
        if max_age_seconds is not None:
            work["gates"][0]["maxAgeSeconds"] = max_age_seconds
        (self.repo / ".governance" / "work.json").write_text(
            json.dumps(work, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def start(self) -> None:
        ready = self.gov("ready")
        self.assertEqual(ready.returncode, 0, ready.stderr + ready.stdout)
        started = self.gov("start")
        self.assertEqual(started.returncode, 0, started.stderr + started.stdout)

    def hook(self, active: bool = False) -> dict:
        result = self.gov("hook-stop", input_value={"stop_hook_active": active})
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)


class GovernanceRuntimeTests(GovernanceFixture):
    def test_ready_rejects_and_apply_repairs_untrusted_hook(self) -> None:
        hooks_path = self.repo / ".codex" / "hooks.json"
        active_field = "commandWindows" if os.name == "nt" else "command"
        for field, value in (
            (active_field, "echo governance.py hook-stop"),
            ("type", "prompt"),
        ):
            hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
            hooks["hooks"]["Stop"][0]["hooks"][0][field] = value
            hooks_path.write_text(json.dumps(hooks, indent=2) + "\n", encoding="utf-8")
            self.assertEqual(self.gov("ready").returncode, 1)
            repaired = self.run_process(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    str(BOOTSTRAP),
                    "apply",
                    "--repo",
                    str(self.repo),
                ]
            )
            self.assertEqual(repaired.returncode, 0, repaired.stderr)
            self.assertEqual(self.gov("ready").returncode, 0)

        for relative, host in (
            (Path(".codex/hooks.json"), "codex"),
            (Path(".devin/hooks.v1.json"), "devin"),
        ):
            hooks_path = self.repo / relative
            hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
            groups = hooks["hooks"]["Stop"] if host == "codex" else hooks["Stop"]
            if host == "codex":
                groups[0]["matcher"] = ""
            else:
                groups[0].pop("matcher")
            hooks_path.write_text(json.dumps(hooks, indent=2) + "\n", encoding="utf-8")
            self.assertEqual(self.gov("ready").returncode, 1)
            repaired = self.run_process(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    str(BOOTSTRAP),
                    "apply",
                    "--repo",
                    str(self.repo),
                ]
            )
            self.assertEqual(repaired.returncode, 0, repaired.stderr)
            self.assertEqual(self.gov("ready").returncode, 0)

    def test_installer_is_idempotent_and_preserves_hook(self) -> None:
        bootstrap_skill = (
            self.repo
            / ".agents"
            / "skills"
            / "bootstrap-project-governance"
            / "SKILL.md"
        )
        grilling_skill = self.repo / ".agents" / "skills" / "grilling" / "SKILL.md"
        self.assertTrue(bootstrap_skill.is_file())
        self.assertTrue(grilling_skill.is_file())
        self.assertIn("triggers:\n  - user", grilling_skill.read_text(encoding="utf-8"))
        attributes_path = self.repo / ".gitattributes"
        ignore_path = self.repo / ".gitignore"
        attributes_path.write_text(
            "*.custom text eol=lf\n" + attributes_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        ignore_path.write_text(
            "custom-artifact/\n" + ignore_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        hooks_path = self.repo / ".codex" / "hooks.json"
        hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
        hooks["hooks"]["SessionStart"] = [
            {"hooks": [{"type": "command", "command": "echo existing"}]}
        ]
        active_field = "commandWindows" if os.name == "nt" else "command"
        hooks["hooks"]["Stop"][0]["hooks"][0][active_field] = "echo broken"
        hooks_path.write_text(json.dumps(hooks, indent=2) + "\n", encoding="utf-8")
        broken = self.run_process(
            [
                sys.executable,
                "-X",
                "utf8",
                str(BOOTSTRAP),
                "check",
                "--repo",
                str(self.repo),
            ]
        )
        self.assertEqual(broken.returncode, 1)
        second = self.run_process(
            [
                sys.executable,
                "-X",
                "utf8",
                str(BOOTSTRAP),
                "apply",
                "--repo",
                str(self.repo),
            ],
            check=True,
        )
        self.assertEqual(second.returncode, 0)
        merged = json.loads(hooks_path.read_text(encoding="utf-8"))
        self.assertIn("SessionStart", merged["hooks"])
        stop_handlers = [
            handler
            for group in merged["hooks"]["Stop"]
            for handler in group.get("hooks", [])
            if "governance.py"
            in f"{handler.get('command', '')} {handler.get('commandWindows', '')}"
        ]
        self.assertEqual(len(stop_handlers), 1)
        attributes = attributes_path.read_text(encoding="utf-8")
        ignore = ignore_path.read_text(encoding="utf-8")
        self.assertIn("*.custom text eol=lf", attributes)
        self.assertIn("custom-artifact/", ignore)
        self.assertEqual(attributes.count("# BEGIN BOOTSTRAP-PROJECT-GOVERNANCE"), 1)
        self.assertEqual(ignore.count("# BEGIN BOOTSTRAP-PROJECT-GOVERNANCE"), 1)
        self.assertIn("/.governance/runs/**/stdout.log -text", attributes)
        self.assertIn("!.governance/runs/**/stdout.log", ignore)

        devin_hooks_path = self.repo / ".devin" / "hooks.v1.json"
        devin_hooks = json.loads(devin_hooks_path.read_text(encoding="utf-8"))
        devin_hooks["SessionStart"] = [
            {"hooks": [{"type": "command", "command": "echo existing"}]}
        ]
        devin_hooks_path.write_text(
            json.dumps(devin_hooks, indent=2) + "\n", encoding="utf-8"
        )
        third = self.run_process(
            [
                sys.executable,
                "-X",
                "utf8",
                str(BOOTSTRAP),
                "apply",
                "--repo",
                str(self.repo),
            ],
            check=True,
        )
        self.assertEqual(third.returncode, 0)
        merged_devin = json.loads(devin_hooks_path.read_text(encoding="utf-8"))
        self.assertIn("SessionStart", merged_devin)
        devin_stop_handlers = [
            handler
            for group in merged_devin["Stop"]
            for handler in group.get("hooks", [])
            if "governance.py" in handler.get("command", "")
        ]
        self.assertEqual(len(devin_stop_handlers), 1)
        checked = self.run_process(
            [
                sys.executable,
                "-X",
                "utf8",
                str(BOOTSTRAP),
                "check",
                "--repo",
                str(self.repo),
            ]
        )
        self.assertEqual(checked.returncode, 0, checked.stderr + checked.stdout)
        if os.name == "nt":
            self.assertTrue(
                devin_stop_handlers[0]["command"].startswith("powershell.exe ")
            )
            self.assertIn("DEVIN_PROJECT_DIR", devin_stop_handlers[0]["command"])
        else:
            self.assertTrue(devin_stop_handlers[0]["command"].startswith("python3 "))

    def test_fresh_checkout_preserves_governance_evidence_bytes(self) -> None:
        run_dir = self.repo / ".governance" / "runs" / "run-byte-test"
        run_dir.mkdir(parents=True)
        result_bytes = b'{"line":1}\n{"line":2}\n'
        stdout_bytes = b"first\r\nsecond\r\n"
        (run_dir / "result.json").write_bytes(result_bytes)
        (run_dir / "stdout.log").write_bytes(stdout_bytes)
        (run_dir / "stderr.log").write_bytes(b"")

        self.run_process(
            ["git", "config", "user.email", "governance-test@example.invalid"],
            cwd=self.repo,
            check=True,
        )
        self.run_process(
            ["git", "config", "user.name", "Governance Test"],
            cwd=self.repo,
            check=True,
        )
        self.run_process(["git", "add", "."], cwd=self.repo, check=True)
        self.run_process(
            ["git", "commit", "-m", "governance byte fixture"],
            cwd=self.repo,
            check=True,
        )
        checkout = Path(self.temp.name) / "fresh-checkout"
        self.run_process(
            [
                "git",
                "-c",
                "core.autocrlf=true",
                "clone",
                "--quiet",
                str(self.repo),
                str(checkout),
            ],
            check=True,
        )

        cloned_run = checkout / ".governance" / "runs" / "run-byte-test"
        self.assertEqual((cloned_run / "result.json").read_bytes(), result_bytes)
        self.assertEqual((cloned_run / "stdout.log").read_bytes(), stdout_bytes)

    def test_ready_start_hook_run_and_complete(self) -> None:
        pre_start = self.hook()
        self.assertTrue(pre_start["continue"])
        self.assertEqual(pre_start["decision"], "approve")
        self.start()
        missing = self.hook()
        self.assertEqual(missing["decision"], "block")
        self.assertIn("run --item WI-001 --gate e2e-real", missing["reason"])
        check = self.gov("run", "--item", "WI-001", "--gate", "e2e-real")
        self.assertEqual(check.returncode, 0, check.stderr + check.stdout)
        implemented = self.gov(
            "record", "--type", "WORK_IMPLEMENTED", "--item", "WI-001"
        )
        self.assertEqual(implemented.returncode, 0, implemented.stderr)
        completion = self.gov("check", "--completion")
        self.assertEqual(
            completion.returncode, 0, completion.stderr + completion.stdout
        )
        self.assertEqual(json.loads(completion.stdout)["runtimeState"], "COMPLETED")
        completed = self.hook(active=True)
        self.assertTrue(completed["continue"])
        self.assertEqual(completed["decision"], "approve")
        status = json.loads(self.gov("status").stdout)
        self.assertEqual(status["runtimeState"], "COMPLETED")
        board = (self.repo / ".governance" / "board.html").read_text(encoding="utf-8")
        self.assertIn("COMPLETED", board)
        self.assertIn("CLAIM-001", board)
        self.assertIn("CHECK_FINISHED", board)
        self.assertIn("pass", board)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", board)
        self.assertNotIn("<script>alert(1)</script>", board)
        self.assertNotIn("<script src=", board)
        self.assertNotIn("<link href=", board)
        self.assertNotIn("fetch(", board)
        valid = self.gov("validate")
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)

    def test_source_change_makes_evidence_stale(self) -> None:
        self.start()
        self.assertEqual(
            self.gov("run", "--item", "WI-001", "--gate", "e2e-real").returncode, 0
        )
        (self.repo / "src" / "app.txt").write_text("changed\n", encoding="utf-8")
        report = json.loads(self.gov("check", "--completion").stdout)
        self.assertEqual(report["items"][0]["checks"][0]["status"], "stale")

    def test_completed_state_blocks_when_source_evidence_becomes_stale(self) -> None:
        self.start()
        self.assertEqual(
            self.gov("run", "--item", "WI-001", "--gate", "e2e-real").returncode, 0
        )
        self.assertEqual(
            self.gov(
                "record", "--type", "WORK_IMPLEMENTED", "--item", "WI-001"
            ).returncode,
            0,
        )
        self.assertEqual(self.gov("check", "--completion").returncode, 0)

        (self.repo / "src" / "app.txt").write_text("changed\n", encoding="utf-8")
        blocked = self.hook(active=True)

        self.assertEqual(blocked["decision"], "block")
        self.assertIn("完成证据已失效", blocked["reason"])
        status = json.loads(self.gov("status").stdout)
        self.assertEqual(status["runtimeState"], "COMPLETED_INVALID")
        invalid = self.gov("validate")
        self.assertEqual(invalid.returncode, 1)
        self.assertIn("PROJECT_COMPLETED", invalid.stdout)
        events = [
            json.loads(line)
            for line in (self.repo / ".governance" / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertEqual(events[-1]["type"], "PROJECT_COMPLETED")
        self.assertRegex(events[-1]["completionEvidenceDigest"], r"^[0-9a-f]{64}$")

        (self.repo / "src" / "app.txt").write_text("initial\n", encoding="utf-8")
        recovered = self.hook(active=True)
        self.assertEqual(recovered["decision"], "approve")
        self.assertEqual(
            json.loads(self.gov("status").stdout)["runtimeState"], "COMPLETED"
        )

    def test_completed_state_uses_completion_time_for_gate_freshness(self) -> None:
        self.configure(exit_code=0, max_age_seconds=2)
        self.start()
        self.assertEqual(
            self.gov("run", "--item", "WI-001", "--gate", "e2e-real").returncode, 0
        )
        self.assertEqual(
            self.gov(
                "record", "--type", "WORK_IMPLEMENTED", "--item", "WI-001"
            ).returncode,
            0,
        )
        self.assertEqual(self.gov("check", "--completion").returncode, 0)

        time.sleep(2.2)

        completed = self.hook(active=True)
        self.assertEqual(completed["decision"], "approve")
        self.assertEqual(
            json.loads(self.gov("status").stdout)["runtimeState"], "COMPLETED"
        )

    def test_runner_byte_change_invalidates_completed_evidence(self) -> None:
        self.start()
        self.assertEqual(
            self.gov("run", "--item", "WI-001", "--gate", "e2e-real").returncode, 0
        )
        self.assertEqual(
            self.gov(
                "record", "--type", "WORK_IMPLEMENTED", "--item", "WI-001"
            ).returncode,
            0,
        )
        self.assertEqual(self.gov("check", "--completion").returncode, 0)
        self.tool.write_text(
            self.tool.read_text(encoding="utf-8") + "\n# host adapter metadata\n",
            encoding="utf-8",
        )
        report = json.loads(self.gov("check", "--completion").stdout)
        self.assertFalse(report["eligible"], report)
        self.assertEqual(report["runtimeState"], "COMPLETED_INVALID")
        self.assertEqual(report["items"][0]["checks"][0]["status"], "stale")
        self.assertEqual(self.hook(active=True)["decision"], "block")

    def test_repeat_failure_guard(self) -> None:
        self.configure(exit_code=7, same_failure_limit=2)
        self.start()
        first = self.gov("run", "--item", "WI-001", "--gate", "e2e-real")
        second = self.gov("run", "--item", "WI-001", "--gate", "e2e-real")
        third = self.gov("run", "--item", "WI-001", "--gate", "e2e-real")
        self.assertEqual(first.returncode, 1)
        self.assertEqual(second.returncode, 1)
        self.assertEqual(third.returncode, 2)
        self.assertIn("相同失败", third.stderr)

    def test_stop_budget_reaches_exhausted_then_releases(self) -> None:
        self.configure(exit_code=0, max_stop_continuations=1, max_no_progress_stops=20)
        self.start()
        first = self.hook()
        self.assertEqual(first["decision"], "block")
        second = self.hook(active=True)
        self.assertEqual(second["decision"], "block")
        self.assertIn("EXHAUSTED", second["reason"])
        third = self.hook(active=True)
        self.assertTrue(third["continue"])
        self.assertEqual(third["systemMessage"], "Governance state: EXHAUSTED")
        status = json.loads(self.gov("status").stdout)
        self.assertEqual(status["runtimeState"], "EXHAUSTED")

    def test_contract_drift_has_deterministic_restore(self) -> None:
        self.start()
        project_path = self.repo / ".governance" / "project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["outcome"] = "changed after start"
        project_path.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")
        payload = self.hook()
        self.assertEqual(payload["decision"], "block")
        self.assertIn("restore-contract", payload["reason"])
        restored = self.gov("restore-contract")
        self.assertEqual(restored.returncode, 0, restored.stderr)
        fixed = json.loads(project_path.read_text(encoding="utf-8"))
        self.assertEqual(fixed["outcome"], "交付一个经过真实模式验证的纵向切片")

    def test_board_is_deterministic_and_modified_board_is_detected(self) -> None:
        self.start()
        first = self.gov("derive")
        self.assertEqual(first.returncode, 0)
        board_path = self.repo / ".governance" / "board.html"
        before = board_path.read_bytes()
        before_mtime = board_path.stat().st_mtime_ns
        time.sleep(0.01)
        second_payload = json.loads(self.gov("derive").stdout)
        self.assertFalse(second_payload["changed"])
        self.assertEqual(before, board_path.read_bytes())
        self.assertEqual(before_mtime, board_path.stat().st_mtime_ns)
        board_path.write_bytes(before + b"<!-- manual -->\n")
        invalid = json.loads(self.gov("validate").stdout)
        self.assertIn("BOARD_MODIFIED", invalid["issues"])
        self.assertEqual(self.gov("derive").returncode, 0)
        self.assertEqual(self.gov("validate").returncode, 0)
        work_path = self.repo / ".governance" / "work.json"
        work = json.loads(work_path.read_text(encoding="utf-8"))
        work["revision"] = 2
        work_path.write_text(
            json.dumps(work, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        stale = json.loads(self.gov("validate").stdout)
        self.assertIn("BOARD_STALE", stale["issues"])


if __name__ == "__main__":
    unittest.main()
