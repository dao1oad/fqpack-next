# -*- coding: utf-8 -*-
"""
线性回归通道分析 CLI 命令
"""

import os
import click
import pandas as pd
from datetime import datetime
from typing import Dict
from rich.table import Table
from rich.console import Console
from rich.padding import Padding

from freshquant.KlineDataTool import get_stock_data
from freshquant.config import cfg
from freshquant.pattern.channel import (
    linear_regression_channel,
    channel_comprehensive_signal,
    create_channel_chart,
    dual_linear_regression_channel,
)
from freshquant.instrument.stock import fq_inst_fetch_stock_list
from freshquant.util.code import (
    fq_util_code_append_market_code,
    normalize_to_base_code,
)
from freshquant.analysis.chanlun_analysis import Chanlun
import asyncio


def _display_dual_channel_result(console, code: str, channels: Dict, chart: str, df: pd.DataFrame, chanlun=None) -> None:
    """显示双通道分析结果"""
    channel1 = channels["channel1"]
    channel2 = channels["channel2"]
    comp = channels["comparison"]

    # 创建对比表格
    table = Table(
        show_header=True,
        header_style="bold magenta",
        show_lines=True,
        title=f"{code} 双通道分析",
    )
    table.add_column("指标", style="cyan")
    table.add_column("通道1（历史）", justify="right")
    table.add_column("通道2（当前）", justify="right")

    # 基本信息
    table.add_row("通道状态", _format_status(channel1["is_valid"]), _format_status(channel2["is_valid"]))
    table.add_row("线段方向", _format_direction(channel1["duan_direction"]), _format_direction(channel2["duan_direction"]))
    table.add_row("K线数量", f"{channel1['bar_count']}", f"{channel2['bar_count']}")
    table.add_row("斜率", f"{channel1['slope']:.6f}", f"{channel2['slope']:.6f}")

    # 拟合优度
    table.add_row("拟合优度 R²", f"{channel1['r_squared']:.4f}", f"{channel2['r_squared']:.4f}")
    table.add_row("标准差", f"{channel1['std']:.4f}", f"{channel2['std']:.4f}")

    # 趋势对比
    console.print(Padding(table, (1, 0, 0, 0)))

    # 趋势状态分析
    trend_table = Table(
        show_header=False,
        show_lines=True,
        title="趋势分析",
    )
    trend_table.add_column("指标", style="yellow")
    trend_table.add_column("值", justify="right")

    trend_table.add_row("趋势状态", _format_trend_status(comp["trend_status"]))
    trend_table.add_row("斜率变化", f"{comp['slope_change']:.6f}")
    trend_table.add_row("斜率变化率", f"{comp['slope_change_pct']:.2f}%")

    console.print(Padding(trend_table, (1, 0, 0, 0)))

    # 生成图表
    if chart:
        output_file = chart
    else:
        # 默认保存到 output/日期/channel/ 目录
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")
        os.makedirs(f"output/{date_str}/channel", exist_ok=True)
        output_file = f"output/{date_str}/channel/{code}_dual_channel.html"

    from freshquant.pattern.channel import create_dual_channel_chart
    create_dual_channel_chart(
        df,
        channels,
        chanlun=chanlun,
        title=f"{code} - Dual Channels ({comp['trend_status']})",
        file=output_file,
    )
    console.print(f"[green]图表已生成: {output_file}[/green]")


def _format_status(is_valid: bool) -> str:
    return "[green]有效[/green]" if is_valid else "[red]无效[/red]"


def _format_direction(direction: str) -> str:
    if direction == "up":
        return "[blue]↑ 上升[/blue]"
    elif direction == "down":
        return "[red]↓ 下降[/red]"
    else:
        return direction


def _format_trend_status(status: str) -> str:
    status_map = {
        "加速上涨": "[blue]加速上涨[/blue]",
        "减速上涨": "[cyan]减速上涨[/cyan]",
        "加速下跌": "[red]加速下跌[/red]",
        "减速下跌": "[yellow]减速下跌[/yellow]",
        "转折向下": "[red]⚠ 转折向下[/red]",
        "转折向上": "[green]⚠ 转折向上[/green]",
    }
    return status_map.get(status, status)


def calculate_dynamic_window(df: pd.DataFrame, use_higher_duan: bool = False) -> int:
    """
    基于缠论线段计算动态窗口大小

    找到最后一个线段的起点，计算从该起点到现在的K线数量。

    Parameters
    ----------
    df : pd.DataFrame
        K线数据，必须包含 time_stamp 列
    use_higher_duan : bool
        是否使用高级别线段（默认使用普通线段）

    Returns
    -------
    tuple[int, dict]
        (窗口大小, 调试信息字典)
    """
    # 执行缠论分析
    chanlun = Chanlun().analysis(
        df.time_stamp.to_list(),
        df.open.to_list(),
        df.close.to_list(),
        df.low.to_list(),
        df.high.to_list(),
    )

    # 选择线段数据
    if use_higher_duan and chanlun.higher_duan_data["dt"]:
        duan_dt = chanlun.higher_duan_data["dt"]
        duan_data = chanlun.higher_duan_data["data"]
        duan_type = "高级别线段"
    else:
        duan_dt = chanlun.duan_data["dt"]
        duan_data = chanlun.duan_data["data"]
        duan_type = "普通线段"

    debug_info = {
        "duan_type": duan_type,
        "total_duan": len(duan_dt) if duan_dt else 0,
        "total_bars": len(df),
    }

    # 如果没有线段数据，使用默认窗口
    if not duan_dt:
        debug_info["reason"] = "未找到线段，使用默认窗口 50"
        return 50, debug_info

    # 获取最后一个线段的时间戳和价格
    last_duan_timestamp = duan_dt[-1]
    last_duan_price = duan_data[-1]

    # 在 df 中找到该时间戳对应的索引位置
    df_reset = df.reset_index(drop=True)
    last_duan_idx = df_reset[df_reset["time_stamp"] == last_duan_timestamp].index

    if len(last_duan_idx) == 0:
        debug_info["reason"] = "无法定位线段在数据中的位置，使用默认窗口 50"
        return 50, debug_info

    last_duan_idx = last_duan_idx[0]

    # 窗口大小 = 当前K线数量 - 线段起点位置
    window = len(df) - last_duan_idx

    # 最小窗口为 10
    window = max(window, 10)

    debug_info["last_duan_idx"] = int(last_duan_idx)
    debug_info["last_duan_price"] = float(last_duan_price)
    debug_info["calculated_window"] = window
    debug_info["reason"] = f"从最后一个线段起点(索引{last_duan_idx})到现在的K线数量"

    return window, debug_info


@click.group(name="channel")
def channel_command_group():
    """线性回归标准差通道分析"""
    pass


@channel_command_group.command(name="analyze")
@click.option("-c", "--code", type=str, required=True, help="股票代码，如 600000 或 sh600000")
@click.option("-p", "--period", type=str, default="1d", help="K线周期，如 1m/5m/15m/30m/60m/1d")
@click.option("-w", "--window", type=int, default=50, help="回溯窗口大小")
@click.option("-m", "--multiplier", type=float, default=2.0, help="标准差倍数")
@click.option("--min-r2", type=float, default=0.3, help="最小拟合优度")
@click.option("--chart", type=str, default=None, help="图表输出文件路径")
@click.option("--auto-window", is_flag=True, help="自动使用缠论线段计算窗口大小")
@click.option("--higher-duan", is_flag=True, help="使用高级别线段计算窗口（需配合 --auto-window）")
@click.option("--dual-channel/--no-dual-channel", default=True, help="使用双通道模式（基于最后两个线段）")
def channel_analyze_command(
    code: str,
    period: str,
    window: int,
    multiplier: float,
    min_r2: float,
    chart: str,
    auto_window: bool,
    higher_duan: bool,
    dual_channel: bool,
):
    """分析单只股票的线性回归通道"""
    console = Console()

    # 标准化股票代码：先去除已有前缀，再自动添加市场前缀
    base_code = normalize_to_base_code(code)
    code = fq_util_code_append_market_code(base_code)

    # 获取数据（endDate=None 获取最新数据）
    df = get_stock_data(code, period, None)

    if df is None or len(df) < 10:
        console.print(f"[red]数据不足[/red]")
        return

    # 添加时间字符串
    df["time_str"] = df["datetime"].apply(lambda dt: dt.strftime(cfg.DT_FORMAT_FULL))

    # ========== 双通道模式 ==========
    if dual_channel:
        # 执行缠论分析
        chanlun = Chanlun().analysis(
            df.time_stamp.to_list(),
            df.open.to_list(),
            df.close.to_list(),
            df.low.to_list(),
            df.high.to_list(),
        )

        # 计算双通道
        channels = dual_linear_regression_channel(
            df,
            chanlun,
            price_source="close",
            std_multiplier=multiplier,
            min_r_squared=min_r2,
        )

        # 检查是否有错误
        if "error" in channels.get("comparison", {}):
            console.print(f"[red]{channels['comparison']['error']}[/red]")
            return

        # 显示双通道结果
        _display_dual_channel_result(console, code, channels, chart, df, chanlun)
        return

    # ========== 单通道模式 ==========
    # 计算窗口大小
    if auto_window:
        actual_window, debug_info = calculate_dynamic_window(df, use_higher_duan=higher_duan)
        # 使用动态计算的结果（-w 参数被忽略，除非用户明确指定大于默认值）
        # 如果用户明确指定了 -w 50 以外的值，则取两者较大值
        if window != 50:  # 用户非默认指定
            actual_window = max(actual_window, window)

        console.print(f"[cyan]动态窗口计算:[/cyan]")
        console.print(f"  线段类型: {debug_info['duan_type']}")
        console.print(f"  总线段数: {debug_info['total_duan']}")
        console.print(f"  最后线段: 索引={debug_info.get('last_duan_idx', 'N/A')}, 价格={debug_info.get('last_duan_price', 'N/A'):.2f}")
        console.print(f"  计算窗口: {debug_info.get('calculated_window', 'N/A')}")
        console.print(f"  最终窗口: {actual_window}")
    else:
        actual_window = window

    if len(df) < actual_window:
        console.print(f"[red]数据不足: {len(df)} < {actual_window}[/red]")
        return

    # 计算通道
    channel = linear_regression_channel(
        df,
        period=actual_window,
        price_source="close",
        std_multiplier=multiplier,
        min_r_squared=min_r2,
    )

    # 创建结果表格
    table = Table(
        show_header=True,
        header_style="bold magenta",
        show_lines=True,
        title=f"{code} 线性回归通道分析",
    )
    table.add_column("指标", style="cyan")
    table.add_column("值", justify="right")

    if channel["is_valid"]:
        table.add_row("通道状态", "[green]有效[/green]")
        table.add_row("窗口大小", f"{actual_window}")
        table.add_row("斜率", f"{channel['slope']:.6f}")
        table.add_row("拟合优度 R²", f"{channel['r_squared']:.4f}")
        table.add_row("标准差", f"{channel['std']:.4f}")
        table.add_row("通道宽度", f"{channel['std'] * 2 * multiplier:.4f}")

        # 当前价格位置
        current_price = df["close"].iloc[-1]
        upper = channel["upper"][-1]
        lower = channel["lower"][-1]
        position = (current_price - lower) / (upper - lower) * 100

        table.add_row("当前价格", f"{current_price:.2f}")
        table.add_row("上轨", f"{upper:.2f}")
        table.add_row("下轨", f"{lower:.2f}")
        table.add_row("价格位置", f"{position:.1f}%")

        # 综合信号
        signals = channel_comprehensive_signal(df, channel)

        table.add_row("突破状态", signals["breakout"])
        table.add_row("支撑状态", signals["support"])
        table.add_row("阻力状态", signals["resistance"])
        table.add_row("交易信号", signals["trading_signal"])
        table.add_row("原因", signals["trading_reason"])

        console.print(Padding(table, (1, 0, 0, 0)))

        # 生成图表
        if chart or channel["is_valid"]:
            if chart:
                output_file = chart
            else:
                # 默认保存到 output/日期/channel/ 目录
                from datetime import datetime
                date_str = datetime.now().strftime("%Y-%m-%d")
                os.makedirs(f"output/{date_str}/channel", exist_ok=True)
                output_file = f"output/{date_str}/channel/{code}_channel.html"

            create_channel_chart(
                df,
                channel,
                title=f"{code} - Linear Regression Channel (Window: {actual_window})",
                file=output_file,
            )
            console.print(f"[green]图表已生成: {output_file}[/green]")
    else:
        table.add_row("通道状态", "[red]无效[/red]")
        table.add_row("原因", channel.get("reason", "Unknown"))
        console.print(Padding(table, (1, 0, 0, 0)))


@channel_command_group.command(name="scan")
@click.option("-c", "--code", type=str, default=None, help="单只股票代码（可选）")
@click.option("-p", "--period", type=str, default="1d", help="K线周期")
@click.option("-w", "--window", type=int, default=50, help="回溯窗口大小")
@click.option("--min-r2", type=float, default=0.3, help="最小拟合优度")
@click.option("--limit", type=int, default=999999, help="扫描数量限制")
@click.option("--signal", type=str, multiple=True, help="信号筛选（可多选）：strong_buy/strong_sell/buy/sell/watch_buy/watch_sell/hold")
@click.option("--chart-dir", type=str, default="output", help="图表保存目录（默认为 output，按日期自动创建子目录）")
def channel_scan_command(code: str, period: str, window: int, min_r2: float, limit: int, signal: tuple, chart_dir: str):
    """批量扫描股票，筛选有效通道并按信号过滤"""
    console = Console()
    import os

    # 信号映射中文显示
    signal_names = {
        "strong_buy": "强买入",
        "strong_sell": "强卖出",
        "buy": "买入",
        "sell": "卖出",
        "watch_buy": "观察买入",
        "watch_sell": "观察卖出",
        "hold": "持有",
    }

    async def scan():
        if code:
            # 单只股票
            stocks = [{"code": code, "name": code}]
        else:
            # 获取股票列表
            stock_list = fq_inst_fetch_stock_list()
            # 过滤 ST 股
            stocks = [s for s in stock_list if "ST" not in s.get("name", "")]
            stocks = stocks[:limit]

        results = []
        filtered_results = []

        for i, stock in enumerate(stocks):
            stock_code = stock["code"]
            stock_name = stock.get("name", stock_code)

            # 标准化股票代码：先去除已有前缀，再自动添加市场前缀
            base_code = normalize_to_base_code(stock_code)
            stock_code = fq_util_code_append_market_code(base_code)

            try:
                df = get_stock_data(stock_code, period, None)

                if df is None or len(df) < window:
                    continue

                # 执行缠论分析
                chanlun = Chanlun().analysis(
                    df.time_stamp.to_list(),
                    df.open.to_list(),
                    df.close.to_list(),
                    df.low.to_list(),
                    df.high.to_list(),
                )

                # 计算双通道
                channels = dual_linear_regression_channel(
                    df,
                    chanlun,
                    price_source="close",
                    std_multiplier=2.0,
                    min_r_squared=min_r2,
                )

                # 检查是否有错误
                if "error" in channels.get("comparison", {}):
                    continue

                channel2 = channels["channel2"]

                if channel2["is_valid"]:
                    # 计算综合信号（基于通道2）
                    from freshquant.pattern.channel import channel_comprehensive_signal
                    sig_result = channel_comprehensive_signal(df, channel2)

                    current_price = df["close"].iloc[-1]
                    position = (
                        (current_price - channel2["lower"][-1])
                        / (channel2["upper"][-1] - channel2["lower"][-1])
                        * 100
                    )

                    result = {
                        "code": stock_code,
                        "name": stock_name,
                        "slope": channel2["slope"],
                        "r_squared": channel2["r_squared"],
                        "width": channel2["std"] * 2,
                        "price_position": position,
                        "trading_signal": sig_result["trading_signal"],
                        "trading_reason": sig_result["trading_reason"],
                        "df": df,  # 保存 df 用于后续生成图表
                        "channels": channels,  # 保存 channels 用于后续生成图表
                        "chanlun": chanlun,  # 保存 chanlun 用于后续生成图表
                    }
                    results.append(result)

                    # 如果指定了信号筛选，检查是否符合
                    if signal:
                        if sig_result["trading_signal"] in signal:
                            filtered_results.append(result)
                    else:
                        # 未指定信号，所有有效通道都保留
                        filtered_results.append(result)

                # 进度显示
                if (i + 1) % 10 == 0:
                    console.print(f"已处理: {i + 1}/{len(stocks)}")

            except Exception as e:
                console.print(f"[red]{stock_code} {stock_name} 失败: {e}[/red]")
                continue

        # 排序输出
        display_results = filtered_results if signal else results

        if display_results:
            display_results.sort(key=lambda x: x["r_squared"], reverse=True)

            # 构建标题
            if signal:
                signal_text = " + ".join([signal_names.get(s, s) for s in signal])
                title = f"通道筛选结果（{signal_text}）共 {len(display_results)} 只"
            else:
                title = f"通道筛选结果（共 {len(display_results)} 只）"

            table = Table(
                show_header=True,
                header_style="bold magenta",
                show_lines=True,
                title=title,
            )
            table.add_column("代码", justify="left")
            table.add_column("名称", justify="left")
            table.add_column("斜率", justify="right")
            table.add_column("R²", justify="right")
            table.add_column("通道宽度", justify="right")
            table.add_column("价格位置%", justify="right")
            table.add_column("信号", justify="left")

            for r in display_results:
                # 信号颜色
                sig = r["trading_signal"]
                sig_display = signal_names.get(sig, sig)
                if sig in ["strong_buy", "buy"]:
                    sig_display = f"[green]{sig_display}[/green]"
                elif sig in ["strong_sell", "sell"]:
                    sig_display = f"[red]{sig_display}[/red]"
                elif sig in ["watch_buy", "watch_sell"]:
                    sig_display = f"[yellow]{sig_display}[/yellow]"

                table.add_row(
                    r["code"],
                    r["name"],
                    f"{r['slope']:.6f}",
                    f"{r['r_squared']:.4f}",
                    f"{r['width']:.2f}",
                    f"{r['price_position']:.1f}",
                    sig_display,
                )

            console.print(Padding(table, (1, 0, 0, 0)))

            # 生成图表
            if chart_dir:
                # 添加日期子目录
                from datetime import datetime
                date_str = datetime.now().strftime("%Y-%m-%d")
                chart_dir_with_date = os.path.join(chart_dir, date_str, "channel")
                os.makedirs(chart_dir_with_date, exist_ok=True)

                from freshquant.pattern.channel import create_dual_channel_chart
                comp = channels["comparison"]

                with console.status("[bold cyan]生成图表...") as status:
                    for i, r in enumerate(display_results):
                        df_chart = r["df"].copy()
                        df_chart["time_str"] = df_chart["datetime"].apply(
                            lambda dt: dt.strftime(cfg.DT_FORMAT_FULL)
                        )

                        chart_file = os.path.join(chart_dir_with_date, f"{r['code']}_dual_channel.html")
                        create_dual_channel_chart(
                            df_chart,
                            r["channels"],
                            chanlun=r["chanlun"],
                            title=f"{r['code']} - Dual Channels ({comp['trend_status']})",
                            file=chart_file,
                        )
                        status.update(f"生成图表: {i + 1}/{len(display_results)}")

                console.print(f"[green]图表已保存到: {chart_dir_with_date}[/green]")

        else:
            if signal:
                signal_text = " + ".join([signal_names.get(s, s) for s in signal])
                console.print(f"[yellow]未找到符合 [{signal_text}] 信号的有效通道[/yellow]")
            else:
                console.print("[yellow]未找到有效通道[/yellow]")

    asyncio.run(scan())
