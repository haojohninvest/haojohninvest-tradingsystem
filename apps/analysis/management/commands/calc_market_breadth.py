"""
計算大盤 Market Breadth (前300大權值股站上EMA20的比例)

使用方式:
    # 初次佈建: 從 2020-01-01 全量計算
    python manage.py calc_market_breadth --full

    # 每日排程: 只更新最近 N 天
    python manage.py calc_market_breadth --days 7
"""

from django.core.management.base import BaseCommand
from datetime import date, timedelta
import pandas as pd
from django.db.models import Max
from django.db import transaction
from apps.market_data.models import DailyPrice
from apps.analysis.models import Indicator, MarketBreadth
from apps.analysis.calculation_utils import load_price_data_with_market_cap


class Command(BaseCommand):
    help = '計算大盤 Market Breadth，寫入 MarketBreadth table'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='更新最近 N 天 (預設 7，給每日排程用)'
        )
        parser.add_argument(
            '--full',
            action='store_true',
            help='全量重算，從 2020-01-01 至今 (給初次佈建用)'
        )

    def handle(self, *args, **options):
        days = options['days']
        full = options['full']

        latest_date = DailyPrice.objects.aggregate(m=Max('date'))['m']
        if not latest_date:
            self.stdout.write(self.style.ERROR("DailyPrice 沒有任何資料，中止。"))
            return

        if full:
            cutoff_date = date(2020, 1, 1)
            self.stdout.write(f"全量重算: 2020-01-01 ~ {latest_date}")
        else:
            cutoff_date = latest_date - timedelta(days=days)
            self.stdout.write(f"更新最近 {days} 天: {cutoff_date} ~ {latest_date}")

        # 1. 讀取價格資料 (已含股數與市值)
        df = load_price_data_with_market_cap(cutoff_date)
        if df.empty:
            self.stdout.write(self.style.WARNING("沒有符合日期的價格資料。"))
            return

        self.stdout.write(f"共讀取 {len(df)} 筆價格資料。")

        # 2. 讀取 Indicator.ema20
        indicators = Indicator.objects.filter(
            date__gte=cutoff_date
        ).values('date', 'stock_id', 'ema20')
        df_ind = pd.DataFrame(list(indicators))

        if df_ind.empty:
            self.stdout.write(self.style.ERROR("沒有 Indicator 資料，請先執行 calc_indicators。"))
            return

        df_ind['ema20'] = pd.to_numeric(df_ind['ema20'], errors='coerce')

        # 3. 合併並篩選
        df_mb = pd.merge(df, df_ind, on=['date', 'stock_id'])
        df_mb = df_mb[df_mb['market_cap'] > 0].dropna(subset=['ema20', 'close'])

        self.stdout.write(f"合併後有效資料: {len(df_mb)} 筆。")

        # 4. 每天挑選前 300 大市值
        top_300 = df_mb.sort_values(
            ['date', 'market_cap'], ascending=[True, False]
        ).groupby('date').head(300)

        # 5. 計算 breadth_percent
        top_300['above_20ma'] = top_300['close'] > top_300['ema20']
        breadth = top_300.groupby('date').agg(
            above=('above_20ma', 'sum'),
            total=('stock_id', 'count')
        ).reset_index()
        breadth['breadth_percent'] = (breadth['above'] / breadth['total'] * 100).round(2)

        self.stdout.write(f"共計算 {len(breadth)} 天的 Market Breadth。")

        # 6. 寫入 MarketBreadth table
        records = []
        for _, row in breadth.iterrows():
            records.append(MarketBreadth(
                date=row['date'],
                breadth_percent=row['breadth_percent']
            ))

        with transaction.atomic():
            if full:
                MarketBreadth.objects.all().delete()
            else:
                dates_to_replace = breadth['date'].tolist()
                MarketBreadth.objects.filter(date__in=dates_to_replace).delete()

            batch_size = 5000
            for i in range(0, len(records), batch_size):
                MarketBreadth.objects.bulk_create(records[i:i+batch_size])

        self.stdout.write(self.style.SUCCESS(
            f"Market Breadth 計算完成！共寫入 {len(records)} 筆。"
        ))
