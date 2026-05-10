"""
OTC 歷史資料專屬爬蟲
- 只爬 OTC，不碰 TWSE
- 使用更保守的間隔（30 秒）避免被擋
- 可指定開始日期
- 不影響每日 run_crawler 命令
"""
from django.core.management.base import BaseCommand
from apps.market_data.crawler import MarketCrawler
from datetime import datetime, timedelta
import time
import logging
import pandas as pd

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = '專屬 OTC 歷史資料爬蟲 (不影響每日爬蟲)'

    def add_arguments(self, parser):
        parser.add_argument('--start_date', type=str, required=True, help='開始日期 (YYYY-MM-DD)')
        parser.add_argument('--end_date', type=str, help='結束日期 (YYYY-MM-DD)，預設為今天')
        parser.add_argument('--delay', type=int, default=30, help='每次爬取間隔秒數 (預設 30 秒)')

    def handle(self, *args, **options):
        start_date = datetime.strptime(options['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(options['end_date'], '%Y-%m-%d').date() if options.get('end_date') else datetime.today().date()
        delay = options.get('delay', 30)
        
        self.stdout.write(f"準備爬取 OTC 歷史資料：{start_date} 到 {end_date}")
        self.stdout.write(f"爬取間隔：{delay} 秒")
        self.stdout.write(f"注意：此命令只爬 OTC，不影響每日 run_crawler")
        self.stdout.write("")
        
        delta_days = (end_date - start_date).days + 1
        success_count = 0
        fail_count = 0
        skip_count = 0
        
        for i in range(delta_days):
            target_date = start_date + timedelta(days=i)
            
            # 跳過六日
            if target_date.weekday() >= 5:
                skip_count += 1
                continue
            
            self.stdout.write(f"[{i+1}/{delta_days}] 正在處理 {target_date}...", ending=' ')
            
            # 只爬 OTC
            otc_df = MarketCrawler.fetch_otc(target_date, max_retries=5, retry_delay=10)
            
            if otc_df.empty:
                self.stdout.write(self.style.WARNING(f"失敗 (無資料)"))
                fail_count += 1
            else:
                # 過濾：只保留 4 碼數字的普通股 (過濾掉 ETF、權證等)
                otc_df = otc_df[otc_df.index.astype(str).str.match(r'^\d{4}$')]
                
                # 寫入資料庫
                from apps.market_data.models import Stock, DailyPrice
                
                # 先建立不存在的股票
                for code, row in otc_df.iterrows():
                    code = str(code).strip()
                    Stock.objects.get_or_create(
                        code=code,
                        defaults={
                            'name': str(row.get('name', '')).strip(),
                            'market': 'otc',
                        }
                    )
                
                # 取得所有股票
                stocks = {s.code: s for s in Stock.objects.filter(market='otc')}
                
                # 建立股價
                prices_to_create = []
                for code, row in otc_df.iterrows():
                    code = str(code).strip()
                    if code in stocks and pd.notna(row.get('close')):
                        price = DailyPrice(
                            stock=stocks[code],
                            date=target_date,
                            open=row['open'] if pd.notna(row['open']) else None,
                            high=row['high'] if pd.notna(row['high']) else None,
                            low=row['low'] if pd.notna(row['low']) else None,
                            close=row['close'] if pd.notna(row['close']) else None,
                            volume=row['volume'] if pd.notna(row['volume']) else None,
                            trade_value=row['trade_value'] if pd.notna(row['trade_value']) else None,
                        )
                        prices_to_create.append(price)
                
                if prices_to_create:
                    DailyPrice.objects.bulk_create(prices_to_create, ignore_conflicts=True)
                    self.stdout.write(self.style.SUCCESS(f"成功 (寫入 {len(prices_to_create)} 筆)"))
                    success_count += 1
                else:
                    self.stdout.write(self.style.WARNING("成功 (無股價資料)"))
                    success_count += 1
            
            # 間隔等待
            if i < delta_days - 1:
                time.sleep(delay)
        
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.SUCCESS("OTC 歷史爬蟲完成！"))
        self.stdout.write(f"成功：{success_count} 天")
        self.stdout.write(f"失敗：{fail_count} 天")
        self.stdout.write(f"跳過 (假日)：{skip_count} 天")
        self.stdout.write("=" * 60)
