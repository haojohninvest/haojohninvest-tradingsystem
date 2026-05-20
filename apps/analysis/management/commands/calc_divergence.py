"""
重算 Sector Divergence (族群乖離與燈號)，並存入快取資料表

優化：預設只算最近 180 天（約半年），大幅減少記憶體需求。
重大修改：
1. Market Breadth 已拆分至 calc_market_breadth command
2. 市值計算改用 StockSharesHistory 季度股數
3. 共用資料讀取邏輯移至 calculation_utils
"""

from django.core.management.base import BaseCommand
from datetime import timedelta
import pandas as pd
from django.db.models import Max
from django.db import transaction
from apps.market_data.models import DailyPrice
from apps.analysis.models import SectorDivergence
from apps.analysis.calculation_utils import load_price_data_with_market_cap


def consecutive_ge_n(mask_series, n=2):
    b = mask_series.fillna(False).astype(bool)
    grp = (b != b.shift()).cumsum()
    run_pos = b.groupby(grp).cumcount() + 1
    return b & (run_pos >= n)


class Command(BaseCommand):
    help = '重算 Sector Divergence (族群乖離與燈號)，預設只算最近180天'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=180,
            help='回溯計算天數 (預設 180，約半年)'
        )
        parser.add_argument(
            '--full',
            action='store_true',
            help='全量重算所有歷史 (會刪除舊 Divergence)'
        )

    def handle(self, *args, **options):
        days = options['days']
        full = options['full']

        latest_date = DailyPrice.objects.aggregate(m=Max('date'))['m']
        if not latest_date:
            self.stdout.write(self.style.ERROR("DailyPrice 沒有任何資料，中止。"))
            return

        cutoff_date = latest_date - timedelta(days=days + 20)

        self.stdout.write(
            f"開始讀取資料 (最近交易日: {latest_date}, 回溯 {days} 天, cutoff: {cutoff_date})..."
        )

        # 1. 使用共用模組讀取價格資料 (已含股數、市值、sector)
        df = load_price_data_with_market_cap(cutoff_date)
        if df.empty:
            self.stdout.write(self.style.WARNING("沒有符合日期的股價資料，中止運算。"))
            return

        self.stdout.write(f"共讀取 {len(df)} 筆價格資料。")

        self.stdout.write("正在計算族群 EMA20 乖離率...")

        # 2. 每天每個族群的總市值
        sector_mc = df.groupby(['date', 'sector__name'])['market_cap'].sum().unstack(fill_value=0)

        # 3. 計算 EMA20 與乖離率
        ema20 = sector_mc.ewm(span=20, adjust=False).mean()
        divergence = ((sector_mc - ema20) / ema20 * 100)

        # 4. 計算排名與燈號
        self.stdout.write("正在判定橘燈(連兩天前五)與紫燈(由負轉正)...")
        sectors_only = divergence.columns.tolist()
        rank_by_day = divergence[sectors_only].rank(axis=1, method='min', ascending=False)
        is_top5 = (rank_by_day <= 5)

        results_to_create = []

        for sector in sectors_only:
            s_div = divergence[sector]
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
                SectorDivergence.objects.filter(date__gte=cutoff_date).delete()

            batch_size = 5000
            for i in range(0, len(results_to_create), batch_size):
                SectorDivergence.objects.bulk_create(results_to_create[i:i+batch_size])

        self.stdout.write(self.style.SUCCESS("族群背離計算完成！"))
