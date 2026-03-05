"""
Python wrapper for the native fullcalc (chanlun + CLX + stop-loss) module.

It will auto-load the compiled extension from:
`morningglory/fqcopilot/python/fullcalc.pyd`
"""

from __future__ import annotations

from pathlib import Path
import importlib
import sys
from typing import Any

import pandas as pd


_MODULE_LOADED = False


def _ensure_module_loaded() -> None:
    global _MODULE_LOADED
    if _MODULE_LOADED:
        return
    root = Path(__file__).resolve().parents[2]
    mod_dir = root / "morningglory" / "fqcopilot" / "python"
    if str(mod_dir) not in sys.path:
        sys.path.insert(0, str(mod_dir))
    importlib.import_module("fullcalc")
    _MODULE_LOADED = True


def run_fullcalc(
    df: pd.DataFrame,
    *,
    wave_opt: int = 1560,
    stretch_opt: int = 0,
    trend_opt: int = 1,
    model_ids: list[int] | None = None,
) -> dict[str, Any]:
    """
    Run full calculation on a pandas DataFrame with columns:
    ['open','high','low','close','volume'].
    """
    _ensure_module_loaded()
    import fullcalc  # type: ignore

    required = ["high", "low", "open", "close", "volume"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"missing column: {col}")

    high = df["high"].astype(float).tolist()
    low = df["low"].astype(float).tolist()
    open_ = df["open"].astype(float).tolist()
    close = df["close"].astype(float).tolist()
    vol = df["volume"].astype(float).tolist()

    mids = list(model_ids or [])
    return fullcalc.full_calc(
        high,
        low,
        open_,
        close,
        vol,
        wave_opt=wave_opt,
        stretch_opt=stretch_opt,
        trend_opt=trend_opt,
        model_ids=mids,
    )


__all__ = ["run_fullcalc"]

