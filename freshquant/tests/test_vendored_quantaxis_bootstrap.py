import os
import subprocess
import sys
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_bootstrap(script: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_importing_freshquant_prefers_vendored_quantaxis_path() -> None:
    result = _run_bootstrap(
        f"""
        import importlib.util
        import site
        import sys

        repo_root = r"{PROJECT_ROOT}"
        site_packages = next(
            entry for entry in site.getsitepackages() if entry.endswith("site-packages")
        )
        remaining = [
            entry
            for entry in sys.path
            if entry not in {{repo_root, site_packages}}
        ]
        sys.path[:] = [
            repo_root,
            site_packages,
            *remaining,
        ]

        import freshquant

        print(importlib.util.find_spec("QUANTAXIS").origin)
        """
    )

    assert result.returncode == 0, result.stderr
    assert "sunflower/QUANTAXIS/QUANTAXIS/__init__.py" in result.stdout.replace(
        "\\", "/"
    )
