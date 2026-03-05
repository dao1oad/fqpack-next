# -*- coding: utf-8 -*-
"""
线性回归通道 - 可视化模块

使用 pyecharts 生成交互式 HTML 图表。
"""

from typing import Dict
import pandas as pd
import numpy as np
import os
from pyecharts import options as opts
from pyecharts.charts import Grid, Kline, Line, Bar, Scatter


def _calculate_macd(df: pd.DataFrame, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9):
    """
    计算 MACD 指标

    Returns
    -------
    Dict with keys: dif, dea, macd
    """
    close = df["close"].values

    # 计算 EMA
    def ema(data, period):
        return pd.Series(data).ewm(span=period, adjust=False).mean().values

    ema_fast = ema(close, fast_period)
    ema_slow = ema(close, slow_period)

    # DIF = 快线 - 慢线
    dif = ema_fast - ema_slow

    # DEA = DIF 的 EMA
    dea = ema(dif, signal_period)

    # MACD = 2 * (DIF - DEA)
    macd = 2 * (dif - dea)

    return {
        "dif": dif,
        "dea": dea,
        "macd": macd,
    }


def create_channel_chart(
    df: pd.DataFrame,
    channel: Dict,
    title: str = "Linear Regression Channel",
    file: str = "channel_chart.html",
) -> None:
    """
    使用 pyecharts 创建通道图表（交互式 HTML）

    Parameters
    ----------
    df : pd.DataFrame
        K线数据，必须包含 'time_str' 列
    channel : Dict
        通道计算结果
    title : str
        图表标题
    file : str
        输出 HTML 文件路径
    """
    # 准备数据
    data = df.iloc[-len(channel["upper"]) :]

    # K线数据
    kline_data = data[["open", "close", "low", "high"]].values.tolist()

    # 通道线数据
    times = data["time_str"].tolist()

    # K线（先创建，后续叠加其他线）
    kline = (
        Kline(init_opts=opts.InitOpts(width="100%", height="100vh", page_title=title))
        .add_xaxis(times)
        .add_yaxis(
            "价格",
            kline_data,
            itemstyle_opts=opts.ItemStyleOpts(color="#ef5350", color0="#26a69a"),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title=title,
                subtitle=f"斜率: {channel['slope']:.6f} | R²: {channel['r_squared']:.3f} | 通道宽: {channel['std'] * 2:.2f}",
                pos_left="10px",
                pos_top="10px",
                title_textstyle_opts=opts.TextStyleOpts(font_size=16, font_weight="bold"),
                subtitle_textstyle_opts=opts.TextStyleOpts(font_size=12),
            ),
            legend_opts=opts.LegendOpts(
                pos_left="10px",
                pos_top="60px",
                orient="horizontal",
            ),
            xaxis_opts=opts.AxisOpts(is_scale=True),
            yaxis_opts=opts.AxisOpts(
                is_scale=True,
                splitarea_opts=opts.SplitAreaOpts(
                    is_show=True, areastyle_opts=opts.AreaStyleOpts(opacity=1)
                ),
            ),
            datazoom_opts=[
                opts.DataZoomOpts(
                    type_="inside",
                    xaxis_index=[0, 1],  # 联动主图和MACD子图
                )
            ],
            tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="cross"),
        )
    )

    # 下轨
    lower_line = (
        Line()
        .add_xaxis(times)
        .add_yaxis(
            "下轨",
            channel["lower"].tolist(),
            is_smooth=True,
            color="#00FF00",
            linestyle_opts=opts.LineStyleOpts(width=2, type_="dashed"),
            label_opts=opts.LabelOpts(is_show=False),
        )
    )

    # 中轨
    center_line = (
        Line()
        .add_xaxis(times)
        .add_yaxis(
            "中轨",
            channel["center"].tolist(),
            is_smooth=True,
            color="#808080",
            linestyle_opts=opts.LineStyleOpts(width=1, type_="dotted"),
            label_opts=opts.LabelOpts(is_show=False),
        )
    )

    # 上轨
    upper_line = (
        Line()
        .add_xaxis(times)
        .add_yaxis(
            "上轨",
            channel["upper"].tolist(),
            is_smooth=True,
            color="#FF0000",
            linestyle_opts=opts.LineStyleOpts(width=2, type_="dashed"),
            label_opts=opts.LabelOpts(is_show=False),
        )
    )

    # 叠加顺序：下轨 -> 中轨 -> 上轨
    overlap = kline.overlap(lower_line).overlap(center_line).overlap(upper_line)

    # ========== MACD 子图 ==========
    macd_data = _calculate_macd(data)

    # MACD 柱状图（零轴上方红色，下方绿色）
    # 将正值和负值分成两个系列以设置不同颜色
    macd_values = macd_data["macd"].tolist()
    macd_positive = [v if v >= 0 else 0 for v in macd_values]
    macd_negative = [v if v < 0 else 0 for v in macd_values]

    macd_bar_pos = (
        Bar()
        .add_xaxis(times)
        .add_yaxis(
            "MACD正",
            macd_positive,
            stack="MACD",
            itemstyle_opts=opts.ItemStyleOpts(color="#ef5350"),
            label_opts=opts.LabelOpts(is_show=False),
        )
    )

    macd_bar_neg = (
        Bar()
        .add_xaxis(times)
        .add_yaxis(
            "MACD负",
            macd_negative,
            stack="MACD",
            itemstyle_opts=opts.ItemStyleOpts(color="#26a69a"),
            label_opts=opts.LabelOpts(is_show=False),
        )
    )

    # DIF 线
    dif_line = (
        Line()
        .add_xaxis(times)
        .add_yaxis(
            "DIF",
            macd_data["dif"].tolist(),
            color="#FF9800",
            is_smooth=True,
            label_opts=opts.LabelOpts(is_show=False),
        )
    )

    # DEA 线
    dea_line = (
        Line()
        .add_xaxis(times)
        .add_yaxis(
            "DEA",
            macd_data["dea"].tolist(),
            color="#2196F3",
            is_smooth=True,
            label_opts=opts.LabelOpts(is_show=False),
        )
    )

    # MACD 子图叠加
    macd_overlap = macd_bar_pos.overlap(macd_bar_neg).overlap(dif_line).overlap(dea_line)

    # 使用 Grid 布局：主图 + MACD 子图
    grid = Grid(init_opts=opts.InitOpts(width="100%", height="100vh"))
    grid.add(
        overlap,
        grid_opts=opts.GridOpts(pos_left="1%", pos_right="1%", pos_top="10%", pos_bottom="35%"),
    )
    grid.add(
        macd_overlap,
        grid_opts=opts.GridOpts(pos_left="1%", pos_right="1%", pos_top="70%", pos_bottom="5%"),
    )

    # 确保输出目录存在
    output_dir = os.path.dirname(file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # 渲染
    grid.render(file)

    # 添加全屏样式
    with open(file, "r", encoding="utf-8") as f:
        html_content = f.read()

    # 添加全屏样式
    full_screen_style = """
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body, html { width: 100%; height: 100%; overflow: hidden; background: #fff; }
    </style>
    """
    html_content = html_content.replace("</head>", full_screen_style + "</head>")

    with open(file, "w", encoding="utf-8") as f:
        f.write(html_content)


def create_dual_channel_chart(
    df: pd.DataFrame,
    channels: Dict,
    chanlun=None,
    title: str = "Dual Linear Regression Channels",
    file: str = "dual_channel_chart.html",
) -> None:
    """
    创建双通道图表（历史通道 + 当前通道）

    Parameters
    ----------
    df : pd.DataFrame
        K线数据
    channels : Dict
        包含 channel1 和 channel2 的字典
    title : str
        图表标题
    file : str
        输出文件路径
    """
    channel1 = channels["channel1"]
    channel2 = channels["channel2"]
    comparison = channels["comparison"]

    # 准备数据 - 使用通道1的数据范围（更长）
    start_idx = channel1["start_idx"]
    data = df.iloc[start_idx:].copy()

    kline_data = data[["open", "close", "low", "high"]].values.tolist()
    times = data["time_str"].tolist()

    # K线
    kline = (
        Kline(init_opts=opts.InitOpts(width="100%", height="100vh", page_title=title))
        .add_xaxis(times)
        .add_yaxis(
            "价格",
            kline_data,
            itemstyle_opts=opts.ItemStyleOpts(color="#ef5350", color0="#26a69a"),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title=title,
                subtitle=f"通道1斜率: {comparison['channel1_slope']:.6f} | 通道2斜率: {comparison['channel2_slope']:.6f} | {comparison['trend_status']}",
                pos_left="10px",
                pos_top="10px",
                title_textstyle_opts=opts.TextStyleOpts(font_size=16, font_weight="bold"),
                subtitle_textstyle_opts=opts.TextStyleOpts(font_size=12),
            ),
            legend_opts=opts.LegendOpts(
                pos_left="10px",
                pos_top="60px",
                orient="horizontal",
            ),
            xaxis_opts=opts.AxisOpts(is_scale=True),
            yaxis_opts=opts.AxisOpts(
                is_scale=True,
                splitarea_opts=opts.SplitAreaOpts(
                    is_show=True, areastyle_opts=opts.AreaStyleOpts(opacity=1)
                ),
            ),
            datazoom_opts=[
                opts.DataZoomOpts(
                    type_="inside",
                    xaxis_index=[0, 1],  # 联动主图和MACD子图
                )
            ],
            tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="cross"),
        )
    )

    # 通道1（历史） - 蓝色虚线，较宽
    # 只在通道1的数据范围内显示
    channel1_end_relative = channel1["end_idx"] - start_idx
    x1 = np.arange(channel1_end_relative + 1)
    y1_fit = channel1["slope"] * x1 + channel1["intercept"]
    upper1 = y1_fit + channel1["std"] * 2
    lower1 = y1_fit - channel1["std"] * 2

    # 前面用 NaN 填充（通道1只在其范围内显示）
    channel1_nan_padding = [np.nan] * (len(data) - len(upper1))

    channel1_upper = (
        Line()
        .add_xaxis(times)
        .add_yaxis(
            f"通道1上轨({channel1['duan_direction']})",
            upper1.tolist() + channel1_nan_padding,
            is_smooth=True,
            color="#2196F3",
            linestyle_opts=opts.LineStyleOpts(width=3, type_="dashed"),
            label_opts=opts.LabelOpts(is_show=False),
        )
    )

    channel1_lower = (
        Line()
        .add_xaxis(times)
        .add_yaxis(
            f"通道1下轨({channel1['duan_direction']})",
            lower1.tolist() + channel1_nan_padding,
            is_smooth=True,
            color="#2196F3",
            linestyle_opts=opts.LineStyleOpts(width=3, type_="dashed"),
            label_opts=opts.LabelOpts(is_show=False),
        )
    )

    # 通道1中轨
    channel1_center = (
        Line()
        .add_xaxis(times)
        .add_yaxis(
            f"通道1中轨",
            y1_fit.tolist() + channel1_nan_padding,
            is_smooth=True,
            color="#2196F3",
            linestyle_opts=opts.LineStyleOpts(width=1, type_="dotted"),
            label_opts=opts.LabelOpts(is_show=False),
        )
    )

    # 通道2（当前） - 橙色实线，较细
    # 从通道2的起点开始
    start_idx_2 = channel2["start_idx"] - start_idx  # 转换为相对索引
    # x2 应该从0开始，因为计算时用的是 np.arange(len(y2))
    x2 = np.arange(len(data) - start_idx_2)
    y2_fit = channel2["slope"] * x2 + channel2["intercept"]
    upper2 = y2_fit + channel2["std"] * 2
    lower2 = y2_fit - channel2["std"] * 2

    # 前面用 NaN 填充
    nan_padding = [np.nan] * start_idx_2

    channel2_upper = (
        Line()
        .add_xaxis(times)
        .add_yaxis(
            f"通道2上轨({channel2['duan_direction']})",
            nan_padding + upper2.tolist(),
            is_smooth=True,
            color="#FF9800",
            linestyle_opts=opts.LineStyleOpts(width=2),
            label_opts=opts.LabelOpts(is_show=False),
        )
    )

    channel2_lower = (
        Line()
        .add_xaxis(times)
        .add_yaxis(
            f"通道2下轨({channel2['duan_direction']})",
            nan_padding + lower2.tolist(),
            is_smooth=True,
            color="#FF9800",
            linestyle_opts=opts.LineStyleOpts(width=2),
            label_opts=opts.LabelOpts(is_show=False),
        )
    )

    # 通道2中轨
    channel2_center = (
        Line()
        .add_xaxis(times)
        .add_yaxis(
            f"通道2中轨",
            nan_padding + y2_fit.tolist(),
            is_smooth=True,
            color="#FF9800",
            linestyle_opts=opts.LineStyleOpts(width=1, type_="dotted"),
            label_opts=opts.LabelOpts(is_show=False),
        )
    )

    # ========== 缠论笔绘制 ==========
    from pyecharts.charts import Scatter

    bi_lines = []
    if chanlun is not None and chanlun.bi_data.get("dt"):
        bi_dt = chanlun.bi_data["dt"]
        bi_data_vals = chanlun.bi_data["data"]

        # 获取完整 df 的时间戳映射
        df_time_stamp_map = {ts: i for i, ts in enumerate(df["time_stamp"].values)}

        # 收集所有笔端点（按时间顺序）
        bi_all_times = []
        bi_all_values = []
        bi_high_times = []
        bi_high_values = []
        bi_low_times = []
        bi_low_values = []

        for i, ts in enumerate(bi_dt):
            if ts in df_time_stamp_map:
                idx = df_time_stamp_map[ts] - start_idx
                if 0 <= idx < len(times):
                    bi_all_times.append(times[idx])
                    bi_all_values.append(bi_data_vals[i])
                    # 高点（偶数索引）用红色，低点（奇数索引）用蓝色
                    if i % 2 == 0:
                        bi_high_times.append(times[idx])
                        bi_high_values.append(bi_data_vals[i])
                    else:
                        bi_low_times.append(times[idx])
                        bi_low_values.append(bi_data_vals[i])

        # 笔连线（折线连接所有笔端点）
        if bi_all_times:
            bi_connection_line = (
                Line()
                .add_xaxis(bi_all_times)
                .add_yaxis(
                    "笔连线",
                    bi_all_values,
                    is_smooth=False,
                    color="#9C27B0",
                    linestyle_opts=opts.LineStyleOpts(width=2),
                    label_opts=opts.LabelOpts(is_show=False),
                    symbol="circle",
                    symbol_size=6,
                )
            )
            bi_lines.append(bi_connection_line)

        # 高点散点（红色）
        if bi_high_times:
            bi_scatter_high = (
                Scatter()
                .add_xaxis(bi_high_times)
                .add_yaxis(
                    "笔高点",
                    bi_high_values,
                    symbol_size=10,
                    color="#FF4444",
                    label_opts=opts.LabelOpts(is_show=False),
                )
            )
            bi_lines.append(bi_scatter_high)

        # 低点散点（蓝色）
        if bi_low_times:
            bi_scatter_low = (
                Scatter()
                .add_xaxis(bi_low_times)
                .add_yaxis(
                    "笔低点",
                    bi_low_values,
                    symbol_size=10,
                    color="#4444FF",
                    label_opts=opts.LabelOpts(is_show=False),
                )
            )
            bi_lines.append(bi_scatter_low)

    # 叠加：通道1（底层） → 通道2（上层） → 笔
    overlap = (
        kline.overlap(channel1_lower)
        .overlap(channel1_upper)
        .overlap(channel1_center)
        .overlap(channel2_lower)
        .overlap(channel2_upper)
        .overlap(channel2_center)
    )

    # 添加笔线段
    for bi_line in bi_lines:
        overlap = overlap.overlap(bi_line)

    # ========== MACD 子图 ==========
    macd_data = _calculate_macd(data)

    # MACD 柱状图（零轴上方红色，下方绿色）
    # 将正值和负值分成两个系列以设置不同颜色
    macd_values = macd_data["macd"].tolist()
    macd_positive = [v if v >= 0 else 0 for v in macd_values]
    macd_negative = [v if v < 0 else 0 for v in macd_values]

    macd_bar_pos = (
        Bar()
        .add_xaxis(times)
        .add_yaxis(
            "MACD正",
            macd_positive,
            stack="MACD",
            itemstyle_opts=opts.ItemStyleOpts(color="#ef5350"),
            label_opts=opts.LabelOpts(is_show=False),
        )
    )

    macd_bar_neg = (
        Bar()
        .add_xaxis(times)
        .add_yaxis(
            "MACD负",
            macd_negative,
            stack="MACD",
            itemstyle_opts=opts.ItemStyleOpts(color="#26a69a"),
            label_opts=opts.LabelOpts(is_show=False),
        )
    )

    # DIF 线
    dif_line = (
        Line()
        .add_xaxis(times)
        .add_yaxis(
            "DIF",
            macd_data["dif"].tolist(),
            color="#FF9800",
            is_smooth=True,
            label_opts=opts.LabelOpts(is_show=False),
        )
    )

    # DEA 线
    dea_line = (
        Line()
        .add_xaxis(times)
        .add_yaxis(
            "DEA",
            macd_data["dea"].tolist(),
            color="#2196F3",
            is_smooth=True,
            label_opts=opts.LabelOpts(is_show=False),
        )
    )

    # MACD 子图叠加
    macd_overlap = macd_bar_pos.overlap(macd_bar_neg).overlap(dif_line).overlap(dea_line)

    # 使用 Grid 布局
    grid = Grid(init_opts=opts.InitOpts(width="100%", height="100vh"))
    grid.add(
        overlap,
        grid_opts=opts.GridOpts(pos_left="1%", pos_right="1%", pos_top="10%", pos_bottom="35%"),
    )
    grid.add(
        macd_overlap,
        grid_opts=opts.GridOpts(pos_left="1%", pos_right="1%", pos_top="70%", pos_bottom="5%"),
    )

    # 确保输出目录存在
    output_dir = os.path.dirname(file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # 渲染
    grid.render(file)

    # 添加全屏样式
    with open(file, "r", encoding="utf-8") as f:
        html_content = f.read()

    full_screen_style = """
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body, html { width: 100%; height: 100%; overflow: hidden; background: #fff; }
    </style>
    """
    html_content = html_content.replace("</head>", full_screen_style + "</head>")

    with open(file, "w", encoding="utf-8") as f:
        f.write(html_content)
