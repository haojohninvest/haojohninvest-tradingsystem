import pandas as pd
from django.db import transaction
from datetime import date, timedelta
from .models import Stock, DailyPrice
from apps.analysis.models import Indicator
import logging

logger = logging.getLogger(__name__)

def calculate_all_indicators(lookback_days=150):
    """
    計算所有股票的技術指標 (EMA, SMA, 偏離率, 漲跌幅)
    並將結果寫入 Indicator 模型
    
    優化：只抓取 lookback_days (預設150天) 的資料進行計算，
          減少記憶體使用量。圖表只需要顯示150天。
    
    Args:
        lookback_days: 回溯計算的天數。預設 150，給 EMA120 足夠的歷史。
                        若需算更久（如首次跑或圖表改顯示更久），可調大。
    """
    cutoff_date = date.today() - timedelta(days=lookback_days + 20)
    # 多抓 20 天緩衝，確保 EMA/SMA 前幾天的值不會變 NaN
    
    print(f"開始讀取最近 {lookback_days} 天的歷史股價資料 ( cutoff: {cutoff_date} )...")
    
    prices = DailyPrice.objects.filter(
        date__gte=cutoff_date
    ).values('stock_id', 'date', 'close').order_by('stock_id', 'date')
    
    if not prices.exists():
        print("沒有符合日期的股價資料可計算。")
        return
    
    df = pd.DataFrame(list(prices))
    print(f"共讀取 {len(df)} 筆價格資料，涵蓋 {df['stock_id'].nunique()} 支股票。")
    
    # 建立計算結果的暫存列表
    indicators_to_create = []
    indicators_to_update = {}  # (stock_id, date) -> Indicator instance
    
    # 先撈出這段期間已經有的舊 Indicator（避免重複寫入）
    existing = Indicator.objects.filter(
        date__gte=cutoff_date
    ).values_list('stock_id', 'date')
    existing_set = set(existing)
    
    print("開始計算技術指標 (分批處理，記憶體友善)...")
    
    # 按股票分組計算
    grouped = df.groupby('stock_id')
    
    for stock_id, group in grouped:
        group = group.set_index('date').sort_index()
        close = group['close'].astype(float)
        
        # 均線 (EMA)
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema60 = close.ewm(span=60, adjust=False).mean()
        ema120 = close.ewm(span=120, adjust=False).mean()
        
        # 均線 (SMA)
        sma20 = close.rolling(window=20).mean()
        sma60 = close.rolling(window=60).mean()
        sma120 = close.rolling(window=120).mean()
        
        # 漲跌率
        daily_return = (close / close.shift(1) - 1) * 100
        
        # 偏離率
        ema20_dev = (close - ema20) / ema20 * 100
        ema60_dev = (close - ema60) / ema60 * 100
        ema120_dev = (close - ema120) / ema120 * 100
        
        # 只取 cutoff_date 之後的日期寫入（去掉前面 20 天緩衝）
        valid_dates = close.index[close.index >= cutoff_date + timedelta(days=20)]
        
        for d in valid_dates:
            key = (stock_id, pd.Timestamp(d).date())
            if key in existing_set:
                continue  # 已有舊資料，跳過（日後可改 update）
            
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
                ema20_dev=round(ema20_dev[d], 2) if pd.notna(ema20_dev.get(d)) else None,
                ema60_dev=round(ema60_dev[d], 2) if pd.notna(ema60_dev.get(d)) else None,
                ema120_dev=round(ema120_dev[d], 2) if pd.notna(ema120_dev.get(d)) else None,
            )
            indicators_to_create.append(ind)
    
    if not indicators_to_create:
        print("沒有新的技術指標需要寫入（可能都已計算過）。")
        return
    
    print(f"準備寫入 {len(indicators_to_create)} 筆新技術指標...")
    with transaction.atomic():
        batch_size = 5000
        for i in range(0, len(indicators_to_create), batch_size):
            Indicator.objects.bulk_create(
                indicators_to_create[i:i+batch_size],
                ignore_conflicts=True  # 若有重複 key 直接忽略
            )
            print(f"已寫入 {min(i+batch_size, len(indicators_to_create))} / {len(indicators_to_create)}...")
            
    print("技術指標計算並寫入完成！")
