"""掃描 2020-01-01 ~ 今天的 DailyPrice，找出異常日期

規則：
1. 任何股票 |daily_return| > 20%（台股正常 ±10%，>20% 一定是錯誤資料）
2. 當天總股票數 < 500 支（正常約 1800 支）

輸出：可疑日期清單，供 fix_bad_dates 使用。
"""

from django.core.management.base import BaseCommand
from datetime import date
import pandas as pd
from apps.market_data.models import DailyPrice


class Command(BaseCommand):
    help = '掃描 DailyPrice 找出異常日期（極端漲跌幅 / 股票數過少）'

    def handle(self, *args, **options):
        cutoff = date(2020, 1, 1)

        self.stdout.write(f"讀取 {cutoff} ~ 今天的股價資料...")

        prices = DailyPrice.objects.filter(
            date__gte=cutoff
        ).values('stock_id', 'date', 'close').order_by('stock_id', 'date')

        if not prices.exists():
            self.stdout.write(self.style.ERROR("沒有 DailyPrice 資料。"))
            return

        df = pd.DataFrame(list(prices))
        df['close'] = df['close'].astype(float)
        df['date'] = pd.to_datetime(df['date'])

        self.stdout.write(f"共讀取 {len(df)} 筆資料，正在計算逐日漲跌幅...")

        # 逐支股票算 daily_return
        bad_dates_by_return = set()
        grouped = df.groupby('stock_id')

        for sid, group in grouped:
            group = group.sort_values('date')
            group['daily_return'] = (group['close'] / group['close'].shift(1) - 1) * 100
            abnormal = group[group['daily_return'].abs() > 20]
            for d in abnormal['date']:
                bad_dates_by_return.add(d.date())

        self.stdout.write(f"因 |日報酬| > 20% 發現 {len(bad_dates_by_return)} 個可疑日期。")

        # 每天股票數量異常
        daily_counts = df.groupby('date')['stock_id'].nunique()
        low_count_dates = set(daily_counts[daily_counts < 500].index)
        low_count_dates = {d.date() if hasattr(d, 'date') else d for d in low_count_dates}

        self.stdout.write(f"因股票數 < 500 發現 {len(low_count_dates)} 個可疑日期。")

        # 合併
        all_bad_dates = sorted(bad_dates_by_return | low_count_dates)

        self.stdout.write("")
        self.stdout.write("=" * 50)

        if not all_bad_dates:
            self.stdout.write(self.style.SUCCESS("沒有發現可疑日期！資料品質良好。"))
        else:
            self.stdout.write(self.style.WARNING(f"共發現 {len(all_bad_dates)} 個可疑日期："))
            for d in all_bad_dates:
                tag = ""
                if d in bad_dates_by_return:
                    tag += " [極端漲跌]"
                if d in low_count_dates:
                    tag += " [股票數少]"
                self.stdout.write(f"  {d}{tag}")

            self.stdout.write("")
            self.stdout.write(f"預計修復時間：約 {len(all_bad_dates) * 5} 秒 (~{len(all_bad_dates) * 5 / 60:.0f} 分鐘)")
            self.stdout.write("執行修復：python manage.py fix_bad_dates")

        self.stdout.write("=" * 50)
