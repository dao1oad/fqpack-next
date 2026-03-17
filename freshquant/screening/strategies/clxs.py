# -*- coding: utf-8 -*-
"""垂直线段选股策略（CLXS）

使用 fqcopilot 和 fqchan04 进行垂直线段选股
"""

import argparse
import asyncio
from datetime import datetime, timedelta
from typing import Callable, Optional

import pandas as pd
import pydash
from loguru import logger
from tabulate import tabulate
from tqdm import tqdm

from freshquant.data.stock import fq_data_stock_fetch_day
from freshquant.instrument.stock import fq_inst_fetch_stock_list
from freshquant.screening.base.strategy import ScreenResult, ScreenStrategy
from freshquant.screening.writers import DatabaseOutput, ReportOutput
from freshquant.trading.dt import fq_trading_fetch_trade_dates

# 导入外部模块
try:
    from fqchan04 import fq_recognise_bi  # type: ignore
    from fqcopilot import fq_clxs  # type: ignore
except ImportError as e:
    logger.warning(f"导入外部模块失败: {e}")
    fq_clxs = None
    fq_recognise_bi = None


class ClxsStrategy(ScreenStrategy):
    """垂直线段选股策略

    使用 fqcopilot.fq_clxs 和 fqchan04.fq_recognise_bi 进行选股
    """

    @property
    def name(self) -> str:
        return "clxs"

    def __init__(
        self,
        wave_opt: int = 1560,
        stretch_opt: int = 0,
        trend_opt: int = 1,
        model_opt: int = 10001,
        save_pre_pools: bool = True,
        output_html: bool = True,
        on_universe: Callable[[dict], None] | None = None,
        on_stock_progress: Callable[[dict], None] | None = None,
        on_hit_raw: Callable[[dict], None] | None = None,
        on_result_accepted: Callable[[dict], None] | None = None,
        on_error: Callable[[dict], None] | None = None,
    ):
        """

        Args:
            wave_opt: 波浪参数，默认 1560
            stretch_opt: 拉伸参数，默认 0
            trend_opt: 趋势参数，默认 1
            model_opt: 模型参数，默认 10001
            save_pre_pools: 是否保存到预选池
            output_html: 是否输出 HTML 报表
        """
        self.wave_opt = wave_opt
        self.stretch_opt = stretch_opt
        self.trend_opt = trend_opt
        self.model_opt = model_opt
        self.save_pre_pools = save_pre_pools
        self.output_html = output_html
        self._on_universe = on_universe
        self._on_stock_progress = on_stock_progress
        self._on_hit_raw = on_hit_raw
        self._on_result_accepted = on_result_accepted
        self._on_error = on_error

    async def screen(
        self,
        days: int = 1,
        code: str | None = None,
        **kwargs,
    ) -> list[ScreenResult]:
        """执行选股

        Args:
            days: 扫描最近 N 天，默认 1
            code: 指定股票代码（可选）

        Returns:
            选股结果列表
        """
        if fq_clxs is None or fq_recognise_bi is None:
            logger.error("缺少必要的外部模块 fqcopilot 或 fqchan04")
            return []

        stock_list = fq_inst_fetch_stock_list()
        stock_list = [s for s in stock_list if "ST" not in s.get("name", "")]

        if code:
            stock_list = [s for s in stock_list if s.get("code") == code]

        self._emit_hook(
            self._on_universe,
            {
                "strategy": self.name,
                "total": len(stock_list),
                "mode": "single_code" if code else "market",
                "code": code,
            },
        )

        tasks = []
        pbar = tqdm(total=len(stock_list), desc="Processing signals")
        processed = 0

        async def process_with_progress(stock):
            nonlocal processed
            result_count = 0
            status = "ok"
            try:
                result = await self._scan_stock(stock, days)
                result_count = len(result)
                return result
            except Exception as exc:
                status = "error"
                self._emit_error(
                    code=stock.get("code"),
                    name=stock.get("name"),
                    error=exc,
                )
                return exc
            finally:
                processed += 1
                self._emit_hook(
                    self._on_stock_progress,
                    {
                        "strategy": self.name,
                        "processed": processed,
                        "total": len(stock_list),
                        "code": stock.get("code"),
                        "name": stock.get("name"),
                        "result_count": result_count,
                        "status": status,
                    },
                )
                pbar.update(1)

        for stock in stock_list:
            tasks.append(process_with_progress(stock))

        records_nested = await asyncio.gather(*tasks, return_exceptions=True)
        pbar.close()

        results = []
        for r in records_nested:
            if isinstance(r, Exception):
                logger.error(f"扫描失败: {r}")
            elif r:
                results.extend(r)

        # 去重和排序
        results = self._deduplicate(results)
        self._sort_results(results)

        for result in results:
            self._emit_hook(self._on_result_accepted, self._result_to_payload(result))

        # 保存到预选池
        if results and self.save_pre_pools:
            DatabaseOutput.save_all(
                results,
                save_signal=False,
                save_pools=False,
                save_pre_pools=True,
            )

        # 输出报表
        if results:
            model_text = f'CLX{str(self.model_opt).zfill(5)}'
            ReportOutput.print_table(results, title=model_text)

            if self.output_html:
                ReportOutput.save_html(results, filename=f"{model_text}_Screening.html")

        return results

    async def _scan_stock(self, stock: dict, days: int = 1) -> list[ScreenResult]:
        """扫描单个股票

        Args:
            stock: 股票信息字典
            days: 扫描最近 N 天

        Returns:
            选股结果列表
        """
        results = []

        for day in range(days - 1, -1, -1):
            dt = datetime.now() - timedelta(days=day)

            # 获取日线数据
            stock_day_data = await self._fetch_stock_day_data(stock.get("code"), dt)
            if stock_day_data is None or len(stock_day_data) == 0:
                continue

            dates = stock_day_data.index.to_list()
            highs = stock_day_data.high.to_list()
            lows = stock_day_data.low.to_list()
            closes = stock_day_data.close.to_list()
            amounts = stock_day_data.amount.to_list()
            length = len(highs)

            # 识别笔
            bi = fq_recognise_bi(length, highs, lows)

            # 计算信号
            sigs = fq_clxs(
                length,
                highs,
                lows,
                stock_day_data.open.to_list(),
                closes,
                stock_day_data.volume.to_list(),
                self.wave_opt,
                self.stretch_opt,
                self.trend_opt,
                self.model_opt,
            )

            # 检查最新信号
            if sigs[-1] > 0:
                # 找止损价格（往前找最近笔底的最低价）
                stop_loss_price = self._find_stop_loss(bi, lows)

                results.append(
                    self._make_result(
                        code=stock['code'],
                        name=stock['name'],
                        symbol=f"{stock.get('sse', '')}{stock['code']}",
                        period="1d",
                        fire_time=dates[-1],
                        price=closes[-1],
                        stop_loss_price=stop_loss_price,
                        signal_type=f"CLXS_{self.model_opt}",
                        position="BUY_LONG",
                    )
                )
                self._emit_hook(
                    self._on_hit_raw,
                    self._result_to_payload(results[-1]),
                )

        return results

    async def _fetch_stock_day_data(
        self, code: str, dt: datetime
    ) -> Optional[pd.DataFrame]:
        """获取日线数据

        Args:
            code: 股票代码
            dt: 日期

        Returns:
            K线数据
        """
        try:
            trade_dates = fq_trading_fetch_trade_dates()
            trade_dates = trade_dates[trade_dates['trade_date'] <= dt.date()]
            trade_dates = trade_dates["trade_date"].tail(5000)

            start = datetime.combine(trade_dates.iloc[0], datetime.min.time())
            end = datetime.combine(trade_dates.iloc[-1], datetime.min.time())

            return fq_data_stock_fetch_day(code=code, start=start, end=end)
        except Exception as e:
            logger.info(f"获取数据失败 {code}: {e}")
            return None

    def _find_stop_loss(self, bi: list, lows: list) -> float | None:
        """查找止损价格

        从最新位置往前找最近一个笔底的最低价

        Args:
            bi: 笔信号列表
            lows: 最低价列表

        Returns:
            止损价格
        """
        for x in range(len(bi) - 1, -1, -1):
            if bi[x] == -1:  # 笔底
                return lows[x]
        return None

    def _deduplicate(self, results: list[ScreenResult]) -> list[ScreenResult]:
        """去重（按 code + date）

        Args:
            results: 选股结果列表

        Returns:
            去重后的结果
        """
        seen = set()
        unique = []
        for r in results:
            key = (r.code, r.fire_time.date())
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return unique

    def _sort_results(self, results: list[ScreenResult]):
        """排序（按日期、金额）

        Args:
            results: 选股结果列表（就地修改）
        """
        results.sort(key=lambda r: (r.fire_time, getattr(r, 'amount', 0)), reverse=True)

    def _result_to_payload(self, result: ScreenResult) -> dict:
        return {
            "strategy": self.name,
            "code": result.code,
            "name": result.name,
            "symbol": result.symbol,
            "period": result.period,
            "fire_time": result.fire_time,
            "price": result.price,
            "stop_loss_price": result.stop_loss_price,
            "signal_type": result.signal_type,
            "position": result.position,
            "remark": result.remark,
            "category": result.category,
            "tags": list(result.tags),
        }

    def _emit_hook(
        self, callback: Callable[[dict], None] | None, payload: dict
    ) -> None:
        if callback is None:
            return
        try:
            callback(payload)
        except Exception as exc:
            logger.warning(f"CLXS hook 执行失败: {exc}")

    def _emit_error(
        self,
        *,
        code: str | None,
        name: str | None = None,
        error: Exception,
    ) -> None:
        self._emit_hook(
            self._on_error,
            {
                "strategy": self.name,
                "code": code,
                "name": name,
                "error": str(error),
            },
        )


# 兼容旧接口
async def screen(
    model: str = "clxs",
    days: int = 1,
    wave_opt: int = 1560,
    stretch_opt: int = 0,
    trend_opt: int = 1,
    model_opt: int = 10001,
    code: str | None = None,
):
    """兼容旧版本的 screen 函数

    Args:
        model: 模型名称（目前只支持 clxs）
        days: 扫描天数
        wave_opt: 波浪参数
        stretch_opt: 拉伸参数
        trend_opt: 趋势参数
        model_opt: 模型参数
        code: 股票代码
    """
    strategy = ClxsStrategy(
        wave_opt=wave_opt,
        stretch_opt=stretch_opt,
        trend_opt=trend_opt,
        model_opt=model_opt,
    )
    await strategy.screen(days=days, code=code)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stock screening script")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--wave-opt", type=int, default=1560)
    parser.add_argument("--stretch-opt", type=int, default=0)
    parser.add_argument("--trend-opt", type=int, default=1)
    parser.add_argument("--model-opt", type=int, default=10001)
    args = parser.parse_args()

    asyncio.run(
        screen(
            days=args.days,
            wave_opt=args.wave_opt,
            stretch_opt=args.stretch_opt,
            trend_opt=args.trend_opt,
            model_opt=args.model_opt,
        )
    )
