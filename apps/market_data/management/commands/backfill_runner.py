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

輸出:
    - 執行中: 逐日進度顯示在 console
    - .backfill_progress.json: 進度存檔 (支援 --resume)
    - logs/backfill_summary.csv: 每日爬取摘要
    - logs/price_anomalies.csv: 價格異常記錄 (crawl_date, date, code, name, close, prev_close, change_pct, reason)
"""

import os
import json
import csv
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from apps.market_data.crawler import MarketCrawler
from apps.market_data.models import DailyPrice
from config.taiwan_holidays import is_holiday

PROGRESS_FILE = '.backfill_progress.json'
SUMMARY_LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))),
    "logs"
)
SUMMARY_LOG_FILE = os.path.join(SUMMARY_LOG_DIR, "backfill_summary.csv")

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

        # 如果 resume，讀取進度
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

        # 每日摘要記錄 (供最終 CSV 輸出)
        daily_summary = []
        skipped_holidays = 0
        skipped_weekends = 0

        self.stdout.write(self.style.SUCCESS(f'開始回填: {start_date} ~ {end_date} (共 {total_days} 天)'))
        self.stdout.write(self.style.SUCCESS(f'執行時間戳記: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'))

        while current <= end_date:
            # 非交易日：檢查並清除 DB 中殘留的資料
            is_non_trading_day = current.weekday() >= 5 or is_holiday(current)
            if is_non_trading_day:
                reason = '週末' if current.weekday() >= 5 else '休市日'
                status = 'weekend' if current.weekday() >= 5 else 'holiday'
                DailyPrice.objects.filter(date=current).delete()
                daily_summary.append({
                    'run_datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'date': current.strftime('%Y-%m-%d'),
                    'market': market,
                    'companies': 0,
                    'status': status,
                    'reason': reason,
                })
                if current.weekday() >= 5:
                    skipped_weekends += 1
                else:
                    skipped_holidays += 1
                current += timedelta(days=1)
                continue

            self.stdout.write(f'[{completed+1}/{total_days}] 處理 {current}...', ending=' ')

            try:
                # 執行爬蟲
                result = MarketCrawler.run_daily_crawl(current, market=market)

                if result['status'] == 'success' or result['status'] == 'partial':
                    completed += 1
                    last_completed = current.strftime('%Y-%m-%d')
                else:
                    failed_dates.append(current.strftime('%Y-%m-%d'))

                daily_summary.append({
                    'run_datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'date': current.strftime('%Y-%m-%d'),
                    'market': market,
                    'companies': result['companies'],
                    'status': result['status'],
                    'reason': result.get('reason', ''),
                })

                # 寫入進度檔案
                progress = {
                    'last_completed_date': last_completed,
                    'total_dates': total_days,
                    'completed': completed,
                    'failed': failed_dates[-10:]  # 只保留最近 10 筆失敗
                }
                with open(PROGRESS_FILE, 'w') as f:
                    json.dump(progress, f)

                self.stdout.write(self.style.SUCCESS('OK'))

            except Exception as e:
                failed_dates.append(current.strftime('%Y-%m-%d'))
                daily_summary.append({
                    'run_datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'date': current.strftime('%Y-%m-%d'),
                    'market': market,
                    'companies': 0,
                    'status': 'fail',
                    'reason': str(e)[:200],
                })
                self.stdout.write(self.style.ERROR(f'FAIL: {e}'))

            current += timedelta(days=1)

            # 延遲避免被封鎖
            if current <= end_date:
                import time
                time.sleep(delay)

        # 產出每日摘要 CSV
        if daily_summary:
            os.makedirs(SUMMARY_LOG_DIR, exist_ok=True)
            file_exists = os.path.isfile(SUMMARY_LOG_FILE)
            with open(SUMMARY_LOG_FILE, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['run_datetime', 'date', 'market', 'companies', 'status', 'reason'])
                if not file_exists:
                    writer.writeheader()
                writer.writerows(daily_summary)

        # 最終報告
        self.stdout.write(self.style.SUCCESS(f'\n回填完成！成功 {completed}/{total_days} 天'))
        if skipped_weekends:
            self.stdout.write(self.style.SUCCESS(f'自動跳過週末: {skipped_weekends} 天'))
        if skipped_holidays:
            self.stdout.write(self.style.SUCCESS(f'自動跳過休市日: {skipped_holidays} 天'))
        self.stdout.write(self.style.SUCCESS(f'摘要已寫入: {SUMMARY_LOG_FILE}'))
        if failed_dates:
            self.stdout.write(self.style.WARNING(f'失敗日期 ({len(failed_dates)} 天): {failed_dates[:10]}{"..." if len(failed_dates) > 10 else ""}'))
            self.stdout.write(self.style.WARNING(f'建議手動補抓: python manage.py backfill_runner --start {failed_dates[0]} --end {failed_dates[-1]}'))
