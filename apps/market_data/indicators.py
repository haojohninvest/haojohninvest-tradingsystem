import pandas as pd
from django.db import transaction
from datetime import date, timedelta
from .models import DailyPrice
from apps.analysis.models import Indicator
import logging

logger = logging.getLogger(__name__)


def calculate_all_indicators(lookback_days=14):
    """
    計算所有股票的技術指標 (EMA, SMA, 漲跌幅)
    優化版：分批讀取 + 向量計算 + bulk_create + 每批寫入後 flush
    """
    cutoff_date = date.today() - timedelta(days=lookback_days + 20)
    write_cutoff = cutoff_date + timedelta(days=20)

    print(f"計算技術指標 (回溯 {lookback_days} 天, cutoff: {cutoff_date})...")

    # PATCH: 只列出需要的股票 ID，避免一次載入全部
    stock_ids = list(set(
        DailyPrice.objects.filter(date__gte=cutoff_date)
        .values_list('stock_id', flat=True)
    ))
    total_stocks = len(stock_ids)
    print(f"共有 {total_stocks} 支股票需要計算")

    if total_stocks == 0:
        print("沒有符合日期的股價資料可計算。")
        return

    # 先刪除目標區間的舊資料
    Indicator.objects.filter(date__gte=write_cutoff).delete()
    print(f"已清除 {write_cutoff} 之後的舊指標資料。")

    print("開始計算技術指標 (每 100 支股票分批)...")

    total_written = 0
    batch_size = 100  # PATCH: 每次只處理 100 支股票，降低記憶體

    for start_idx in range(0, total_stocks, batch_size):
        end_idx = min(start_idx + batch_size, total_stocks)
        current_batch_ids = stock_ids[start_idx:end_idx]

        # PATCH: 分批讀取，而不是一次全讀
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

            # 向量計算，一次完成
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

        # PATCH: 每批寫入後立刻 flush
        if indicator_batch:
            Indicator.objects.bulk_create(indicator_batch, batch_size=5000, ignore_conflicts=True)
            total_written += len(indicator_batch)

        print(f"已處理 {end_idx}/{total_stocks} 支股票，寫入 {total_written} 筆。")

    print(f"技術指標計算完成！共寫入 {total_written} 筆 ({total_stocks} 支股票)。")
