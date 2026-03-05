# -*- coding: utf-8 -*-

import pandas as pd
import traceback
import argparse
import asyncio
from freshquant.trading.dt import fq_trading_fetch_trade_dates
from tabulate import tabulate
from tqdm import tqdm
from typing import Optional
from freshquant.instrument.stock import fq_inst_fetch_stock_list
from freshquant.data.stock import fq_data_stock_fetch_day
from datetime import datetime, timedelta
from loguru import logger
from freshquant.pattern.chanlun.macd_divergence import locate_macd_divergence


async def fetch_stock_day_data(code, dt: datetime = datetime.now()) -> Optional[pd.DataFrame]:
    """获取股票日线数据"""
    try:
        trade_dates = fq_trading_fetch_trade_dates()
        trade_dates = trade_dates[trade_dates['trade_date'] <= dt.date()]
        trade_dates = trade_dates["trade_date"].tail(5000)
        start = datetime.combine(trade_dates.iloc[0], datetime.min.time())
        end = datetime.combine(trade_dates.iloc[-1], datetime.min.time())
        return fq_data_stock_fetch_day(
            code=code,
            start=start,
            end=end)
    except Exception as e:
        logger.info(f"Error fetching data for stock {code}: {e} {traceback.format_exc()}")
        return None


async def process_stock_macd_divergence(stock, days: int = 1) -> Optional[list]:
    """处理单个股票的MACD背驰信号，只返回最近days天内的信号"""
    result = []

    # 获取股票数据
    stock_day_data: pd.DataFrame = await fetch_stock_day_data(stock.get("code"))

    if stock_day_data is not None and len(stock_day_data) > 0:
        dates = stock_day_data.index.to_list()
        highs = stock_day_data.high.to_list()
        lows = stock_day_data.low.to_list()
        opens = stock_day_data.open.to_list()
        closes = stock_day_data.close.to_list()
        amounts = stock_day_data.amount.to_list()

        try:
            # 调用locate_macd_divergence函数（bi_list会在函数内部计算）
            divergence_result = locate_macd_divergence(
                datetime_list=dates,
                high_list=highs,
                low_list=lows,
                open_list=opens,
                close_list=closes
            )

            # 获取最近days天的日期范围
            recent_date_threshold = datetime.now() - timedelta(days=days-1)
            recent_date_threshold = recent_date_threshold.date()

            # 处理看涨背驰信号
            bullish_signals = divergence_result['bullish']
            for i in range(len(bullish_signals['idx'])):
                signal_date = bullish_signals['datetime'][i].date()
                # 只保留最近days天内的信号
                if signal_date >= recent_date_threshold:
                    result.append({
                        "stock": stock,
                        "signal_type": "bullish",
                        "date": bullish_signals['datetime'][i],
                        "datetime_str": bullish_signals['datetime_str'][i],
                        "idx": bullish_signals['idx'][i],
                        "price": bullish_signals['price'][i],
                        "stop_lose_price": bullish_signals['stop_lose_price'][i],
                        "stop_loss_rate": f'{round(((bullish_signals["price"][i] - bullish_signals["stop_lose_price"][i]) / bullish_signals["price"][i]) * 100, 2)}%',
                        "zhongshu_count": bullish_signals['zhongshu_count'][i],
                        "amount": amounts[bullish_signals['idx'][i]] if bullish_signals['idx'][i] < len(amounts) else None,
                    })

            # 处理看跌背驰信号
            bearish_signals = divergence_result['bearish']
            for i in range(len(bearish_signals['idx'])):
                signal_date = bearish_signals['datetime'][i].date()
                # 只保留最近days天内的信号
                if signal_date >= recent_date_threshold:
                    result.append({
                        "stock": stock,
                        "signal_type": "bearish",
                        "date": bearish_signals['datetime'][i],
                        "datetime_str": bearish_signals['datetime_str'][i],
                        "idx": bearish_signals['idx'][i],
                        "price": bearish_signals['price'][i],
                        "stop_lose_price": bearish_signals['stop_lose_price'][i],
                        "stop_loss_rate": f'{round(((bearish_signals["stop_lose_price"][i] - bearish_signals["price"][i]) / bearish_signals["price"][i]) * 100, 2)}%',
                        "zhongshu_count": bearish_signals['zhongshu_count'][i],
                        "amount": amounts[bearish_signals['idx'][i]] if bearish_signals['idx'][i] < len(amounts) else None,
                    })

        except Exception as e:
            logger.error(f"Error processing MACD divergence for stock {stock.get('code')}: {e}")

    return result


async def test_macd_divergence(days: int = 1, code: Optional[str] = None, limit: Optional[int] = None):
    """测试locate_macd_divergence函数，输出最近days天内出现信号的股票"""
    stock_list = fq_inst_fetch_stock_list()
    stock_list = [stock for stock in stock_list if "ST" not in stock.get("name", "")]

    if code:
        stock_list = [stock for stock in stock_list if stock.get("code") == code]

    if limit:
        stock_list = stock_list[:limit]

    days_text = "最后一个交易日" if days == 1 else f"最近{days}天"
    print(f"查找{days_text}内出现MACD背驰信号的股票，共检查{len(stock_list)}只股票...")

    pbar = tqdm(total=len(stock_list), desc="Processing MACD divergence signals")

    async def process_stock_with_progress(stock):
        result = await process_stock_macd_divergence(stock, days)
        pbar.update(1)
        return result

    tasks = [process_stock_with_progress(stock) for stock in stock_list]
    records = await asyncio.gather(*tasks, return_exceptions=True)
    pbar.close()

    # 过滤异常结果并展平列表
    valid_records = []
    for record in records:
        if not isinstance(record, Exception) and record:
            valid_records.extend(record)

    if len(valid_records) > 0:
        df_records = pd.DataFrame(valid_records)

        # 展开股票信息
        stock_info = df_records['stock'].apply(pd.Series)
        stock_info.drop('_id', axis=1, inplace=True, errors='ignore')
        columns_to_drop = ['volunit', 'decimal_point', 'sse', 'sec', 'pre_close']
        stock_info.drop(columns=columns_to_drop, inplace=True, errors='ignore')
        df_records.drop(columns=['stock'], inplace=True)

        result_df = pd.concat([stock_info, df_records], axis=1)
        result_df['date'] = result_df['date'].dt.date

        # 按日期和成交量排序
        result_df.sort_values(by=['date', 'signal_type', 'amount'], ascending=[False, True, False], inplace=True)
        result_df.reset_index(drop=True, inplace=True)

        print(f"\n{days_text}内MACD背驰信号结果 - 发现{len(result_df)}个信号")
        print(f"看涨背驰信号: {len(result_df[result_df['signal_type'] == 'bullish'])}")
        print(f"看跌背驰信号: {len(result_df[result_df['signal_type'] == 'bearish'])}")

        # 显示结果表格
        display_columns = ['code', 'name', 'signal_type', 'date', 'price', 'stop_lose_price', 'stop_loss_rate', 'zhongshu_count', 'amount']
        display_df = result_df[display_columns] if all(col in result_df.columns for col in display_columns) else result_df

        print(tabulate(display_df, headers='keys', tablefmt='pretty', showindex=False))

        # 保存到HTML文件
        filename = f'MACD_Divergence_{days}Days_Results.html'
        styled_result_df = result_df.style \
            .set_caption(f"{days_text}内MACD背驰信号结果") \
            .set_table_styles([
                {'selector': 'caption', 'props': [('text-align', 'left'), ('font-size', '16px'), ('font-weight', 'bold')]},
                {'selector': 'th', 'props': [('background-color', '#f0f0f0'), ('text-align', 'left'), ('padding', '4px')]},
                {'selector': 'td', 'props': [('text-align', 'left'), ('padding', '4px')]}
            ]) \
            .highlight_null(color='lightgrey') \
            .set_properties(subset=['code'], **{'color': 'darkblue', 'font-weight': 'bold'}) \
            .set_properties(subset=['signal_type'], **{'color': 'darkgreen', 'font-weight': 'bold'})

        styled_result_df.to_html(filename)
        print(f"\n结果已保存到 {filename}")

    else:
        print(f"{days_text}内未发现MACD背驰信号。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test locate_macd_divergence function")
    parser.add_argument("--days", type=int, default=1, help="Number of days to consider for testing")
    parser.add_argument("--code", type=str, help="Specific stock code to test (optional)")
    parser.add_argument("--limit", type=int, help="Limit number of stocks to test (optional)")

    args = parser.parse_args()

    asyncio.run(test_macd_divergence(
        days=args.days,
        code=args.code,
        limit=args.limit
    ))