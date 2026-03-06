import subprocess
import sys


def test_fqctl_help_works_without_loading_native_extensions() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "freshquant.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Usage:" in result.stdout
