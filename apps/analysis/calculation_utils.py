import pandas as pd
from apps.market_data.models import DailyPrice, StockSharesHistory
from apps.sectors.models import StockSector


def get_shares_for_date(stock_id, target_date):
    """
    根據 target_date 找適用的股數（StockSharesHistory）
    Fallback：該季 → 上一季 → 更舊季 → 0
    """
    shares_record = StockSharesHistory.objects.filter(
        stock_id=stock_id,
        date__lte=target_date
    ).order_by('-date').first()

    if shares_record and shares_record.outstanding_shares:
        return shares_record.outstanding_shares

    return 0


def load_price_data_with_market_cap(cutoff_date):
    """
    讀取 DailyPrice + 匹配 StockSharesHistory 股數 + 合併 StockSector

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

    shares_cache = {}
    unique_pairs = df_prc[['date', 'stock_id']].drop_duplicates()

    for _, row in unique_pairs.iterrows():
        key = (row['stock_id'], row['date'])
        if key not in shares_cache:
            shares_cache[key] = get_shares_for_date(row['stock_id'], row['date'])

    df_prc['outstanding_shares'] = df_prc.apply(
        lambda r: shares_cache.get((r['stock_id'], r['date']), 0), axis=1
    )

    df = pd.merge(df_prc, df_sec, on='stock_id', how='left')
    df['sector__name'] = df['sector__name'].fillna('未分類')
    df['market_cap'] = df['close'] * df['outstanding_shares']

    return df
