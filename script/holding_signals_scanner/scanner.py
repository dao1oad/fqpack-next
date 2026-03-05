#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
持仓标的买卖点扫描脚本

扫描持仓（A股 + ETF）在日线和30分钟线上的买卖点信号。
支持指定日期检测，默认检测最后一个交易日。
使用 fq_clxs 计算缠论信号，包括背驰、拉回、V反等。
"""

import argparse
from datetime import datetime, timedelta, date, time
from typing import List, Dict, Any, Optional

import pandas as pd
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from freshquant.carnation.enum_instrument import InstrumentType
from freshquant.data.astock.holding import get_stock_holding_codes
from freshquant.data.stock import fq_data_stock_fetch_day, fq_data_stock_fetch_min
from freshquant.instrument.general import query_instrument_type, query_instrument_info
from freshquant.quote.etf import queryEtfCandleSticksDay, queryEtfCandleSticksMin
from freshquant.trading.dt import fq_trading_fetch_trade_dates
from fqcopilot import fq_clxs  # type: ignore


class HoldingSignalsScanner:
    """持仓标的买卖点扫描器（支持A股和ETF）"""

    # 信号类型配置
    SIGNAL_TYPES = {
        "buy_divergence": {"model_opt": 8, "name": "MACD背驰买点", "sign": 1},
        "sell_divergence": {"model_opt": 8, "name": "MACD背驰卖点", "sign": -1},
        "buy_pullback": {"model_opt": 9, "name": "拉回买点", "sign": 1},
        "sell_pullback": {"model_opt": 9, "name": "拉回卖点", "sign": -1},
        "buy_vreverse": {"model_opt": 12, "name": "V反买点", "sign": 1},
        "sell_vreverse": {"model_opt": 12, "name": "V反卖点", "sign": -1},
    }

    def __init__(self, target_date: Optional[date] = None):
        """
        初始化扫描器

        Args:
            target_date: 目标检测日期，None 表示检测最后一个交易日
        """
        self.console = Console()
        self.target_date = target_date

    def get_trade_date_range(
        self, trade_days: int = 5000, end_time: time = datetime.min.time()
    ) -> tuple[datetime, datetime]:
        """
        根据交易日数量计算时间范围

        Args:
            trade_days: 需要的交易日数量（默认5000，足以覆盖日线数据）
            end_time: 结束时间（默认00:00:00，分钟线应设为23:59:59.999999）

        Returns:
            (start, end): 时间范围的起止日期
        """
        trade_dates = fq_trading_fetch_trade_dates()

        # 确定截止日期
        if self.target_date:
            cutoff_date = self.target_date
            end = datetime.combine(self.target_date, end_time)
        else:
            cutoff_date = datetime.now().date()
            end = datetime.now()

        # 获取到截止日期为止的交易日
        trade_dates = trade_dates[trade_dates['trade_date'] <= cutoff_date]

        # 取最后 trade_days 个交易日
        trade_dates = trade_dates["trade_date"].tail(trade_days)

        if len(trade_dates) == 0:
            # 如果没有交易日历数据，使用默认范围
            start = end - timedelta(days=trade_days * 2)  # 粗略估计
            return start, end

        start = datetime.combine(trade_dates.iloc[0], datetime.min.time())
        return start, end

    def get_instrument_type(self, code: str) -> InstrumentType:
        """获取标的类型"""
        try:
            # 尝试直接查询
            inst_type = query_instrument_type(code)
            if inst_type:
                return inst_type

            # 如果查询失败，通过代码格式判断
            # ETF 通常是 5 开头（沪市）或 15/16 开头（深市）
            if code.startswith("5") or code.startswith("15") or code.startswith("16"):
                return InstrumentType.ETF_CN

            return InstrumentType.STOCK_CN
        except Exception:
            # 默认为股票
            return InstrumentType.STOCK_CN

    def format_code_for_data_fetch(self, code: str, inst_type: InstrumentType) -> str:
        """格式化代码用于数据获取"""
        if inst_type == InstrumentType.ETF_CN:
            # ETF 需要带市场前缀
            if len(code) == 6:
                # 根据代码判断市场
                if code.startswith("5") or code.startswith("51"):
                    return f"sh{code}"
                else:
                    return f"sz{code}"
            return code
        else:
            # A 股使用原代码
            return code

    def fetch_stock_day_data(self, code: str) -> Optional[pd.DataFrame]:
        """获取 A 股日线数据"""
        try:
            # 日线：5000个交易日
            start, end = self.get_trade_date_range(trade_days=5000)
            return fq_data_stock_fetch_day(code=code, start=start, end=end)
        except Exception as e:
            self.console.print(f"[yellow]获取 {code} 日线数据失败: {e}[/yellow]")
            return None

    def fetch_stock_min30_data(self, code: str) -> Optional[pd.DataFrame]:
        """获取 A 股30分钟数据"""
        try:
            # 30分钟线：5000根K线，每天约8根，需要约625个交易日
            # 取800个交易日作为缓冲（考虑假期和停牌）
            start, end = self.get_trade_date_range(
                trade_days=800, end_time=datetime.max.time()
            )
            return fq_data_stock_fetch_min(
                code=code, frequence="30min", start=start, end=end
            )
        except Exception as e:
            self.console.print(f"[yellow]获取 {code} 30分钟数据失败: {e}[/yellow]")
            return None

    def fetch_etf_day_data(self, code: str) -> Optional[pd.DataFrame]:
        """获取 ETF 日线数据"""
        try:
            # 日线：5000个交易日
            start, end = self.get_trade_date_range(trade_days=5000)
            return queryEtfCandleSticksDay(code=code, start=start, end=end)
        except Exception as e:
            self.console.print(f"[yellow]获取 {code} ETF日线数据失败: {e}[/yellow]")
            return None

    def fetch_etf_min30_data(self, code: str) -> Optional[pd.DataFrame]:
        """获取 ETF 30分钟数据"""
        try:
            # 30分钟线：800个交易日
            start, end = self.get_trade_date_range(
                trade_days=800, end_time=datetime.max.time()
            )
            return queryEtfCandleSticksMin(
                code=code, frequence="30min", start=start, end=end
            )
        except Exception as e:
            self.console.print(f"[yellow]获取 {code} ETF 30分钟数据失败: {e}[/yellow]")
            return None

    def fetch_day_data(self, code: str, inst_type: InstrumentType) -> Optional[pd.DataFrame]:
        """根据标的类型获取日线数据"""
        formatted_code = self.format_code_for_data_fetch(code, inst_type)

        if inst_type == InstrumentType.ETF_CN:
            return self.fetch_etf_day_data(formatted_code)
        else:
            return self.fetch_stock_day_data(formatted_code)

    def fetch_min30_data(self, code: str, inst_type: InstrumentType) -> Optional[pd.DataFrame]:
        """根据标的类型获取30分钟数据"""
        formatted_code = self.format_code_for_data_fetch(code, inst_type)

        if inst_type == InstrumentType.ETF_CN:
            return self.fetch_etf_min30_data(formatted_code)
        else:
            return self.fetch_stock_min30_data(formatted_code)

    def check_signals(
        self, data: pd.DataFrame, signal_type: str, check_bars: int = 1
    ) -> List[Dict[str, Any]]:
        """
        检查指定类型的信号

        Args:
            data: K线数据
            signal_type: 信号类型
            check_bars: 检查最后几根K线（日线=1，30分钟线=8）

        Returns:
            匹配的信号列表
        """
        if data is None or len(data) == 0:
            return []

        highs = data.high.to_list()
        lows = data.low.to_list()
        opens = data.open.to_list()
        closes = data.close.to_list()
        volumes = data.volume.to_list()
        length = len(highs)

        # 获取信号配置
        config = self.SIGNAL_TYPES[signal_type]

        # 计算信号
        signals = fq_clxs(
            length,
            highs,
            lows,
            opens,
            closes,
            volumes,
            wave_opt=1560,
            stretch_opt=0,
            trend_opt=0,
            model_opt=config["model_opt"],
        )

        # 检查最后 check_bars 根K线
        matched_signals = []
        expected_sign = config["sign"]
        start_idx = max(0, length - check_bars)

        for i in range(start_idx, length):
            signal_value = int(signals[i])
            if signal_value == 0:
                continue

            # 检查信号方向是否匹配
            if (signal_value > 0 and expected_sign > 0) or (
                signal_value < 0 and expected_sign < 0
            ):
                # 对于背驰信号，计算中枢数量
                zhongshu_count = None
                if config["model_opt"] == 8:
                    zhongshu_count = abs(signal_value) // 100

                matched_signals.append({
                    "signal_type": config["name"],
                    "signal_value": signal_value,
                    "price": closes[i],
                    "zhongshu_count": zhongshu_count,
                    "datetime": data.index[i],
                })

        return matched_signals

    def scan_holding(self, code: str) -> Dict[str, Any]:
        """扫描单个持仓标的的信号（支持A股和ETF）"""
        # 判断标的类型
        inst_type = self.get_instrument_type(code)

        # 获取标的名称
        inst_info = query_instrument_info(code)
        name = inst_info.get("name", "") if inst_info else ""

        result = {
            "code": code,
            "name": name,
            "inst_type": inst_type,
            "day_signals": [],
            "min30_signals": [],
        }

        # 扫描日线（检查最后1根K线）
        day_data = self.fetch_day_data(code, inst_type)
        if day_data is not None and len(day_data) > 0:
            for signal_type in self.SIGNAL_TYPES:
                signals = self.check_signals(day_data, signal_type, check_bars=1)
                result["day_signals"].extend(signals)

        # 扫描30分钟线（检查最后8根K线，即最后一天）
        min30_data = self.fetch_min30_data(code, inst_type)
        if min30_data is not None and len(min30_data) > 0:
            for signal_type in self.SIGNAL_TYPES:
                signals = self.check_signals(min30_data, signal_type, check_bars=8)
                result["min30_signals"].extend(signals)

        return result

    def scan_all_holdings(self) -> List[Dict[str, Any]]:
        """扫描所有持仓（A股 + ETF）"""
        codes = get_stock_holding_codes()

        if not codes:
            self.console.print("[yellow]没有找到持仓标的[/yellow]")
            return []

        self.console.print(f"[cyan]开始扫描 {len(codes)} 个持仓标的（A股+ETF）...[/cyan]")

        results = []
        stock_count = 0
        etf_count = 0

        for code in codes:
            result = self.scan_holding(code)
            results.append(result)

            if result["inst_type"] == InstrumentType.ETF_CN:
                etf_count += 1
            else:
                stock_count += 1

        self.console.print(
            f"[dim]扫描完成: {stock_count} 只A股, {etf_count} 只ETF[/dim]\n"
        )

        return results

    def display_results(self, results: List[Dict[str, Any]]):
        """显示扫描结果"""
        # 按日线信号数量排序
        results_with_signals = [
            r for r in results if r["day_signals"] or r["min30_signals"]
        ]
        results_with_signals.sort(
            key=lambda x: len(x["day_signals"]) + len(x["min30_signals"]),
            reverse=True,
        )

        if not results_with_signals:
            target_date_str = self.target_date.strftime("%Y-%m-%d") if self.target_date else "最后一个交易日"
            self.console.print(
                Panel(
                    f"[yellow]持仓标的中在 {target_date_str} 没有发现买卖点信号[/yellow]",
                    title="扫描结果",
                    border_style="yellow",
                )
            )
            return

        # 创建结果表格
        target_date_str = f" ({self.target_date.strftime('%Y-%m-%d')})" if self.target_date else ""
        table = Table(
            title=f"持仓标的买卖点扫描结果{target_date_str}",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold magenta",
        )

        table.add_column("代码", style="cyan", width=8)
        table.add_column("名称", style="white", width=10)
        table.add_column("日线信号", style="green", width=36)
        table.add_column("30分钟信号", style="blue", width=36)

        for result in results_with_signals:
            # 代码列
            code = result['code']
            # 名称列
            name = result.get('name', '')

            # 格式化日线信号
            day_signals_text = self._format_signals(result["day_signals"])

            # 格式化30分钟信号
            min30_signals_text = self._format_signals(result["min30_signals"])

            table.add_row(code, name, day_signals_text, min30_signals_text)

        self.console.print(table)

        # 统计信息
        total_stocks = len(results)
        stocks_with_signals = len(results_with_signals)
        total_day_signals = sum(len(r["day_signals"]) for r in results_with_signals)
        total_min30_signals = sum(len(r["min30_signals"]) for r in results_with_signals)

        # 按类型统计
        stock_results = [r for r in results if r["inst_type"] == InstrumentType.STOCK_CN]
        etf_results = [r for r in results if r["inst_type"] == InstrumentType.ETF_CN]

        target_date_str = f"检测日期: {self.target_date.strftime('%Y-%m-%d')}" if self.target_date else "检测日期: 最后一个交易日"

        summary = (
            f"[bold]扫描完成[/bold]\n"
            f"{target_date_str}\n"
            f"扫描标的数: {total_stocks} (A股: {len(stock_results)}, ETF: {len(etf_results)})\n"
            f"有信号的标的: {stocks_with_signals}\n"
            f"日线信号总数: {total_day_signals}\n"
            f"30分钟信号总数: {total_min30_signals}"
        )

        self.console.print(Panel(summary, border_style="cyan"))

    def _format_signals(self, signals: List[Dict[str, Any]]) -> str:
        """格式化信号列表为文本"""
        if not signals:
            return "-"

        lines = []
        for sig in signals:
            parts = [sig["signal_type"]]

            if sig.get("zhongshu_count"):
                parts.append(f"(中枢{sig['zhongshu_count']}个)")

            # 价格统一显示 3 位小数
            parts.append(f"@ {sig['price']:.3f}")

            # 添加时间
            dt = sig["datetime"]
            if hasattr(dt, "hour") and dt.hour > 0:
                # 30分钟线：显示日期+时间
                parts.append(f"[dim]{dt.strftime('%m-%d %H:%M')}[/dim]")
            else:
                # 日线：仅显示日期
                parts.append(f"[dim]{dt.strftime('%m-%d')}[/dim]")

            lines.append(" ".join(parts))

        return "\n".join(lines)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="持仓标的买卖点扫描器（支持A股和ETF）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 扫描最后一个交易日的信号
  python -m script.holding_signals_scanner.scanner

  # 扫描指定日期的信号
  python -m script.holding_signals_scanner.scanner --date 2024-01-15

  # 扫描昨天的信号
  python -m script.holding_signals_scanner.scanner --date yesterday
        """
    )

    parser.add_argument(
        "--date", "-d",
        type=str,
        default=None,
        help="目标检测日期 (格式: YYYY-MM-DD，或使用 'yesterday' 表示昨天)"
    )

    return parser.parse_args()


def parse_date(date_str: Optional[str]) -> Optional[date]:
    """解析日期字符串"""
    if date_str is None:
        return None

    date_str = date_str.strip().lower()

    # 处理特殊关键字
    if date_str == "yesterday":
        return (datetime.now() - timedelta(days=1)).date()

    # 处理标准日期格式
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"无效的日期格式: {date_str}，请使用 YYYY-MM-DD 格式或 'yesterday'"
        )


def main():
    """主函数"""
    args = parse_args()

    # 解析目标日期
    target_date = None
    if args.date:
        target_date = parse_date(args.date)

    # 创建扫描器
    scanner = HoldingSignalsScanner(target_date=target_date)

    # 显示标题
    console = Console()
    target_date_str = f" ({target_date.strftime('%Y-%m-%d')})" if target_date else ""
    console.print(
        Panel(
            f"[bold cyan]持仓标的买卖点扫描器[/bold cyan]\n"
            f"扫描持仓（A股+ETF）在日线和30分钟线上的买卖点信号{target_date_str}",
            border_style="cyan",
        )
    )

    # 执行扫描
    results = scanner.scan_all_holdings()

    # 显示结果
    scanner.display_results(results)


if __name__ == "__main__":
    main()
