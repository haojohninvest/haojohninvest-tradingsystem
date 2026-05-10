"""
標誌性動作偵測模組
偵測三種技術訊號：
1. 上漲 > 7% - 單日漲幅超過 7%
2. 跳空缺口 - 今日最低 > 昨日最高（標準定義）
3. 大量 - 成交量 > 20 日均量 × 3
"""
import pandas as pd
from apps.market_data.models import DailyPrice
from django.utils import timezone
from datetime import timedelta


def detect_price_surge(prices_df, threshold=7.0):
    """
    偵測上漲 > 7% 的次數
    
    Args:
        prices_df: DataFrame，包含 date, close, volume 等欄位，已依日期排序
        threshold: 漲幅門檻，預設 7%
    
    Returns:
        int: 訊號出現次數
    """
    if len(prices_df) < 2:
        return 0
    
    # 計算每日漲跌幅
    prices_df = prices_df.copy()
    prices_df['daily_return'] = prices_df['close'].pct_change() * 100
    
    # 偵測漲幅 > 7%
    surge_signals = prices_df['daily_return'] > threshold
    
    return int(surge_signals.sum())


def detect_gap_up(prices_df):
    """
    偵測跳空缺口（標準定義：今日最低 > 昨日最高）
    
    Args:
        prices_df: DataFrame，包含 date, high, low, close 等欄位，已依日期排序
    
    Returns:
        int: 訊號出現次數
    """
    if len(prices_df) < 2:
        return 0
    
    # 計算跳空缺口：今日低點 > 昨日高點
    gap_signals = prices_df['low'].iloc[1:].values > prices_df['high'].iloc[:-1].values
    
    return int(gap_signals.sum())


def detect_volume_spike(prices_df, multiplier=2, window=20):
    """
    偵測大量（成交量 > 20 日均量 × 2）
    
    Args:
        prices_df: DataFrame，包含 date, volume 等欄位，已依日期排序
        multiplier: 倍數門檻，預設 2 倍
        window: 移動平均窗口，預設 20 日
    
    Returns:
        int: 訊號出現次數
    """
    if len(prices_df) < window:
        return 0
    
    # 計算 20 日移動均量
    prices_df = prices_df.copy()
    prices_df['avg_volume_20'] = prices_df['volume'].rolling(window=window).mean()
    
    # 偵測大量：成交量 > 20 日均量 × 2
    volume_signals = prices_df['volume'] > (prices_df['avg_volume_20'] * multiplier)
    
    # 排除前 window-1 天（因為均量還未穩定）
    return int(volume_signals.iloc[window-1:].sum())


def detect_all_signals(stock_id, days=20, end_date=None):
    """
    偵測某支股票的所有標誌性動作
    
    Args:
        stock_id: 股票 ID
        days: 偵測天數，預設 20 交易日
        end_date: 結束日期，預設為最新交易日
    
    Returns:
        dict: {
            'surge_count': 上漲>7% 次數，
            'gap_count': 跳空缺口次數，
            'volume_count': 大量次數（成交量 > 2 日均量 × 2）,
        }
    """
    from django.db.models import Max
    
    # 如果沒有指定結束日期，使用資料庫最新日期
    if end_date is None:
        latest = DailyPrice.objects.aggregate(max_date=Max('date'))['max_date']
        if latest is None:
            return {'surge_count': 0, 'gap_count': 0, 'volume_count': 0}
        end_date = latest
    
    # 計算開始日期（粗略估計，實際會再過濾）
    start_date = end_date - timedelta(days=days * 2)  # 多抓一些天數確保有足夠交易日
    
    # 撈取股價資料
    prices_qs = DailyPrice.objects.filter(
        stock_id=stock_id,
        date__gte=start_date,
        date__lte=end_date
    ).order_by('date').values('date', 'open', 'high', 'low', 'close', 'volume')
    
    if len(prices_qs) < 2:
        return {'surge_count': 0, 'gap_count': 0, 'volume_count': 0}
    
    # 轉為 DataFrame
    prices_df = pd.DataFrame(list(prices_qs))
    
    # 確保日期是 datetime 類型
    prices_df['date'] = pd.to_datetime(prices_df['date'])
    
    # 只取最近 N 個交易日
    prices_df = prices_df.tail(days)
    
    # 偵測所有訊號
    return {
        'surge_count': detect_price_surge(prices_df),
        'gap_count': detect_gap_up(prices_df),
        'volume_count': detect_volume_spike(prices_df),
    }


def get_signal_details(stock_id, days=20, end_date=None):
    """
    取得訊號的詳細日期資訊（用於展開詳情）
    
    Args:
        stock_id: 股票 ID
        days: 偵測天數
        end_date: 結束日期
    
    Returns:
        dict: {
            'surge_dates': [('2026-05-01', 8.5), ('2026-04-25', 7.2), ...],
            'gap_dates': ['2026-04-28', ...],
            'volume_dates': [('2026-05-03', 3.5), ('2026-04-20', 4.2), ...],
        }
    """
    from django.db.models import Max
    from datetime import timedelta
    
    # 如果沒有指定結束日期，使用資料庫最新日期
    if end_date is None:
        latest = DailyPrice.objects.aggregate(max_date=Max('date'))['max_date']
        if latest is None:
            return {'surge_dates': [], 'gap_dates': [], 'volume_dates': []}
        end_date = latest
    
    # 計算開始日期
    start_date = end_date - timedelta(days=days * 2)
    
    # 撈取股價資料（需要昨天的資料來計算漲跌幅和跳空）
    prices_qs = DailyPrice.objects.filter(
        stock_id=stock_id,
        date__gte=start_date,
        date__lte=end_date
    ).order_by('date').values('date', 'open', 'high', 'low', 'close', 'volume')
    
    if len(prices_qs) < 2:
        return {'surge_dates': [], 'gap_dates': [], 'volume_dates': []}
    
    prices_df = pd.DataFrame(list(prices_qs))
    prices_df['date'] = pd.to_datetime(prices_df['date'])
    prices_df = prices_df.tail(days)
    
    # 計算漲跌幅
    prices_df['daily_return'] = prices_df['close'].pct_change() * 100
    
    # 計算 20 日移動均量
    prices_df['avg_volume_20'] = prices_df['volume'].rolling(window=20).mean()
    
    # 上漲 > 7% 的日期
    surge_dates = []
    for idx, row in prices_df.iterrows():
        if pd.notna(row['daily_return']) and row['daily_return'] > 7:
            surge_dates.append((row['date'].strftime('%Y-%m-%d'), round(row['daily_return'], 2)))
    
    # 跳空缺口的日期
    gap_dates = []
    for i in range(1, len(prices_df)):
        prev_row = prices_df.iloc[i-1]
        curr_row = prices_df.iloc[i]
        if curr_row['low'] > prev_row['high']:
            gap_dates.append(curr_row['date'].strftime('%Y-%m-%d'))
    
    # 大量的日期
    volume_dates = []
    for idx, row in prices_df.iterrows():
        if pd.notna(row['avg_volume_20']) and row['volume'] > (row['avg_volume_20'] * 3):
            ratio = round(row['volume'] / row['avg_volume_20'], 1)
            volume_dates.append((row['date'].strftime('%Y-%m-%d'), ratio))
    
    return {
        'surge_dates': surge_dates,
        'gap_dates': gap_dates,
        'volume_dates': volume_dates,
    }
