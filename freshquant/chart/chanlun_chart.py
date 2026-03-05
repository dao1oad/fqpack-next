from pyecharts import options as opts
from pyecharts.charts import Bar, Grid, Kline, Line

"""
用pyecharts生成一张图表快照
"""


def create_charts(klines, page_title="Awesome-Pyecharts", file="chanlun-kline.html"):
    grid_chart = Grid(
        init_opts=opts.InitOpts(
            width="1300px",
            height="650px",
            page_title=page_title,
            js_host="https://cdn.staticfile.org/echarts/4.6.0/",
        )
    )
    times = klines['time_str'].tolist()
    datas = klines[['open', 'close', 'low', 'high']].values.tolist()
    bi_lines = []
    line = []
    for idx in range(len(klines)):
        if klines.loc[idx, 'bi'] == 1:
            if len(line) == 1:
                line.append(
                    {
                        'xAxis': klines.loc[idx, 'time_str'],
                        'yAxis': klines.loc[idx, 'high'],
                        'value': klines.loc[idx, 'high'],
                    }
                )
                bi_lines.append(line)
            line = [
                {
                    'xAxis': klines.loc[idx, 'time_str'],
                    'yAxis': klines.loc[idx, 'high'],
                    'value': klines.loc[idx, 'high'],
                }
            ]
        elif klines.loc[idx, 'bi'] == -1:
            if len(line) == 1:
                line.append(
                    {
                        'xAxis': klines.loc[idx, 'time_str'],
                        'yAxis': klines.loc[idx, 'low'],
                        'value': klines.loc[idx, 'low'],
                    }
                )
                bi_lines.append(line)
            line = [
                {
                    'xAxis': klines.loc[idx, 'time_str'],
                    'yAxis': klines.loc[idx, 'low'],
                    'value': klines.loc[idx, 'low'],
                }
            ]

    duan_xdata = []
    duan_ydata = []
    for idx in range(len(klines)):
        if klines.loc[idx, 'duan'] == 1:
            duan_xdata.append(klines.loc[idx, 'time_str'])
            duan_ydata.append(klines.loc[idx, 'high'])
        elif klines.loc[idx, 'duan'] == -1:
            duan_xdata.append(klines.loc[idx, 'time_str'])
            duan_ydata.append(klines.loc[idx, 'low'])

    kline = (
        Kline()
        .add_xaxis(xaxis_data=times)
        .add_yaxis(
            series_name='',
            y_axis=datas,
            markline_opts=opts.MarkLineOpts(
                label_opts=opts.LabelOpts(
                    position="inside", color="blue", font_size=12
                ),
                data=bi_lines,
                linestyle_opts=opts.LineStyleOpts(width=1, type_='dashed', opacity=1),
                symbol='none',
                symbol_size=10,
            ),
        )
        .set_series_opts(markarea_opts=opts.MarkAreaOpts(is_silent=True, data=[]))
        .set_global_opts(
            xaxis_opts=opts.AxisOpts(is_scale=True),
            yaxis_opts=opts.AxisOpts(
                is_scale=True,
                splitarea_opts=opts.SplitAreaOpts(
                    is_show=True, areastyle_opts=opts.AreaStyleOpts(opacity=1)
                ),
            ),
            datazoom_opts=[opts.DataZoomOpts(type_="inside")],
            title_opts=opts.TitleOpts(page_title),
        )
    )
    duan_line = (
        Line()
        .set_global_opts(
            tooltip_opts=opts.TooltipOpts(is_show=False),
            xaxis_opts=opts.AxisOpts(type_="category"),
            yaxis_opts=opts.AxisOpts(
                type_="value",
                axistick_opts=opts.AxisTickOpts(is_show=True),
                splitline_opts=opts.SplitLineOpts(is_show=True),
            ),
        )
        .add_xaxis(xaxis_data=duan_xdata)
        .add_yaxis(
            series_name="",
            y_axis=duan_ydata,
            symbol="emptyCircle",
            is_symbol_show=True,
            label_opts=opts.LabelOpts(is_show=False),
        )
    )
    overlap_kline_line = kline.overlap(duan_line)

    grid_chart.add(
        overlap_kline_line,
        grid_opts=opts.GridOpts(pos_left="3%", pos_right="1%", height="60%"),
    ).render(file)
