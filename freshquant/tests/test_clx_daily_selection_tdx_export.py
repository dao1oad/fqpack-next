from __future__ import annotations

import os

import pytest

from freshquant.clx_daily_selection.tdx_export import (
    BLOCKNEW_CFG_GROUP_SIZE,
    BLOCKNEW_CFG_NAME,
    CLX_15_30_TDX_BLK_FILENAME,
    append_tdx_group_members,
    encode_tdx_blk_code,
    ensure_tdx_group_registered,
    read_tdx_blk_lines,
    write_clx_tdx_group,
)


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("000001", "0000001"),
        ("200001", "0200001"),
        ("900901", "1900901"),
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


def test_read_tdx_blk_lines_returns_normalized_dedup_lines(tmp_path):
    target = tmp_path / "T0002" / "blocknew" / CLX_15_30_TDX_BLK_FILENAME
    target.parent.mkdir(parents=True)
    target.write_bytes("1510050\r\n0000001\r\n1510050\r\n0000001\r\n".encode("gbk"))

    assert read_tdx_blk_lines(tdx_home=tmp_path) == ["1510050", "0000001"]


def test_read_tdx_blk_lines_missing_file_returns_empty(tmp_path):
    assert read_tdx_blk_lines(tdx_home=tmp_path) == []


def test_append_tdx_group_members_appends_dedup_preserves_order(tmp_path):
    target = tmp_path / "T0002" / "blocknew" / CLX_15_30_TDX_BLK_FILENAME
    target.parent.mkdir(parents=True)
    target.write_bytes("1510050\r\n".encode("gbk"))

    result = append_tdx_group_members(
        ["sh600000", "000001", "sh600000", {"symbol": "160512", "asset_type": "etf"}],
        tdx_home=tmp_path,
    )

    assert result == {
        "group_name": "clx_15_30",
        "file_name": "CLX_15_30.blk",
        "appended_count": 3,
        "written_count": 4,
    }
    assert target.read_bytes() == b"1510050\r\n1600000\r\n0000001\r\n0160512\r\n"


def test_append_tdx_group_members_no_new_members_is_noop(tmp_path):
    target = tmp_path / "T0002" / "blocknew" / CLX_15_30_TDX_BLK_FILENAME
    target.parent.mkdir(parents=True)
    target.write_bytes("1510050\r\n".encode("gbk"))

    result = append_tdx_group_members(["sh510050"], tdx_home=tmp_path)

    assert result == {
        "group_name": "clx_15_30",
        "file_name": "CLX_15_30.blk",
        "appended_count": 0,
        "written_count": 1,
    }
    assert target.read_bytes() == b"1510050\r\n"


def test_append_tdx_group_members_atomic_failure_preserves_old(monkeypatch, tmp_path):
    target = tmp_path / "T0002" / "blocknew" / CLX_15_30_TDX_BLK_FILENAME
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old-group\r\n")

    def fail_replace(_source, _target):
        raise OSError("replace denied")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(RuntimeError, match="旧分组已保留"):
        append_tdx_group_members(["sh600000"], tdx_home=tmp_path)

    assert target.read_bytes() == b"old-group\r\n"
    assert list(target.parent.glob(".CLX_15_30.blk.*.tmp")) == []


def test_append_tdx_group_members_supports_custom_block_key(tmp_path):
    result = append_tdx_group_members(
        ["sh510050"],
        tdx_home=tmp_path,
        block_key="CUSTOM",
        display_name="custom",
    )

    target = tmp_path / "T0002" / "blocknew" / "CUSTOM.blk"
    assert target.read_bytes() == b"1510050\r\n"
    assert result == {
        "group_name": "custom",
        "file_name": "CUSTOM.blk",
        "appended_count": 1,
        "written_count": 1,
    }


def _seed_blocknew_cfg(tmp_path, groups=("clx_18", "CLX_18")):
    cfg = tmp_path / "T0002" / "blocknew" / BLOCKNEW_CFG_NAME
    cfg.parent.mkdir(parents=True, exist_ok=True)
    name1, name2 = groups
    # 真实格式：名称1=50B + 名称2=70B
    name1_bytes = name1.encode("gbk")
    name2_bytes = name2.encode("gbk")
    data = (
        name1_bytes
        + b"\x00" * (50 - len(name1_bytes))
        + name2_bytes
        + b"\x00" * (BLOCKNEW_CFG_GROUP_SIZE - 50 - len(name2_bytes))
    )
    cfg.write_bytes(data)
    return cfg


def test_ensure_tdx_group_registered_adds_standard_120b_group(tmp_path):
    cfg = _seed_blocknew_cfg(tmp_path)

    changed = ensure_tdx_group_registered("CLX_15_30", "clx_15_30", tdx_home=tmp_path)

    assert changed is True
    data = cfg.read_bytes()
    assert len(data) == 2 * BLOCKNEW_CFG_GROUP_SIZE
    # 第二组：名称1=clx_15_30(50B)，名称2=CLX_15_30(70B)
    name1 = data[120:170].split(b"\x00", 1)[0].decode("gbk")
    name2 = data[170:240].split(b"\x00", 1)[0].decode("gbk")
    assert name1 == "clx_15_30"
    assert name2 == "CLX_15_30"


def test_ensure_tdx_group_registered_is_idempotent(tmp_path):
    cfg = _seed_blocknew_cfg(tmp_path)
    assert (
        ensure_tdx_group_registered("CLX_15_30", "clx_15_30", tdx_home=tmp_path) is True
    )
    assert (
        ensure_tdx_group_registered("CLX_15_30", "clx_15_30", tdx_home=tmp_path)
        is False
    )
    assert len(cfg.read_bytes()) == 2 * BLOCKNEW_CFG_GROUP_SIZE


def test_ensure_tdx_group_registered_missing_cfg_is_noop(tmp_path):
    assert (
        ensure_tdx_group_registered("CLX_15_30", "clx_15_30", tdx_home=tmp_path)
        is False
    )


def test_append_tdx_group_members_registers_group_when_cfg_present(tmp_path):
    cfg = _seed_blocknew_cfg(tmp_path)

    append_tdx_group_members(["sh600000"], tdx_home=tmp_path)

    data = cfg.read_bytes()
    name1 = data[120:170].split(b"\x00", 1)[0].decode("gbk")
    name2 = data[170:240].split(b"\x00", 1)[0].decode("gbk")
    assert name1 == "clx_15_30"
    assert name2 == "CLX_15_30"
