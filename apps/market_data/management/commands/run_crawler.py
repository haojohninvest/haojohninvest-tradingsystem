from django.core.management.base import BaseCommand
from apps.market_data.crawler import MarketCrawler
from datetime import datetime, timedelta
import time

class Command(BaseCommand):
    help = '執行每日股市爬蟲 (TWSE + OTC)'

    def add_arguments(self, parser):
        parser.add_argument('--date', type=str, help='指定日期 (YYYY-MM-DD)')
        parser.add_argument('--days', type=int, help='往前爬幾天')
        parser.add_argument('--start_date', type=str, help='從哪一天開始爬到今天 (YYYY-MM-DD)')

    def handle(self, *args, **options):
        if options.get('start_date'):
            start_date = datetime.strptime(options['start_date'], '%Y-%m-%d').date()
            today = datetime.today().date()
            delta_days = (today - start_date).days
            self.stdout.write(f"準備從 {start_date} 爬取到 {today} (共 {delta_days + 1} 天)...")
            
            for i in range(delta_days + 1):
                target_date = start_date + timedelta(days=i)
                # 跳過六日，減少無效的連線
                if target_date.weekday() >= 5: 
                    continue
                self.stdout.write(f"正在處理 {target_date}...")
                MarketCrawler.run_daily_crawl(target_date)
                # 強制休息 5 秒，保護 IP 不被證交所封鎖
                time.sleep(5)
        
        elif options.get('date'):
            target_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
            self.stdout.write(f"正在處理 {target_date}...")
            MarketCrawler.run_daily_crawl(target_date)
        
        else:
            # ★ 預設行為：抓今天（如果沒給任何參數）
            target_date = datetime.today().date()
            # 跳過六日（台股休市）
            if target_date.weekday() >= 5:
                self.stdout.write(self.style.WARNING(f"今天是週六/日 ({target_date})，台股休市，跳過爬取。"))
            else:
                self.stdout.write(f"正在處理 {target_date}...")
                MarketCrawler.run_daily_crawl(target_date)
        
        self.stdout.write(self.style.SUCCESS('爬蟲任務執行完畢！'))
        
        # 執行健康檢查
        self.stdout.write("\n執行股價健康檢查...")
        from apps.market_data.management.commands.check_stock_health import Command as HealthCheckCommand
        health_check = HealthCheckCommand()
        try:
            health_check.handle()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'健康檢查執行失敗：{e}'))
