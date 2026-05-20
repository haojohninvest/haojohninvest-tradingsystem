"""修復異常日期，逐一重抓股價（使用覆蓋模式）

使用方式：
    python manage.py fix_bad_dates --auto           # 自動偵測並修復
    python manage.py fix_bad_dates --date 2021-03-15 --date 2022-07-08  # 手動指定
"""

from django.core.management.base import BaseCommand
from datetime import date
import time
import pandas as pd
from apps.market_data.models import DailyPrice


def detect_bad_dates():
    cutoff = date(2020, 1, 1)
    prices = DailyPrice.objects.filter(
        date__gte=cutoff
    ).values('stock_id', 'date', 'close').order_by('stock_id', 'date')

    if not prices.exists():
        return []

    df = pd.DataFrame(list(prices))
    df['close'] = df['close'].astype(float)
    df['date'] = pd.to_datetime(df['date'])

    bad_dates = set()

    grouped = df.groupby('stock_id')
    for sid, group in grouped:
        group = group.sort_values('date')
        group['daily_return'] = (group['close'] / group['close'].shift(1) - 1) * 100
        abnormal = group[group['daily_return'].abs() > 20]
        for d in abnormal['date']:
            bad_dates.add(d.date())

    daily_counts = df.groupby('date')['stock_id'].nunique()
    low_count = daily_counts[daily_counts < 500]
    for d in low_count.index:
        bad_dates.add(d.date() if hasattr(d, 'date') else d)

    return sorted(bad_dates)


class Command(BaseCommand):
    help = '修復異常日期，重抓股價資料'

    def add_arguments(self, parser):
        parser.add_argument(
            '--auto',
            action='store_true',
            help='自動偵測後修復'
        )
        parser.add_argument(
            '--date',
            action='append',
            dest='dates',
            help='手動指定日期 YYYY-MM-DD (可多次使用)'
        )

    def handle(self, *args, **options):
        bad_dates = []

        if options.get('auto'):
            self.stdout.write("自動偵測異常日期...")
            bad_dates = detect_bad_dates()
            if bad_dates:
                self.stdout.write(f"偵測到 {len(bad_dates)} 個可疑日期。")
            else:
                self.stdout.write(self.style.SUCCESS("沒有可疑日期，無需修復。"))
                return

        elif options.get('dates'):
            bad_dates = [date.fromisoformat(d) for d in options['dates']]
        else:
            self.stdout.write(self.style.ERROR("請指定 --auto 或 --date YYYY-MM-DD"))
            return

        bad_dates = sorted(set(bad_dates))
        self.stdout.write(f"準備修復 {len(bad_dates)} 個日期...")

        from apps.market_data.crawler import MarketCrawler

        for i, d in enumerate(bad_dates):
            self.stdout.write(f"[{i+1}/{len(bad_dates)}] {d} ...")
            MarketCrawler.run_daily_crawl(d)
            if i < len(bad_dates) - 1:
                time.sleep(5)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"修復完成！共重抓 {len(bad_dates)} 個日期。"))
        self.stdout.write("下一步：python manage.py calc_indicators --full")
