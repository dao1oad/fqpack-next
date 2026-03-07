from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from freshquant.runtime.extension_build import build_fullcalc_plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Build project native extensions")
    parser.add_argument(
        "--target",
        choices=["fullcalc"],
        default="fullcalc",
        help="Extension target to build",
    )
    parser.add_argument(
        "--xmake-bin",
        default="xmake",
        help="xmake executable path",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    platform_target = "windows" if os.name == "nt" else "posix"

    if args.target != "fullcalc":
        raise ValueError(f"unsupported target: {args.target}")

    plan = build_fullcalc_plan(
        repo_root,
        target=platform_target,
        xmake_bin=args.xmake_bin,
    )
    env = dict(os.environ)
    env.update(plan["env"])
    workdir = plan["workdir"]

    for command in plan["commands"]:
        subprocess.run(command, cwd=workdir, env=env, check=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
