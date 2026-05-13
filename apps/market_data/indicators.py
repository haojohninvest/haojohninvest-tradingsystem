import pandas as pd
from django.db import transaction
from .models import Stock, DailyPrice
from apps.analysis.models import Indicator
import logging

logger = logging.getLogger(__name__)

def calculate_all_indicators():
    """
    計算所有股票的技術指標 (EMA, SMA, 偏離率, 漲跌幅)
    並將結果寫入 Indicator 模型
    """
    print("開始讀取歷史股價資料...")
    # 讀取全部資料並轉換成 Pandas DataFrame 進行向量化運算 (這樣最快)
    prices = DailyPrice.objects.all().values('stock_id', 'date', 'close')
    if not prices:
        print("沒有股價資料可計算。")
        return

    df = pd.DataFrame(list(prices))
    df = df.sort_values(['stock_id', 'date'])
    
    # 建立計算結果的暫存列表
    indicators_to_create = []
    
    print("開始計算技術指標 (這可能需要幾十秒到幾分鐘)...")
    
    # 按股票分組計算
    grouped = df.groupby('stock_id')
    
    for stock_id, group in grouped:
        group = group.set_index('date')
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
        
        # 準備寫入資料庫的物件
        for date, current_close in close.items():
            # 我們只需要最新有變動的，但為了完整性，批次建立
            ind = Indicator(
                stock_id=stock_id,
                date=date,
                ema20=round(ema20[date], 2) if pd.notna(ema20[date]) else None,
                ema60=round(ema60[date], 2) if pd.notna(ema60[date]) else None,
                ema120=round(ema120[date], 2) if pd.notna(ema120[date]) else None,
                sma20=round(sma20[date], 2) if pd.notna(sma20[date]) else None,
                sma60=round(sma60[date], 2) if pd.notna(sma60[date]) else None,
                sma120=round(sma120[date], 2) if pd.notna(sma120[date]) else None,
                daily_return=round(daily_return[date], 2) if pd.notna(daily_return[date]) else None,
                ema20_dev=round(ema20_dev[date], 2) if pd.notna(ema20_dev[date]) else None,
                ema60_dev=round(ema60_dev[date], 2) if pd.notna(ema60_dev[date]) else None,
                ema120_dev=round(ema120_dev[date], 2) if pd.notna(ema120_dev[date]) else None,
            )
            indicators_to_create.append(ind)

    # 批次刪除舊指標再重新寫入，確保資料一致且乾淨 (可優化為只更新最新一天)
    print(f"清空舊指標，準備寫入 {len(indicators_to_create)} 筆新技術指標...")
    with transaction.atomic():
        Indicator.objects.all().delete()
        
        # 因為資料可能很大，分批寫入 (每次 5000 筆)
        batch_size = 5000
        for i in range(0, len(indicators_to_create), batch_size):
            Indicator.objects.bulk_create(indicators_to_create[i:i+batch_size])
            print(f"已寫入 {min(i+batch_size, len(indicators_to_create))} / {len(indicators_to_create)}...")
            
    print("所有技術指標計算並寫入完成！")
