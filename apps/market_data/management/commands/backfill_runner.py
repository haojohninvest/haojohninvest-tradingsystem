"""
歷史資料回填腳本
從 2016-01-01 開始逐日抓 TWSE + OTC 股價，並每日更新發行股數

使用方式:
    # 全新開始
    python manage.py backfill_runner --start 2016-01-01 --end 2026-05-10

    # 中斷續跑 (自動讀取 .backfill_progress.json)
    python manage.py backfill_runner --resume

    # 只抓 OTC (用於補救)
    python manage.py backfill_runner --start 2020-01-01 --market otc
"""

import os
import json
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from apps.market_data.crawler import MarketCrawler
from apps.market_data.models import DailyPrice

PROGRESS_FILE = '.backfill_progress.json'


class Command(BaseCommand):
    help = '回填歷史股價資料'

    def add_arguments(self, parser):
        parser.add_argument('--start', type=str, default='2016-01-01', help='開始日期 (YYYY-MM-DD)')
        parser.add_argument('--end', type=str, default=None, help='結束日期 (YYYY-MM-DD)，預設今天')
        parser.add_argument('--resume', action='store_true', help='從上次中斷處續跑')
        parser.add_argument('--market', type=str, default='all', choices=['all', 'twse', 'otc'], help='只抓特定市場')
        parser.add_argument('--delay', type=int, default=3, help='每次爬蟲間隔秒數')

    def handle(self, *args, **options):
        start_str = options['start']
        end_str = options['end'] or datetime.today().strftime('%Y-%m-%d')
        resume = options['resume']
        market = options['market']
        delay = options['delay']

        start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_str, '%Y-%m-%d').date()

        last_completed = None
        if resume and os.path.exists(PROGRESS_FILE):
            with open(PROGRESS_FILE, 'r') as f:
                progress = json.load(f)
                last_completed = progress.get('last_completed_date')
                if last_completed:
                    start_date = datetime.strptime(last_completed, '%Y-%m-%d').date() + timedelta(days=1)
                    self.stdout.write(self.style.WARNING(f'從中斷處續跑: {start_date}'))

        current = start_date
        total_days = (end_date - start_date).days + 1
        completed = 0
        failed_dates = []

        self.stdout.write(self.style.SUCCESS(f'開始回填: {start_date} ~ {end_date} (共 {total_days} 天)'))

        while current <= end_date:
            self.stdout.write(f'[{completed+1}/{total_days}] 處理 {current}...', ending=' ')

            try:
                DailyPrice.objects.filter(date=current).delete()
                MarketCrawler.run_daily_crawl(current)
                completed += 1
                last_completed = current.strftime('%Y-%m-%d')

                progress = {
                    'last_completed_date': last_completed,
                    'total_dates': total_days,
                    'completed': completed,
                    'failed': failed_dates[-10:]
                }
                with open(PROGRESS_FILE, 'w') as f:
                    json.dump(progress, f)

                self.stdout.write(self.style.SUCCESS('OK'))

            except Exception as e:
                failed_dates.append(current.strftime('%Y-%m-%d'))
                self.stdout.write(self.style.ERROR(f'FAIL: {e}'))

            current += timedelta(days=1)

            if current <= end_date:
                import time
                time.sleep(delay)

        self.stdout.write(self.style.SUCCESS(f'\n回填完成！成功 {completed}/{total_days} 天'))
        if failed_dates:
            self.stdout.write(self.style.WARNING(f'失敗日期: {failed_dates}'))
            self.stdout.write(self.style.WARNING(f'建議手動補抓: python manage.py backfill_runner --start {failed_dates[0]} --end {failed_dates[-1]}'))
