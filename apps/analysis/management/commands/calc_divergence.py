"""
重算 Sector Divergence (族群乖離與燈號)，並存入快取資料表

優化：預設只算最近 150 天，大幅減少記憶體需求。
重大修改：
1. Market Breadth 改用 EMA20（原為 SMA20）
2. 市值計算改用 StockSharesHistory 季度股數（原為 Stock.outstanding_shares）
"""

from django.core.management.base import BaseCommand
from datetime import timedelta
import pandas as pd
from django.db.models import Max
from apps.market_data.models import DailyPrice, Stock, StockSharesHistory
from apps.sectors.models import StockSector
from apps.analysis.models import SectorDivergence, Indicator
from django.db import transaction

def consecutive_ge_n(mask_series, n=2):
    b = mask_series.fillna(False).astype(bool)
    grp = (b != b.shift()).cumsum()
    run_pos = b.groupby(grp).cumcount() + 1
    return b & (run_pos >= n)

class Command(BaseCommand):
    help = '重算 Sector Divergence (族群乖離與燈號)，預設只算最近150天'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=150,
            help='回溯計算天數 (預設 150)'
        )
        parser.add_argument(
            '--full',
            action='store_true',
            help='全量重算所有歷史 (會刪除舊 Divergence)'
        )

    def get_shares_for_date(self, stock_id, target_date):
        """
        根據 target_date 找適用的股數（StockSharesHistory）
        Fallback：該季 → 上一季 → 更舊季 → 0
        """
        # 找 target_date 當天或之前的最新股數記錄
        shares_record = StockSharesHistory.objects.filter(
            stock_id=stock_id,
            date__lte=target_date
        ).order_by('-date').first()
        
        if shares_record and shares_record.outstanding_shares:
            return shares_record.outstanding_shares
        
        # 完全找不到，回傳 0（不會讓市值為 None）
        return 0

    def handle(self, *args, **options):
        # ---- 日期範圍設定 ----
        days = options['days']
        full = options['full']
        
        # 找 DB 中最新日期，若無則用今天
        latest_date = DailyPrice.objects.aggregate(m=Max('date'))['m']
        if not latest_date:
            self.stdout.write(self.style.ERROR("DailyPrice 沒有任何資料，中止。"))
            return
        
        cutoff_date = latest_date - timedelta(days=days + 20)
        
        self.stdout.write(
            f"開始讀取資料 (最近交易日: {latest_date}, 回溯 {days} 天, cutoff: {cutoff_date})..."
        )
        
        # 1. 只抓 cutoff 之後的原始資料
        prices = DailyPrice.objects.filter(
            date__gte=cutoff_date
        ).values('date', 'stock_id', 'close').order_by('date')
        
        sectors = StockSector.objects.select_related('sector').values('stock_id', 'sector__name')
        
        if not prices.exists():
            self.stdout.write(self.style.WARNING("沒有符合日期的股價資料，中止運算。"))
            return

        df_prc = pd.DataFrame(list(prices))
        df_sec = pd.DataFrame(list(sectors))
        df_prc['close'] = df_prc['close'].astype(float)

        self.stdout.write(f"共讀取 {len(df_prc)} 筆價格資料，正在匹配歷史股數...")
        
        # 2. 為每個 (date, stock) 找適用的股數
        shares_cache = {}
        unique_pairs = df_prc[['date', 'stock_id']].drop_duplicates()
        
        for _, row in unique_pairs.iterrows():
            key = (row['stock_id'], row['date'])
            if key not in shares_cache:
                shares_cache[key] = self.get_shares_for_date(row['stock_id'], row['date'])
        
        df_prc['outstanding_shares'] = df_prc.apply(
            lambda r: shares_cache.get((r['stock_id'], r['date']), 0), axis=1
        )
        
        # 3. 合併資料並計算各別股票市值
        df = pd.merge(df_prc, df_sec, on='stock_id', how='left')
        df['sector__name'] = df['sector__name'].fillna('未分類')
        df['market_cap'] = df['close'] * df['outstanding_shares']

        self.stdout.write("正在計算族群 EMA20 乖離率...")
        
        # 4. 每天每個族群的總市值
        sector_mc = df.groupby(['date', 'sector__name'])['market_cap'].sum().unstack(fill_value=0)
        
        # 5. 計算 EMA20 與乖離率
        ema20 = sector_mc.ewm(span=20, adjust=False).mean()
        divergence = ((sector_mc - ema20) / ema20 * 100)
        
        # ★ 計算大盤 Market Breadth (前 300 大權值股) 使用 EMA20
        self.stdout.write("正在計算大盤 Market Breadth (EMA20)...")
        indicators = Indicator.objects.filter(
            date__gte=cutoff_date
        ).values('date', 'stock_id', 'ema20')
        df_ind = pd.DataFrame(list(indicators))
        
        if not df_ind.empty:
            df_ind['ema20'] = pd.to_numeric(df_ind['ema20'], errors='coerce')
            df_mb = pd.merge(df, df_ind, on=['date', 'stock_id'])
            df_mb = df_mb[df_mb['market_cap'] > 0].dropna(subset=['ema20', 'close'])
            
            top_300 = df_mb.sort_values(
                ['date', 'market_cap'], ascending=[True, False]
            ).groupby('date').head(300)
            top_300['above_20ma'] = top_300['close'] > top_300['ema20']
            breadth = top_300.groupby('date').agg(
                above=('above_20ma', 'sum'),
                total=('stock_id', 'count')
            ).reset_index()
            breadth['breadth_percent'] = breadth['above'] / breadth['total'] * 100
            breadth = breadth.set_index('date')
            
            divergence['__MARKET_BREADTH__'] = breadth['breadth_percent']
        else:
            self.stdout.write(self.style.WARNING("沒有 Indicator 資料，Market Breadth 設為 0"))
            divergence['__MARKET_BREADTH__'] = 0

        # 6. 計算排名與燈號（只算 latest_date 前後需要的範圍即可）
        self.stdout.write("正在判定橘燈(連兩天前五)與紫燈(由負轉正)...")
        sectors_only = [c for c in divergence.columns if c != '__MARKET_BREADTH__']
        rank_by_day = divergence[sectors_only].rank(axis=1, method='min', ascending=False)
        is_top5 = (rank_by_day <= 5)
        
        results_to_create = []
        
        for sector in divergence.columns:
            s_div = divergence[sector]
            
            if sector == '__MARKET_BREADTH__':
                cond_orange = pd.Series(False, index=s_div.index)
                cond_pink = pd.Series(False, index=s_div.index)
            else:
                cond_orange = consecutive_ge_n(is_top5[sector], n=2)
                cond_pink = (s_div.shift(1) < 0) & (s_div > 0) & (s_div.shift(-1) > 0)
            
            for date_idx, val in s_div.items():
                if pd.notna(val):
                    results_to_create.append(
                        SectorDivergence(
                            date=date_idx,
                            sector_name=sector,
                            divergence=round(val, 2),
                            is_orange=bool(cond_orange.get(date_idx, False)),
                            is_pink=bool(cond_pink.get(date_idx, False))
                        )
                    )

        self.stdout.write(f"準備寫入 {len(results_to_create)} 筆族群背離紀錄...")
        
        with transaction.atomic():
            if full:
                SectorDivergence.objects.all().delete()
            else:
                # 只刪這段期間的舊資料，保留更早的（雖然圖表不顯示，但資料完整）
                SectorDivergence.objects.filter(date__gte=cutoff_date).delete()
            
            batch_size = 5000
            for i in range(0, len(results_to_create), batch_size):
                SectorDivergence.objects.bulk_create(results_to_create[i:i+batch_size])
                
        self.stdout.write(self.style.SUCCESS("族群背離計算完成！"))
        self.stdout.write(self.style.SUCCESS(f"本次使用 StockSharesHistory 季度股數計算市值，共 {len(shares_cache)} 筆股數匹配。"))
