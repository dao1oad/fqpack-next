# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any

bidata: dict[str, list[Any]] = {"date": [], "data": []}

duandata: dict[str, list[Any]] = {"date": [], "data": []}

higherDuanData: dict[str, list[Any]] = {"date": [], "data": []}

higherHigherDuanData: dict[str, list[Any]] = {"data": [], "date": []}

zsdata: list[Any] = []
zsflag: list[Any] = []

duan_zsdata: list[Any] = []
duan_zsflag: list[Any] = []

higher_duan_zsdata: list[Any] = []
higher_duan_zsflag: list[Any] = []

buy_zs_huila: dict[str, list[Any]] = {
    "idx": [],
    "date": [],
    "data": [],
    "stop_lose_price": [],
    "stop_win_price": [],
    "tag": [],
    "above_ma5": [],
    "above_ma20": [],
}

sell_zs_huila: dict[str, list[Any]] = {
    "idx": [],
    "date": [],
    "data": [],
    "stop_lose_price": [],
    "stop_win_price": [],
    "tag": [],
    "above_ma5": [],
    "above_ma20": [],
}

buy_zs_tupo: dict[str, list[Any]] = {
    "idx": [],
    "date": [],
    "data": [],
    "stop_lose_price": [],
    "stop_win_price": [],
    "tag": [],
    "above_ma5": [],
    "above_ma20": [],
}

sell_zs_tupo: dict[str, list[Any]] = {
    "idx": [],
    "date": [],
    "data": [],
    "stop_lose_price": [],
    "stop_win_price": [],
    "tag": [],
    "above_ma5": [],
    "above_ma20": [],
}

buy_v_reverse: dict[str, list[Any]] = {
    "idx": [],
    "date": [],
    "data": [],
    "stop_lose_price": [],
    "stop_win_price": [],
    "tag": [],
    "above_ma5": [],
    "above_ma20": [],
}

sell_v_reverse: dict[str, list[Any]] = {
    "idx": [],
    "date": [],
    "data": [],
    "stop_lose_price": [],
    "stop_win_price": [],
    "tag": [],
    "above_ma5": [],
    "above_ma20": [],
}

buy_five_v_reverse: dict[str, list[Any]] = {
    "idx": [],
    "date": [],
    "data": [],
    "stop_lose_price": [],
    "stop_win_price": [],
    "tag": [],
    "above_ma5": [],
    "above_ma20": [],
}

sell_five_v_reverse: dict[str, list[Any]] = {
    "idx": [],
    "date": [],
    "data": [],
    "stop_lose_price": [],
    "stop_win_price": [],
    "tag": [],
    "above_ma5": [],
    "above_ma20": [],
}

buy_duan_break: dict[str, list[Any]] = {
    "idx": [],
    "date": [],
    "data": [],
    "stop_lose_price": [],
    "stop_win_price": [],
    "tag": [],
    "above_ma5": [],
    "above_ma20": [],
}

sell_duan_break: dict[str, list[Any]] = {
    "idx": [],
    "date": [],
    "data": [],
    "stop_lose_price": [],
    "stop_win_price": [],
    "tag": [],
    "above_ma5": [],
    "above_ma20": [],
}

fractal: list[Any] = []
