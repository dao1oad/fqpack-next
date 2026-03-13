from __future__ import annotations

import sys
from pathlib import Path


def _normalize_path(entry: str | Path) -> str:
    try:
        return str(Path(entry).resolve()).casefold()
    except OSError:
        return str(entry).strip().casefold()


def ensure_vendored_quantaxis_path(repo_root: str | Path | None = None) -> str | None:
    root = (
        Path(repo_root)
        if repo_root is not None
        else Path(__file__).resolve().parents[2]
    )
    vendored_root = root / "sunflower" / "QUANTAXIS"
    vendored_init = vendored_root / "QUANTAXIS" / "__init__.py"
    if not vendored_init.exists():
        return None

    vendored_root_str = str(vendored_root)
    normalized_root = _normalize_path(vendored_root)
    sys.path[:] = [
        entry for entry in sys.path if _normalize_path(entry) != normalized_root
    ]
    sys.path.insert(0, vendored_root_str)
    return vendored_root_str
