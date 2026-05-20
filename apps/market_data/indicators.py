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
    並將結果寫入 Indicator 模型（刪除目標區間 → 重寫，每 200 支股票分批 flush）
    """
    cutoff_date = date.today() - timedelta(days=lookback_days + 20)
    write_cutoff = cutoff_date + timedelta(days=20)

    print(f"計算技術指標 (回溯 {lookback_days} 天, cutoff: {cutoff_date})...")

    prices = DailyPrice.objects.filter(
        date__gte=cutoff_date
    ).values('stock_id', 'date', 'close').order_by('stock_id', 'date')

    if not prices.exists():
        print("沒有符合日期的股價資料可計算。")
        return

    df = pd.DataFrame(list(prices))
    print(f"共讀取 {len(df)} 筆價格資料，涵蓋 {df['stock_id'].nunique()} 支股票。")

    # 先刪除目標區間的舊資料
    Indicator.objects.filter(date__gte=write_cutoff).delete()
    print(f"已清除 {write_cutoff} 之後的舊指標資料。")

    print("開始計算技術指標 (每 200 支股票分批寫入)...")

    grouped = df.groupby('stock_id')
    indicator_batch = []
    stock_count = 0
    total_written = 0

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

        stock_count += 1

        if stock_count % 200 == 0:
            Indicator.objects.bulk_create(indicator_batch)
            total_written += len(indicator_batch)
            print(f"已寫入 {total_written} 筆 ({stock_count} 支股票)...")
            indicator_batch = []

    if indicator_batch:
        Indicator.objects.bulk_create(indicator_batch)
        total_written += len(indicator_batch)

    print(f"技術指標計算完成！共寫入 {total_written} 筆 ({stock_count} 支股票)。")
