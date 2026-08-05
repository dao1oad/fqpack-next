from __future__ import annotations

import os
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import uuid4

CLX_TDX_GROUP_DISPLAY_NAME = "clx_18"
CLX_TDX_BLOCK_KEY = "CLX_18"
CLX_TDX_BLK_FILENAME = f"{CLX_TDX_BLOCK_KEY}.blk"

CLX_15_30_TDX_GROUP_DISPLAY_NAME = "clx_15_30"
CLX_15_30_TDX_BLOCK_KEY = "CLX_15_30"
CLX_15_30_TDX_BLK_FILENAME = f"{CLX_15_30_TDX_BLOCK_KEY}.blk"

# consumer 的 fullcalc 回调来自线程池，读-合并-重写必须串行化
_TDX_BLK_WRITE_LOCK = threading.Lock()


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
    with _TDX_BLK_WRITE_LOCK:
        _atomic_write_blk(lines, target)

    return {
        "group_name": CLX_TDX_GROUP_DISPLAY_NAME,
        "file_name": CLX_TDX_BLK_FILENAME,
        "written_count": len(lines),
    }


def read_tdx_blk_lines(
    tdx_home: str | Path | None = None,
    filename: str = CLX_15_30_TDX_BLK_FILENAME,
) -> list[str]:
    """Read an existing TDX .blk group as normalized 7-char lines (order preserved, dedup)."""
    root = Path(tdx_home) if tdx_home is not None else _require_tdx_home()
    target = root / "T0002" / "blocknew" / filename
    if not target.exists():
        return []

    text = target.read_bytes().decode("gbk", errors="ignore")
    lines = []
    seen = set()
    for raw in text.splitlines():
        line = str(raw).strip().upper()
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return lines


def append_tdx_group_members(
    symbols: Sequence[object],
    *,
    tdx_home: str | Path | None = None,
    block_key: str = CLX_15_30_TDX_BLOCK_KEY,
    display_name: str = CLX_15_30_TDX_GROUP_DISPLAY_NAME,
) -> dict[str, object]:
    """去重追加成员到通达信分组，复用编码与原子写实现。

    - 以编码后的 7 字符行直接去重（不解码回 6 位，避免 LOF 等裸 6 位歧义）。
    - 无新增成员时为 no-op，不抛错、不触碰旧文件。
    """
    filename = f"{block_key}.blk"
    lines = list(read_tdx_blk_lines(tdx_home=tdx_home, filename=filename))
    seen = set(lines)

    appended_count = 0
    for symbol in symbols or []:
        line = encode_tdx_blk_code(symbol)
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
        appended_count += 1

    result = {
        "group_name": display_name,
        "file_name": filename,
        "appended_count": appended_count,
        "written_count": len(lines),
    }
    if appended_count == 0:
        return result

    root = Path(tdx_home) if tdx_home is not None else _require_tdx_home()
    target = root / "T0002" / "blocknew" / filename
    with _TDX_BLK_WRITE_LOCK:
        _atomic_write_blk(lines, target)
    return result


def _atomic_write_blk(lines: list[str], target: Path) -> None:
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


def _require_tdx_home() -> Path:
    from freshquant.bootstrap_config import bootstrap_config

    value = str(bootstrap_config.tdx.home or os.environ.get("TDX_HOME") or "").strip()
    if not value:
        raise RuntimeError("导入通达信失败，旧分组已保留：TDX_HOME not configured")
    return Path(value)
