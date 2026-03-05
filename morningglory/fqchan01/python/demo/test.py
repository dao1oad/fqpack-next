from datetime import datetime
from rich.progress import Progress
from freshquant.instrument.stock import fq_inst_fetch_stock_list
from freshquant.trading.dt import fq_trading_fetch_trade_dates
from freshquant.data.stock import fq_data_stock_fetch_day
from fqchan01 import fq_recognise_bi, FqChanOptions

def main():
    trade_dates = fq_trading_fetch_trade_dates()
    trade_dates = trade_dates[trade_dates['trade_date'] <= datetime.now().date()]
    trade_dates = trade_dates["trade_date"].tail(5000)
    start = datetime.combine(trade_dates.iloc[0], datetime.min.time())
    end = datetime.combine(trade_dates.iloc[-1], datetime.min.time())
    stock_list = fq_inst_fetch_stock_list()
    total_stocks = len(stock_list)
    with Progress() as progress:
        task = progress.add_task("[cyan]Processing stocks...", total=total_stocks)
        for stock in stock_list:
            data = fq_data_stock_fetch_day(stock["code"], start, end)
            progress.update(task, advance=1)
        length = len(data)
        high_price_list = data["high"].tolist()
        low_price_list = data["low"].tolist()
        # 创建自定义配置对象
        chan_opts = FqChanOptions(
            inclusion_mode=2, 
            bi_mode=6, 
            force_wave_stick_count=15,
            allow_pivot_across=0,
            merge_non_complehensive_wave=0
        )
        fq_recognise_bi(length, high_price_list, low_price_list, chan_opts)

if __name__ == "__main__":
    main()
