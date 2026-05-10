"""
從 FinMind 抓取歷史發行股數

使用方式:
    python manage.py fetch_finmind_shares
    python manage.py fetch_finmind_shares --start_year 2016 --end_year 2025
    python manage.py fetch_finmind_shares --year 2026 --quarter 1
"""

import requests
import pandas as pd
import time
import os
from datetime import datetime
from django.core.management.base import BaseCommand
from apps.market_data.models import Stock, StockSharesHistory

# FinMind API Token (從環境變數讀取)
FINMIND_TOKEN = os.getenv('FINMIND_TOKEN', '')

def get_capital_stock_from_finmind(stock_id, year, quarter, token):
    """從 FinMind 抓指定季度的 CapitalStock (股本)"""
    quarter_months = {
        1: ("01-01", "03-31"),
        2: ("04-01", "06-30"),
        3: ("07-01", "09-30"),
        4: ("10-01", "12-31")
    }
    start_m, end_m = quarter_months[quarter]
    start_date = f"{year}-{start_m}"
    end_date = f"{year}-{end_m}"
    
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockBalanceSheet",
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
        "token": token
    }
    
    try:
        r = requests.get(url, params=params, timeout=30)
        data = r.json()
        if "data" in data and data["data"]:
            df = pd.DataFrame(data["data"])
            capital = df[df['type'] == 'CapitalStock']
            if len(capital) > 0:
                value = float(capital.iloc[0]['value'])
                return value
    except Exception as e:
        pass
    return None

def get_shares_with_fallback(stock_id, year, quarter, token):
    """抓股數，帶有 fallback 機制"""
    capital = get_capital_stock_from_finmind(stock_id, year, quarter, token)
    
    # Fallback：往回推最多 12 個季度（3 年）
    fallback_count = 0
    q_year, q_quarter = year, quarter
    while capital is None and fallback_count < 12:
        q_quarter -= 1
        if q_quarter < 1:
            q_quarter = 4
            q_year -= 1
        capital = get_capital_stock_from_finmind(stock_id, q_year, q_quarter, token)
        fallback_count += 1
    
    if capital and capital > 0:
        shares = capital / 10
        return int(shares), f"finmind_{q_year}Q{q_quarter}"
    
    return 0, "zero_fallback"

class Command(BaseCommand):
    help = '從 FinMind 抓取歷史發行股數'

    def add_arguments(self, parser):
        parser.add_argument('--start_year', type=int, default=2016, help='開始年份')
        parser.add_argument('--end_year', type=int, default=2025, help='結束年份')
        parser.add_argument('--year', type=int, default=None, help='指定年份（用於單季更新）')
        parser.add_argument('--quarter', type=int, default=None, help='指定季度（1-4）')
        parser.add_argument('--delay', type=float, default=0.5, help='每檔股票間隔秒數')

    def handle(self, *args, **options):
        if not FINMIND_TOKEN:
            self.stdout.write(self.style.ERROR('請設定 FINMIND_TOKEN 環境變數'))
            return
        
        delay = options['delay']
        
        # 如果指定了 year 和 quarter，只抓那一季
        if options['year'] and options['quarter']:
            self.fetch_single_quarter(options['year'], options['quarter'], delay)
        else:
            # 抓歷史 2016~2025 Q4
            self.fetch_all_historical(options['start_year'], options['end_year'], delay)
            # 抓 2026 Q1
            self.fetch_single_quarter(2026, 1, delay)
        
        self.stdout.write(self.style.SUCCESS('\n全部完成！'))

    def fetch_all_historical(self, start_year, end_year, delay):
        """抓取所有股票 2016~end_year 的每年 Q4 股本"""
        stocks = Stock.objects.all()
        total = stocks.count()
        self.stdout.write(self.style.SUCCESS(f'共 {total} 檔股票需要抓取歷史股數 ({start_year}~{end_year} Q4)'))
        
        records_created = 0
        records_skipped = 0
        
        for idx, stock in enumerate(stocks, 1):
            self.stdout.write(f'[{idx}/{total}] {stock.code} {stock.name}...', ending=' ')
            
            for year in range(start_year, end_year + 1):
                shares, source = get_shares_with_fallback(stock.code, year, 4, FINMIND_TOKEN)
                
                if shares > 0:
                    applicable_date = datetime(year, 12, 31).date()
                    obj, created = StockSharesHistory.objects.update_or_create(
                        stock=stock,
                        date=applicable_date,
                        defaults={
                            'outstanding_shares': shares,
                            'source': source
                        }
                    )
                    if created:
                        records_created += 1
                else:
                    records_skipped += 1
            
            self.stdout.write(self.style.SUCCESS('OK'))
            time.sleep(delay)
        
        self.stdout.write(self.style.SUCCESS(f'\n歷史股數完成！新增 {records_created} 筆，跳過 {records_skipped} 筆（股數為 0）'))

    def fetch_single_quarter(self, year, quarter, delay):
        """抓取指定季度的股本"""
        stocks = Stock.objects.all()
        total = stocks.count()
        self.stdout.write(self.style.SUCCESS(f'\n共 {total} 檔股票需要抓取 {year} Q{quarter} 股數'))
        
        records_created = 0
        
        for idx, stock in enumerate(stocks, 1):
            self.stdout.write(f'[{idx}/{total}] {stock.code} {stock.name}...', ending=' ')
            
            shares, source = get_shares_with_fallback(stock.code, year, quarter, FINMIND_TOKEN)
            
            if shares > 0:
                # 根據季度決定適用日期
                month = quarter * 3
                applicable_date = datetime(year, month, 1).date()
                
                obj, created = StockSharesHistory.objects.update_or_create(
                    stock=stock,
                    date=applicable_date,
                    defaults={
                        'outstanding_shares': shares,
                        'source': source
                    }
                )
                if created:
                    records_created += 1
                self.stdout.write(self.style.SUCCESS(f'{shares:,} ({source})'))
            else:
                self.stdout.write(self.style.WARNING('股數為 0'))
            
            time.sleep(delay)
        
        self.stdout.write(self.style.SUCCESS(f'\n{year} Q{quarter} 完成！新增 {records_created} 筆'))
