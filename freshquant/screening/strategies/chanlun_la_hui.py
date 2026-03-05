# -*- coding: utf-8 -*-
"""拉回中枢策略

策略：拉回中枢+中枢区间比较窄+拉回中枢后又有大阳
"""

import asyncio
from datetime import datetime

import pydash
from bson.codec_options import CodecOptions
from loguru import logger
from tqdm import tqdm

from freshquant.analysis.chanlun_analysis import Chanlun
from freshquant.config import cfg, settings
from freshquant.db import DBQuantAxis
from freshquant.KlineDataTool import get_stock_data
from freshquant.pattern import pattern_chanlun
from freshquant.screening.base.strategy import ScreenResult, ScreenStrategy
from freshquant.screening.writers import ReportOutput


class ChanlunLaHuiStrategy(ScreenStrategy):
    """拉回中枢策略

    策略逻辑：
    1. 识别拉回中枢信号
    2. 筛选中枢区间较窄的
    3. 拉回后出现大阳线（涨幅 >= 5%）
    """

    @property
    def name(self) -> str:
        return "chanlun_la_hui"

    def __init__(
        self,
        periods: list[str] | None = None,
        chanlun_imps: list[str] | None = None,
        min_rise: float = 1.05,
        output_json: bool = True,
        output_html: bool = False,
    ):
        """

        Args:
            periods: 周期列表，默认 ['60m', '90m', '120m', '1d']
            chanlun_imps: 缠论重要级别，默认 ['cl1', 'cl2', 'cl3', 'cl4']
            min_rise: 最小涨幅，默认 1.05（5%）
            output_json: 是否输出 JSON 文件
            output_html: 是否输出 HTML 报表
        """
        self.periods = periods or ['60m', '90m', '120m', '1d']
        self.chanlun_imps = chanlun_imps or ['cl1', 'cl2', 'cl3', 'cl4']
        self.min_rise = min_rise
        self.output_json = output_json
        self.output_html = output_html

    async def screen(self, **kwargs) -> list[ScreenResult]:
        """执行选股

        Returns:
            选股结果列表
        """
        stock_list = list(
            DBQuantAxis["stock_list"]
            .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=cfg.TZ))
            .find()
        )

        tasks = []
        for stock in stock_list:
            symbol = f"{stock['sse']}{stock['code']}"
            for period in self.periods:
                tasks.append(
                    self._scan_stock(
                        symbol=symbol,
                        code=stock['code'],
                        name=stock['name'],
                        sse=stock['sse'],
                        period=period,
                    )
                )

        # 并发执行 + 进度条
        results = []
        for task in tqdm(
            asyncio.as_completed(tasks),
            desc=self.name,
            total=len(tasks),
        ):
            try:
                task_results = await task
                if task_results:
                    results.extend(task_results)
            except Exception as e:
                logger.error(f"扫描失败: {e}")

        # 输出报表
        if results:
            if self.output_html:
                ReportOutput.print_table(results, title=self.name)
                ReportOutput.save_html(results, filename=f"{self.name}.html")

            if self.output_json:
                self._save_json(results)

        return results

    async def _scan_stock(
        self, symbol: str, code: str, name: str, sse: str, period: str
    ) -> list[ScreenResult]:
        """扫描单个股票

        Args:
            symbol: 完整代码
            code: 股票代码
            name: 股票名称
            sse: 交易所
            period: 周期

        Returns:
            选股结果列表
        """
        loop = asyncio.get_event_loop()

        # 获取数据
        hqdata = await loop.run_in_executor(None, get_stock_data, symbol, period)
        if hqdata is None or len(hqdata) == 0:
            return []

        count = len(hqdata)
        hqdata["time_str"] = hqdata["datetime"].apply(
            lambda dt: dt.strftime("%Y-%m-%d %H:%M")
        )

        results = []

        # 对每个缠论级别进行分析
        for imp in self.chanlun_imps:
            try:
                chanlun = await loop.run_in_executor(
                    None,
                    lambda: Chanlun(imp).analysis(
                        hqdata.time_stamp.to_list(),
                        hqdata.open.to_list(),
                        hqdata.close.to_list(),
                        hqdata.low.to_list(),
                        hqdata.high.to_list(),
                    )
                )

                hqdata['bi'] = chanlun.bi_signal_list
                hqdata['duan'] = chanlun.duan_signal_list
                entanglement_list = chanlun.entanglement_list

                lahui = await loop.run_in_executor(
                    None,
                    lambda: pattern_chanlun.la_hui(
                        entanglement_list,
                        hqdata['datetime'].to_list(),
                        hqdata['time_str'].to_list(),
                        hqdata.high.to_list(),
                        hqdata.low.to_list(),
                        hqdata.bi.to_list(),
                        hqdata.duan.to_list(),
                    )
                )

                signals = self._find_signals(
                    lahui, entanglement_list, hqdata, count
                )

                for sig in signals:
                    # 计算止损价格
                    stop_loss_price = self._calc_stop_loss(hqdata, sig['la_hui_idx'])

                    results.append(
                        self._make_result(
                            code=code,
                            name=name,
                            symbol=symbol,
                            period=period,
                            fire_time=sig['dt'],
                            price=sig['price'],
                            stop_loss_price=stop_loss_price,
                            signal_type=f"拉回中枢_{imp}",
                            tags=[imp],
                            remark=f"大阳线 {sig['rise']:.2%}",
                        )
                    )
            except Exception as e:
                logger.error(f"分析失败 {symbol} {period} {imp}: {e}")

        return results

    def _find_signals(self, lahui, entanglement_list, hqdata, count: int) -> list:
        """查找符合条件的信号

        Args:
            lahui: 拉回中枢结果
            entanglement_list: 中枢列表
            hqdata: 行情数据
            count: 数据条数

        Returns:
            信号列表
        """
        signals = []
        buy_idx_list = lahui["buy_zs_huila"]["idx"]
        time_str_list = hqdata['time_str'].to_list()
        open_list = hqdata.open.to_list()
        close_list = hqdata.close.to_list()
        high_list = hqdata.high.to_list()
        low_list = hqdata.low.to_list()

        for i in buy_idx_list:
            # 找到最后一个中枢
            e = (
                pydash.chain(entanglement_list)
                .find_last(lambda obj: obj.end < i)
                .value()
            )
            if e is None:
                continue

            min_close = pydash.min_(low_list[e.start : i])

            # 检查后续是否出现大阳
            for x in range(i, count):
                # 下跌创了低点就不搜寻了
                if low_list[x] < min_close:
                    break
                # 上涨突破中枢最高点也不搜寻了
                if high_list[x] > e.gg:
                    break
                # 大阳线
                rise = close_list[x] / open_list[x]
                if rise >= self.min_rise:
                    signals.append({
                        'la_hui_idx': i,
                        'dt': hqdata['datetime'].iloc[x],
                        'price': close_list[x],
                        'rise': rise,
                    })
                    break

        return signals

    def _calc_stop_loss(self, hqdata, la_hui_idx: int) -> float | None:
        """计算止损价格

        从拉回点往前找最近一个笔底（最低点）

        Args:
            hqdata: 行情数据
            la_hui_idx: 拉回点索引

        Returns:
            止损价格
        """
        low_list = hqdata.low.to_list()
        bi_list = hqdata.bi.to_list()

        for x in range(la_hui_idx, -1, -1):
            if bi_list[x] == -1:  # 笔底
                return low_list[x]

        return None

    def _save_json(self, results: list[ScreenResult]):
        """保存为 JSON 文件

        按日期分组保存到 output/选股/ 目录

        Args:
            results: 选股结果列表
        """
        output_dir = settings.get("output", {}).get("dir", "output")
        output_dir = f"{output_dir}/选股"

        # 按日期分组
        data_dict = {}
        for r in results:
            dt = r.fire_time.strftime("%Y-%m-%d")
            if dt not in data_dict:
                data_dict[dt] = []
            data_dict[dt].append({
                'symbol': r.symbol,
                'name': r.name,
                'period': r.period,
                'dt': r.fire_time.strftime("%Y-%m-%d %H:%M"),
                'la_hui': r.tags[0] if r.tags else "",
            })

        # 按日期保存
        import os
        import json
        for dt, records in data_dict.items():
            dt_dir = os.path.join(output_dir, dt)
            os.makedirs(dt_dir, exist_ok=True)

            filepath = os.path.join(dt_dir, f"{self.name}.json")
            with open(filepath, 'w', encoding='utf-8') as f:
                for record in records:
                    f.write(f"{json.dumps(record, ensure_ascii=False)}\n")

        logger.info(f"JSON 文件已保存到 {output_dir}")


# 兼容旧接口
def run():
    """兼容旧版本的 run 函数"""
    strategy = ChanlunLaHuiStrategy()

    async def _run():
        results = await strategy.screen()
        logger.info(f"完成扫描，共 {len(results)} 条信号")

    asyncio.run(_run())


if __name__ == "__main__":
    run()
