"""
重算所有歷史資料的 Sector Divergence (族群乖離與燈號)，並存入快取資料表

重大修改：
1. Market Breadth 改用 EMA20（原為 SMA20）
2. 市值計算改用 StockSharesHistory 季度股數（原為 Stock.outstanding_shares）
"""

from django.core.management.base import BaseCommand
import pandas as pd
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
    help = '重算所有歷史資料的 Sector Divergence (族群乖離與燈號)，並存入快取資料表'

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
        self.stdout.write("開始讀取歷史股價資料...")
        
        # 1. 取出所需的原始資料
        prices = DailyPrice.objects.all().values('date', 'stock_id', 'close')
        sectors = StockSector.objects.select_related('sector').values('stock_id', 'sector__name')
        
        if not prices:
            self.stdout.write(self.style.WARNING("沒有股價資料，中止運算。"))
            return

        df_prc = pd.DataFrame(list(prices))
        df_sec = pd.DataFrame(list(sectors))

        # 型態轉換
        df_prc['close'] = df_prc['close'].astype(float)

        self.stdout.write("正在根據日期匹配歷史股數 (StockSharesHistory)...")
        
        # 2. 為每個 (date, stock) 找適用的股數
        # 建立快取字典，避免重複查詢
        shares_cache = {}
        unique_pairs = df_prc[['date', 'stock_id']].drop_duplicates()
        
        for _, row in unique_pairs.iterrows():
            key = (row['stock_id'], row['date'])
            if key not in shares_cache:
                shares_cache[key] = self.get_shares_for_date(row['stock_id'], row['date'])
        
        # 應用到 DataFrame
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
        
        # ★ 新增：計算大盤 Market Breadth (前 200 大權值股) 使用 EMA20
        self.stdout.write("正在計算大盤 Market Breadth (EMA20)...")
        indicators = Indicator.objects.all().values('date', 'stock_id', 'ema20')
        df_ind = pd.DataFrame(list(indicators))
        
        if not df_ind.empty:
            df_ind['ema20'] = pd.to_numeric(df_ind['ema20'], errors='coerce')
            df_mb = pd.merge(df, df_ind, on=['date', 'stock_id'])
            df_mb = df_mb[df_mb['market_cap'] > 0].dropna(subset=['ema20', 'close'])
            
            # 取每天市值前 200 大
            top_200 = df_mb.sort_values(['date', 'market_cap'], ascending=[True, False]).groupby('date').head(200)
            top_200['above_20ma'] = top_200['close'] > top_200['ema20']
            breadth = top_200.groupby('date').agg(above=('above_20ma', 'sum'), total=('stock_id', 'count')).reset_index()
            breadth['breadth_percent'] = breadth['above'] / breadth['total'] * 100
            breadth = breadth.set_index('date')
            
            # 把算好的大盤塞進 divergence DataFrame 裡，偽裝成一個族群
            divergence['__MARKET_BREADTH__'] = breadth['breadth_percent']
        else:
            self.stdout.write(self.style.WARNING("沒有 Indicator 資料，Market Breadth 設為 0"))
            divergence['__MARKET_BREADTH__'] = 0

        # 6. 計算排名與燈號
        self.stdout.write("正在判定橘燈(連兩天前五)與紫燈(由負轉正)...")
        # 排除掉 __MARKET_BREADTH__ 再去排名，才不會干擾族群名次
        sectors_only = [c for c in divergence.columns if c != '__MARKET_BREADTH__']
        rank_by_day = divergence[sectors_only].rank(axis=1, method='min', ascending=False)
        is_top5 = (rank_by_day <= 5)
        
        results_to_create = []
        
        # 迴圈處理每一個族群 (包含大盤)，計算每一天的燈號
        for sector in divergence.columns:
            s_div = divergence[sector]
            
            if sector == '__MARKET_BREADTH__':
                # 大盤不需要亮燈
                cond_orange = pd.Series(False, index=s_div.index)
                cond_pink = pd.Series(False, index=s_div.index)
            else:
                # 橘燈條件：連續2天排名前5
                cond_orange = consecutive_ge_n(is_top5[sector], n=2)
                # 紫燈條件：昨天<0, 今天>0, 明天>0
                cond_pink = (s_div.shift(1) < 0) & (s_div > 0) & (s_div.shift(-1) > 0)
            
            # 打包該族群所有日期的結果
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

        self.stdout.write(f"準備寫入 {len(results_to_create)} 筆族群背離紀錄到快取資料庫...")
        
        with transaction.atomic():
            SectorDivergence.objects.all().delete() # 清空舊資料
            batch_size = 5000
            for i in range(0, len(results_to_create), batch_size):
                SectorDivergence.objects.bulk_create(results_to_create[i:i+batch_size])
                
        self.stdout.write(self.style.SUCCESS("全部族群歷史背離與燈號計算完成！(0.1秒極速視圖已準備就緖)"))
        self.stdout.write(self.style.SUCCESS(f"本次使用 StockSharesHistory 季度股數計算市值，共 {len(shares_cache)} 筆股數匹配。"))
