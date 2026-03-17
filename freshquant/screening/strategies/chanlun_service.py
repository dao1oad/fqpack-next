# -*- coding: utf-8 -*-
"""缠论信号策略（基于微服务）

调用 chanlun_service.get_data_v2 获取缠论信号
"""

import asyncio
from datetime import datetime, timedelta
from typing import Callable

from bson.codec_options import CodecOptions
from loguru import logger
from tqdm import tqdm

from freshquant.chanlun_service import get_data_v2
from freshquant.config import cfg
from freshquant.data.astock.basic import fq_fetch_a_stock_basic
from freshquant.data.trade_date_hist import tool_trade_date_last
from freshquant.db import DBfreshquant
from freshquant.screening.base.strategy import ScreenResult, ScreenStrategy
from freshquant.screening.signal_types import CHANLUN_SIGNAL_TYPES
from freshquant.screening.writers import DatabaseOutput, ReportOutput
from freshquant.util.datetime_helper import fq_util_datetime_localize


class ChanlunServiceStrategy(ScreenStrategy):
    """缠论信号策略

    从微服务获取多种缠论信号：
    - buy/sell_zs_huila: 回拉中枢
    - buy/sell_zs_tupo: 突破中枢
    - buy/sell_v_reverse: V反
    - buy/sell_five_v_reverse: 五浪V反
    - buy/sell_duan_break: 线段破坏
    """

    @property
    def name(self) -> str:
        return "chanlun_service"

    def __init__(
        self,
        periods: list[str] | None = None,
        pool_expire_days: int = 10,
        save_signal: bool = False,
        save_pools: bool = False,
        save_pre_pools: bool = False,
        max_concurrent: int = 50,
        days: int = 1,
        output_html: bool = True,
        on_universe: Callable[[dict], None] | None = None,
        on_stock_progress: Callable[[dict], None] | None = None,
        on_hit_raw: Callable[[dict], None] | None = None,
        on_result_accepted: Callable[[dict], None] | None = None,
        on_error: Callable[[dict], None] | None = None,
    ):
        """

        Args:
            periods: 周期列表，默认 ['30m', '60m', '1d']
            pool_expire_days: 股票池过期天数
            save_signal: 是否保存到 stock_signals
            save_pools: 是否保存到 stock_pools
            save_pre_pools: 是否保存到预选池
            max_concurrent: 最大并发数，默认 50
            days: 扫描最近 N 天的信号，默认 1
            output_html: 是否输出 HTML 报表，默认 True
        """
        self.periods = periods or ['30m', '60m', '1d']
        self.pool_expire_days = pool_expire_days
        self.save_signal = save_signal
        self.save_pools = save_pools
        self.save_pre_pools = save_pre_pools
        self.max_concurrent = max_concurrent
        self.days = days
        self.output_html = output_html
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._on_universe = on_universe
        self._on_stock_progress = on_stock_progress
        self._on_hit_raw = on_hit_raw
        self._on_result_accepted = on_result_accepted
        self._on_error = on_error

        # 只使用与 monitor_stock_zh_a_min.py 相同的信号类型
        monitored_signal_types = [
            "buy_zs_huila",
            "buy_v_reverse",
            "macd_bullish_divergence",
            "sell_zs_huila",
            "sell_v_reverse",
            "macd_bearish_divergence",
        ]
        self._signal_types = {
            sig_type: CHANLUN_SIGNAL_TYPES[sig_type]
            for sig_type in monitored_signal_types
            if sig_type in CHANLUN_SIGNAL_TYPES
        }

    async def screen(
        self,
        symbol: str | None = None,
        code: str | None = None,
        period: str | None = None,
        days: int | None = None,
        pre_pool_query: dict | None = None,
    ) -> list[ScreenResult]:
        """执行选股

        Args:
            symbol: 完整代码（如 sh600000）
            code: 股票代码（如 600000）
            period: 单个周期（默认扫描所有周期）
            days: 扫描最近 N 天的信号，默认使用初始化值

        Returns:
            选股结果列表
        """
        # 使用传入的 days 或初始化值
        scan_days = days if days is not None else self.days
        tasks = []
        total_tasks = 0

        if symbol:
            # 单个股票
            logger.info(f"扫描股票: {symbol}, 周期: {period or '所有'}")
            total_tasks = 1
            tasks.append(
                (
                    {"code": code or symbol[2:], "symbol": symbol},
                    self._scan_stock(symbol, period),
                )
            )
            self._emit_hook(
                self._on_universe,
                {
                    "strategy": self.name,
                    "total": total_tasks,
                    "mode": "single_code",
                    "code": code or symbol[2:],
                },
            )
        else:
            # 从预选池获取股票列表
            stock_list = list(
                DBfreshquant["stock_pre_pools"]
                .with_options(codec_options=CodecOptions(tz_aware=True, tzinfo=cfg.TZ))
                .find(pre_pool_query or {})
            )

            if not stock_list:
                logger.warning("预选池为空，请先添加股票到 stock_pre_pools")
                return []

            # 根据 code 去重，保留完整股票信息（包含 category）
            unique_stocks = {}
            for stock in stock_list:
                code = stock.get("code")
                if code and code not in unique_stocks:
                    unique_stocks[code] = stock

            dup_count = len(stock_list) - len(unique_stocks)
            if dup_count > 0:
                logger.info(f"发现 {dup_count} 个重复股票，已去重")

            stock_list = list(unique_stocks.values())
            logger.info(f"从预选池加载 {len(stock_list)} 只股票（去重后），开始扫描...")
            total_tasks = len(stock_list)
            self._emit_hook(
                self._on_universe,
                {
                    "strategy": self.name,
                    "total": total_tasks,
                    "mode": "pre_pool",
                    "code": None,
                },
            )

            for stock in tqdm(
                stock_list, desc="加载股票", disable=len(stock_list) < 10
            ):
                stock_info = fq_fetch_a_stock_basic(stock["code"])
                if not stock_info:
                    logger.warning(f"无法获取股票信息: {stock['code']}")
                    continue
                sym = f"{stock_info['sse']}{stock_info['code']}"
                tasks.append(
                    (
                        {
                            "code": stock["code"],
                            "symbol": sym,
                            "name": stock_info.get("name"),
                        },
                        self._scan_stock(sym, period, stock),
                    )
                )

        if not tasks:
            logger.warning("没有可扫描的股票")
            return []

        # 分批执行，避免一次性创建过多任务
        logger.info(
            f"开始分批扫描 {len(tasks)} 只股票（每批 {self.max_concurrent} 只）..."
        )
        results = []
        batch_size = self.max_concurrent
        processed_total = 0

        for i in range(0, len(tasks), batch_size):
            batch = tasks[i : i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(tasks) + batch_size - 1) // batch_size

            logger.info(
                f"执行第 {batch_num}/{total_batches} 批（{len(batch)} 只股票）..."
            )

            # 执行当前批次
            batch_results = await asyncio.gather(
                *[item[1] for item in batch], return_exceptions=True
            )

            # 处理结果
            batch_valid_results = []
            for task_meta, r in zip(batch, batch_results):
                meta = task_meta[0]
                processed_total += 1
                if isinstance(r, Exception):
                    logger.error(f"扫描失败: {r}")
                    self._emit_error(
                        code=meta.get("code"),
                        symbol=meta.get("symbol"),
                        error=r,
                    )
                    self._emit_hook(
                        self._on_stock_progress,
                        {
                            "strategy": self.name,
                            "processed": processed_total,
                            "total": total_tasks,
                            "code": meta.get("code"),
                            "name": meta.get("name"),
                            "symbol": meta.get("symbol"),
                            "result_count": 0,
                            "status": "error",
                        },
                    )
                elif r:
                    batch_valid_results.extend(r)
                    self._emit_hook(
                        self._on_stock_progress,
                        {
                            "strategy": self.name,
                            "processed": processed_total,
                            "total": total_tasks,
                            "code": meta.get("code"),
                            "name": meta.get("name"),
                            "symbol": meta.get("symbol"),
                            "result_count": len(r),
                            "status": "ok",
                        },
                    )
                else:
                    self._emit_hook(
                        self._on_stock_progress,
                        {
                            "strategy": self.name,
                            "processed": processed_total,
                            "total": total_tasks,
                            "code": meta.get("code"),
                            "name": meta.get("name"),
                            "symbol": meta.get("symbol"),
                            "result_count": 0,
                            "status": "ok",
                        },
                    )

            # 筛选最近 N 个交易日的信号（每批立即过滤）
            if scan_days > 0 and batch_valid_results:
                # 获取最后一个交易日
                last_trade_date = tool_trade_date_last()
                if last_trade_date:
                    # 转换为 datetime 并本地化，然后减去天数
                    cutoff_date = fq_util_datetime_localize(
                        datetime.combine(last_trade_date, datetime.min.time())
                    ) - timedelta(days=scan_days - 1)
                else:
                    # 如果无法获取交易日，回退到当前时间
                    cutoff_date = fq_util_datetime_localize(datetime.now()) - timedelta(
                        days=scan_days
                    )

                before_count = len(batch_valid_results)
                # 筛选日期和信号方向（只保留 BUY_LONG）
                batch_valid_results = [
                    r
                    for r in batch_valid_results
                    if r.fire_time >= cutoff_date and r.position == "BUY_LONG"
                ]
                after_count = len(batch_valid_results)
                if before_count > after_count:
                    logger.debug(
                        f"批次 {batch_num} 筛选: {before_count} → {after_count}（过滤 SELL_SHORT）"
                    )

            # 添加到总结果
            results.extend(batch_valid_results)

            # 每批后报告进度
            logger.info(
                f"第 {batch_num}/{total_batches} 批完成，本批 {len(batch_valid_results)} 条，累计 {len(results)} 条"
            )

        logger.info(f"扫描完成，共找到 {len(results)} 条信号")

        # 去重和排序（与 clxs.py 保持一致）
        results = self._deduplicate(results)
        self._sort_results(results)

        for result in results:
            self._emit_hook(self._on_result_accepted, self._result_to_payload(result))

        # 输出报表
        if results:
            ReportOutput.print_table(results, title="缠论信号")

            if self.output_html:
                ReportOutput.save_html(
                    results, filename="chanlun_service_screening.html"
                )

        # 批量保存
        if results:
            DatabaseOutput.save_all(
                results,
                save_signal=self.save_signal,
                save_pools=self.save_pools,
                save_pre_pools=self.save_pre_pools,
                pool_expire_days=self.pool_expire_days,
            )

        return results

    async def _scan_stock(
        self, symbol: str, period: str | None = None, stock_info: dict | None = None
    ) -> list[ScreenResult]:
        """扫描单个股票（带超时）

        Args:
            symbol: 完整代码
            period: 单个周期，None 表示所有周期
            stock_info: 股票信息字典（包含 category）

        Returns:
            选股结果列表
        """
        sse = symbol[:2]
        code = symbol[2:]
        category = stock_info.get("category", "") if stock_info else ""

        periods = [period] if period else self.periods
        results = []

        for p in periods:
            try:
                # 添加超时限制，避免卡死
                period_results = await asyncio.wait_for(
                    self._scan_period(symbol, code, sse, p, category),
                    timeout=30.0,  # 30 秒超时
                )
                results.extend(period_results)
            except asyncio.TimeoutError:
                logger.warning(f"扫描 {symbol} {p} 超时（30s），跳过")
            except Exception as e:
                logger.error(f"扫描 {symbol} {p} 失败: {e}")

        return results

    async def _scan_period(
        self, symbol: str, code: str, sse: str, period: str, category: str = ""
    ) -> list[ScreenResult]:
        """扫描单个周期

        Args:
            symbol: 完整代码
            code: 股票代码
            sse: 交易所
            period: 周期
            category: 分类（来自预选池）

        Returns:
            选股结果列表
        """
        # 在线程池中执行阻塞调用
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None, get_data_v2, symbol, period, datetime.now().strftime("%Y-%m-%d")
        )

        if not resp:
            return []

        stock_info = await loop.run_in_executor(None, fq_fetch_a_stock_basic, code)
        if not stock_info:
            return []

        name = stock_info.get("name", "")
        results = []

        for signal_type, signal_info in self._signal_types.items():
            signals = resp.get(signal_type, {})
            dates = signals.get("datetime", [])
            data = signals.get("price", [])
            stop_loss_prices = signals.get("stop_lose_price", [])
            tags = signals.get("tag", [])

            remark = signal_info["name"]
            position = signal_info["direction"]

            for i, fire_time in enumerate(dates):
                try:
                    # 本地化时间
                    localized_fire_time = fq_util_datetime_localize(fire_time)

                    price = data[i] if i < len(data) else 0
                    stop_loss_price = (
                        stop_loss_prices[i] if i < len(stop_loss_prices) else None
                    )
                    tag_list = tags[i].split(",") if i < len(tags) and tags[i] else []

                    results.append(
                        self._make_result(
                            code=code,
                            name=name,
                            symbol=symbol,
                            period=period,
                            fire_time=localized_fire_time,
                            price=price,
                            stop_loss_price=stop_loss_price,
                            signal_type=signal_type,
                            tags=tag_list,
                            position=position,
                            remark=remark,
                            category=category,
                        )
                    )
                    self._emit_hook(
                        self._on_hit_raw,
                        self._result_to_payload(results[-1]),
                    )
                except Exception as e:
                    logger.error(f"解析信号失败 {symbol} {signal_type} {i}: {e}")

        return results

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
        """排序（按日期）

        Args:
            results: 选股结果列表（就地修改）
        """
        results.sort(key=lambda r: r.fire_time, reverse=True)

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
            logger.warning(f"chanlun_service hook 执行失败: {exc}")

    def _emit_error(
        self,
        *,
        code: str | None,
        symbol: str | None = None,
        error: Exception,
    ) -> None:
        self._emit_hook(
            self._on_error,
            {
                "strategy": self.name,
                "code": code,
                "symbol": symbol,
                "error": str(error),
            },
        )


# 兼容旧接口
def run(symbol: str | None = None, input_period: str | None = None):
    """兼容旧版本的 run 函数

    Args:
        symbol: 完整代码（如 sh600000）
        input_period: 周期
    """
    strategy = ChanlunServiceStrategy()

    async def _run():
        results = await strategy.screen(symbol=symbol, period=input_period)
        logger.info(f"完成扫描，共 {len(results)} 条信号")

    asyncio.run(_run())


if __name__ == "__main__":
    run()
