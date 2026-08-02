from __future__ import annotations

import os

import pytest

from freshquant.clx_daily_selection.tdx_export import (
    encode_tdx_blk_code,
    write_clx_tdx_group,
)


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("000001", "0000001"),
        ("159577", "0159577"),
        ("510050", "1510050"),
        ("830799", "2830799"),
        ("bj920001", "2920001"),
        ({"symbol": "160512", "asset_type": "etf"}, "0160512"),
        ({"symbol": "161128", "asset_type": "etf"}, "0161128"),
        ({"symbol": "162711", "asset_type": "etf"}, "0162711"),
        ({"symbol": "163001", "asset_type": "etf"}, "0163001"),
        ({"symbol": "164902", "asset_type": "etf"}, "0164902"),
        ({"symbol": "167002", "asset_type": "etf"}, "0167002"),
        ({"symbol": "160512", "exchange": "SZSE"}, "0160512"),
    ],
)
def test_encode_tdx_blk_code_covers_sh_sz_etf_and_bj(symbol, expected):
    assert encode_tdx_blk_code(symbol) == expected


def test_encode_tdx_blk_code_fails_closed_for_unknown_market():
    with pytest.raises(ValueError, match="unknown China security market"):
        encode_tdx_blk_code("700001")
    with pytest.raises(ValueError, match="unknown China security market"):
        encode_tdx_blk_code({"symbol": "000001", "exchange": "UNKNOWN"})


def test_encode_tdx_blk_code_keeps_bare_lof_fail_closed_without_etf_or_exchange():
    with pytest.raises(ValueError, match="unknown China security market"):
        encode_tdx_blk_code("160512")


def test_write_clx_tdx_group_full_replaces_with_gbk_crlf_and_dedupes(tmp_path):
    result = write_clx_tdx_group(
        ["510050", "000001", "830799", "000001"], tdx_home=tmp_path
    )

    target = tmp_path / "T0002" / "blocknew" / "CLX_18.blk"
    assert target.read_bytes() == (b"1510050\r\n0000001\r\n2830799\r\n")
    assert result == {
        "group_name": "clx_18",
        "file_name": "CLX_18.blk",
        "written_count": 3,
    }


def test_write_clx_tdx_group_atomic_failure_preserves_old_file(monkeypatch, tmp_path):
    target = tmp_path / "T0002" / "blocknew" / "CLX_18.blk"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old-group\r\n")

    def fail_replace(_source, _target):
        raise OSError("replace denied")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(RuntimeError, match="旧分组已保留"):
        write_clx_tdx_group(["000001"], tdx_home=tmp_path)

    assert target.read_bytes() == b"old-group\r\n"
    assert list(target.parent.glob(".CLX_18.blk.*.tmp")) == []


def test_write_clx_tdx_group_rejects_empty_without_touching_old_file(tmp_path):
    target = tmp_path / "T0002" / "blocknew" / "CLX_18.blk"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old-group\r\n")

    with pytest.raises(ValueError, match="旧分组已保留"):
        write_clx_tdx_group([], tdx_home=tmp_path)

    assert target.read_bytes() == b"old-group\r\n"
