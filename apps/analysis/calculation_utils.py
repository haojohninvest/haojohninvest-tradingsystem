import pandas as pd
from apps.market_data.models import DailyPrice, StockSharesHistory
from apps.sectors.models import StockSector
import bisect


def _build_shares_lookup():
    """
    一次性載入所有 StockSharesHistory，建立記憶體查找表。
    回傳 dict: stock_id -> [(date, shares), ...] (按日期升序)
    """
    records = StockSharesHistory.objects.values(
        'stock_id', 'date', 'outstanding_shares'
    ).order_by('stock_id', 'date')

    lookup = {}
    for rec in records:
        sid = rec['stock_id']
        if sid not in lookup:
            lookup[sid] = []
        lookup[sid].append((rec['date'], rec['outstanding_shares'] or 0))
    return lookup


def get_shares_for_date(lookup, stock_id, target_date):
    """
    從記憶體 lookup 查找 target_date 適用的股數。
    Fallback：該季 → 上一季 → 更舊季 → 0
    """
    entries = lookup.get(stock_id, [])
    if not entries:
        return 0

    # entries 已按日期升序，用二分搜尋找最後一個 <= target_date
    dates = [e[0] for e in entries]
    idx = bisect.bisect_right(dates, target_date) - 1
    if idx >= 0:
        return entries[idx][1]
    return 0


def load_price_data_with_market_cap(cutoff_date):
    """
    讀取 DailyPrice + 匹配 StockSharesHistory 股數 + 合併 StockSector
    優化版：一次性預載 shares，避免 N+1 查詢

    Args:
        cutoff_date: 資料起始日期

    Returns:
        DataFrame with columns [date, stock_id, close, sector__name, market_cap, outstanding_shares]
    """
    prices = DailyPrice.objects.filter(
        date__gte=cutoff_date
    ).values('date', 'stock_id', 'close').order_by('date')

    sectors = StockSector.objects.select_related('sector').values('stock_id', 'sector__name')

    if not prices.exists():
        return pd.DataFrame()

    df_prc = pd.DataFrame(list(prices))
    df_sec = pd.DataFrame(list(sectors))
    df_prc['close'] = df_prc['close'].astype(float)

    # OPTIMIZED: 一次性預載所有 shares，避免 N+1 查詢
    print(f"  [load_price_data] 預載 StockSharesHistory...")
    shares_lookup = _build_shares_lookup()
    print(f"  [load_price_data] 預載完成，{len(shares_lookup)} 支股票有股數資料。")

    df_prc['outstanding_shares'] = df_prc.apply(
        lambda r: get_shares_for_date(shares_lookup, r['stock_id'], r['date']), axis=1
    )

    df = pd.merge(df_prc, df_sec, on='stock_id', how='left')
    df['sector__name'] = df['sector__name'].fillna('未分類')
    df['market_cap'] = df['close'] * df['outstanding_shares']

    return df


# 保留舊函數名稱以便向後相容
__all__ = ['get_shares_for_date', 'load_price_data_with_market_cap', '_build_shares_lookup']
