from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

CLX_TDX_GROUP_DISPLAY_NAME = "clx_18"
CLX_TDX_BLOCK_KEY = "CLX_18"
CLX_TDX_BLK_FILENAME = f"{CLX_TDX_BLOCK_KEY}.blk"


def encode_tdx_blk_code(value: object) -> str:
    asset_type = ""
    explicit_market = ""
    if isinstance(value, Mapping):
        asset_type = str(value.get("asset_type") or "").strip().lower()
        explicit_market = (
            str(value.get("exchange") or value.get("market") or "").strip().lower()
        )
        value = value.get("symbol") or value.get("code")

    raw = str(value or "").strip().upper()
    market = _normalize_market(explicit_market)
    if explicit_market and not market:
        raise ValueError(f"unknown China security market: {explicit_market}")
    if len(raw) == 8 and raw[:2] in {"SH", "SZ", "BJ"} and raw[2:].isdigit():
        market, code = raw[:2].lower(), raw[2:]
    elif (
        len(raw) == 9
        and raw[:6].isdigit()
        and raw[6:]
        in {
            ".SH",
            ".SZ",
            ".BJ",
        }
    ):
        market, code = raw[7:].lower(), raw[:6]
    elif len(raw) == 6 and raw.isdigit():
        code = raw
        if market:
            pass
        elif code.startswith(("4", "8", "92")):
            market = "bj"
        elif code.startswith(("5", "6", "9")):
            market = "sh"
        elif code.startswith("2"):
            market = "sz"
        elif asset_type == "etf" and code.startswith("1"):
            market = "sz"
        elif code.startswith(("000", "001", "002", "003", "159", "300", "301", "302")):
            market = "sz"
        else:
            raise ValueError(f"unknown China security market: {value}")
    else:
        raise ValueError(f"invalid China security code: {value}")

    prefix = {"sh": "1", "sz": "0", "bj": "2"}[market]
    return f"{prefix}{code}"


def _normalize_market(value: str) -> str:
    aliases = {
        "sh": "sh",
        "sse": "sh",
        "xshg": "sh",
        "1": "sh",
        "sz": "sz",
        "szse": "sz",
        "xshe": "sz",
        "0": "sz",
        "bj": "bj",
        "bse": "bj",
        "xbj": "bj",
        "2": "bj",
    }
    return aliases.get(value, "")


def write_clx_tdx_group(
    symbols: list[object], *, tdx_home: str | Path | None = None
) -> dict[str, object]:
    lines = []
    seen = set()
    for symbol in symbols:
        line = encode_tdx_blk_code(symbol)
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    if not lines:
        raise ValueError("没有匹配结果，通达信旧分组已保留")

    root = Path(tdx_home) if tdx_home is not None else _require_tdx_home()
    target = root / "T0002" / "blocknew" / CLX_TDX_BLK_FILENAME
    temp_path = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with temp_path.open("w", encoding="gbk", newline="") as handle:
            handle.write("".join(f"{line}\r\n" for line in lines))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"导入通达信失败，旧分组已保留：{exc}") from exc

    return {
        "group_name": CLX_TDX_GROUP_DISPLAY_NAME,
        "file_name": CLX_TDX_BLK_FILENAME,
        "written_count": len(lines),
    }


def _require_tdx_home() -> Path:
    from freshquant.bootstrap_config import bootstrap_config

    value = str(bootstrap_config.tdx.home or os.environ.get("TDX_HOME") or "").strip()
    if not value:
        raise RuntimeError("导入通达信失败，旧分组已保留：TDX_HOME not configured")
    return Path(value)
