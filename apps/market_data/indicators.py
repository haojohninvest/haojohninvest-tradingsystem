import pandas as pd
from django.db import transaction
from datetime import date
from .models import DailyPrice
from apps.analysis.models import Indicator
import logging

logger = logging.getLogger(__name__)


def calculate_all_indicators(lookback_days=14):
    """
    計算所有股票的技術指標 (EMA, SMA, 漲跌幅)
    優化版：分批讀取 + 向量計算 + bulk_create + 每批寫入後 flush

    lookback_days: 寫入最近 N 個「交易日」的指標（以 DB 中 DailyPrice 有記錄的日期為交易日）
    """
    max_read_window = 500

    trading_dates = list(
        DailyPrice.objects
        .dates('date', 'day', order='DESC')
        .distinct()
    )

    if not trading_dates:
        print("DB 中沒有任何股價資料。")
        return

    total_trading_days = len(trading_dates)
    latest_trading_day = trading_dates[0]

    write_idx = min(lookback_days - 1, total_trading_days - 1)
    write_cutoff = trading_dates[write_idx]

    read_idx = min(max_read_window + lookback_days - 1, total_trading_days - 1)
    cutoff_date = trading_dates[read_idx]

    print(
        f"計算技術指標 (最近交易日: {latest_trading_day}, "
        f"寫入最近 {lookback_days} 個交易日, "
        f"讀取回溯 {max_read_window + lookback_days} 個交易日, "
        f"cutoff: {cutoff_date})..."
    )

    stock_ids = list(set(
        DailyPrice.objects.filter(date__gte=cutoff_date)
        .values_list('stock_id', flat=True)
    ))
    total_stocks = len(stock_ids)
    print(f"共有 {total_stocks} 支股票需要計算")

    if total_stocks == 0:
        print("沒有符合日期的股價資料可計算。")
        return

    Indicator.objects.filter(date__gte=write_cutoff).delete()
    print(f"已清除 {write_cutoff} 之後的舊指標資料。")

    print("開始計算技術指標 (每 100 支股票分批)...")

    total_written = 0
    batch_size = 100

    for start_idx in range(0, total_stocks, batch_size):
        end_idx = min(start_idx + batch_size, total_stocks)
        current_batch_ids = stock_ids[start_idx:end_idx]

        prices = DailyPrice.objects.filter(
            stock_id__in=current_batch_ids,
            date__gte=cutoff_date
        ).values('stock_id', 'date', 'close').order_by('stock_id', 'date')

        df = pd.DataFrame(list(prices))

        if df.empty:
            continue

        indicator_batch = []

        grouped = df.groupby('stock_id')
        for stock_id, group in grouped:
            group = group.set_index('date').sort_index()
            close = group['close'].astype(float)

            ema20 = close.ewm(span=20, adjust=False).mean()
            ema60 = close.ewm(span=60, adjust=False).mean()
            ema120 = close.ewm(span=120, adjust=False).mean()
            sma20 = close.rolling(window=20).mean()
            sma60 = close.rolling(window=60).mean()
            sma120 = close.rolling(window=120).mean()
            daily_return = (close / close.shift(1) - 1) * 100

            valid_dates = close.index[close.index >= write_cutoff]

            for d in valid_dates:
                ind = Indicator(
                    stock_id=stock_id,
                    date=d,
                    ema20=round(ema20[d], 2) if pd.notna(ema20.get(d)) else None,
                    ema60=round(ema60[d], 2) if pd.notna(ema60.get(d)) else None,
                    ema120=round(ema120[d], 2) if pd.notna(ema120.get(d)) else None,
                    sma20=round(sma20[d], 2) if pd.notna(sma20.get(d)) else None,
                    sma60=round(sma60[d], 2) if pd.notna(sma60.get(d)) else None,
                    sma120=round(sma120[d], 2) if pd.notna(sma120.get(d)) else None,
                    daily_return=round(daily_return[d], 2) if pd.notna(daily_return.get(d)) else None,
                )
                indicator_batch.append(ind)

        if indicator_batch:
            Indicator.objects.bulk_create(indicator_batch, batch_size=5000, ignore_conflicts=True)
            total_written += len(indicator_batch)

        print(f"已處理 {end_idx}/{total_stocks} 支股票，寫入 {total_written} 筆。")

    print(f"技術指標計算完成！共寫入 {total_written} 筆 ({total_stocks} 支股票)。")
