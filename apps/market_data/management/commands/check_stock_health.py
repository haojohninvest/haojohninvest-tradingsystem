from django.core.management.base import BaseCommand
from apps.market_data.models import Stock, DailyPrice
from django.db.models import Count, Q
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = '檢查股價資料健康狀態'
    
    def handle(self, *args, **options):
        self.stdout.write("=" * 60)
        self.stdout.write(f"股價健康檢查報告 ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
        self.stdout.write("=" * 60)
        
        issues = []
        warnings = []
        
        # 1. 總體覆蓋率檢查
        total_stocks = Stock.objects.count()
        stocks_with_price = Stock.objects.annotate(
            price_count=Count('daily_prices')
        ).filter(price_count__gt=0).count()
        
        coverage_rate = (stocks_with_price / total_stocks * 100) if total_stocks > 0 else 0
        
        self.stdout.write(f"\n總體覆蓋率：{coverage_rate:.1f}% ({stocks_with_price:,} / {total_stocks:,})")
        
        if coverage_rate < 95:
            issue_msg = f"覆蓋率低於 95% ({coverage_rate:.1f}%)"
            issues.append(issue_msg)
            self.stdout.write(self.style.ERROR(f"  [X] {issue_msg}"))
        elif coverage_rate < 90:
            warn_msg = f"覆蓋率低於 90% ({coverage_rate:.1f}%)"
            warnings.append(warn_msg)
            self.stdout.write(self.style.WARNING(f"  [!] {warn_msg}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"  [OK] 覆蓋率正常"))
        
        # 2. 市場別分佈檢查
        self.stdout.write("\n市場別分佈：")
        
        for market, market_name in [('twse', '上市'), ('otc', '上櫃')]:
            market_stocks = Stock.objects.filter(market=market).count()
            market_with_price = Stock.objects.filter(market=market).annotate(
                price_count=Count('daily_prices')
            ).filter(price_count__gt=0).count()
            
            market_coverage = (market_with_price / market_stocks * 100) if market_stocks > 0 else 0
            
            self.stdout.write(f"  {market_name}: {market_with_price:,} / {market_stocks:,} = {market_coverage:.1f}%")
            
            if market_coverage < 95:
                issue_msg = f"{market_name}市場覆蓋率低於 95% ({market_coverage:.1f}%)"
                issues.append(issue_msg)
                self.stdout.write(self.style.ERROR(f"    [X] {issue_msg}"))
            elif market_coverage < 90:
                warn_msg = f"{market_name}市場覆蓋率低於 90% ({market_coverage:.1f}%)"
                warnings.append(warn_msg)
                self.stdout.write(self.style.WARNING(f"    [!] {warn_msg}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"    [OK] 正常"))
        
        # 3. 異常模式偵測 - 檢查是否有股票連續多日無股價
        self.stdout.write("\n異常模式偵測：")
        
        # 找出最近 30 天完全無股價的股票
        recent_date = datetime.now().date() - timedelta(days=30)
        stocks_no_recent_price = Stock.objects.annotate(
            recent_price_count=Count('daily_prices', filter=Q(daily_prices__date__gte=recent_date))
        ).filter(recent_price_count=0).count()
        
        if stocks_no_recent_price > 0:
            issue_msg = f"{stocks_no_recent_price} 支股票最近 30 天無股價資料"
            issues.append(issue_msg)
            self.stdout.write(self.style.ERROR(f"  [X] {issue_msg}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"  [OK] 所有股票最近 30 天都有股價"))
        
        # 4. 爬蟲日誌檢查
        self.stdout.write("\n爬蟲日誌 (最近 7 天)：")
        
        seven_days_ago = datetime.now() - timedelta(days=7)
        
        try:
            with open('logs/app.log', 'r', encoding='utf-8') as f:
                log_lines = f.readlines()
            
            twse_errors = 0
            otc_errors = 0
            
            for line in log_lines:
                if 'crawler error' in line.lower():
                    # 檢查是否在最近 7 天
                    try:
                        log_date_str = line.split(' ')[0]
                        log_date = datetime.strptime(log_date_str, '%Y-%m-%d')
                        if log_date >= seven_days_ago:
                            if 'twse' in line.lower():
                                twse_errors += 1
                            elif 'otc' in line.lower():
                                otc_errors += 1
                    except:
                        pass
            
            self.stdout.write(f"  TWSE 錯誤：{twse_errors} 次")
            self.stdout.write(f"  OTC 錯誤：{otc_errors} 次")
            
            if twse_errors > 100:
                warn_msg = f"TWSE 錯誤過多 ({twse_errors} 次)"
                warnings.append(warn_msg)
                self.stdout.write(self.style.WARNING(f"  [!] {warn_msg}"))
            
            if otc_errors > 100:
                warn_msg = f"OTC 錯誤過多 ({otc_errors} 次)"
                warnings.append(warn_msg)
                self.stdout.write(self.style.WARNING(f"  [!] {warn_msg}"))
                
            if twse_errors <= 100 and otc_errors <= 100:
                self.stdout.write(self.style.SUCCESS(f"  [OK] 錯誤數量正常"))
                
        except FileNotFoundError:
            self.stdout.write(self.style.WARNING("  [!] 找不到日誌檔"))
        
        # 5. 隨機抽樣驗證
        self.stdout.write("\n隨機抽樣驗證 (5 支股票)：")
        
        sample_stocks = Stock.objects.filter(daily_prices__isnull=False).distinct()[:5]
        
        for stock in sample_stocks:
            latest_price = DailyPrice.objects.filter(stock=stock).order_by('-date').first()
            if latest_price:
                self.stdout.write(f"  [OK] {stock.code} {stock.name}: {latest_price.date} 收盤價 {latest_price.close}")
            else:
                self.stdout.write(self.style.ERROR(f"  [X] {stock.code} {stock.name}: 無股價資料"))
        
        # 總結
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("建議行動：")
        
        if issues:
            for issue in issues:
                self.stdout.write(self.style.ERROR(f"  - {issue}"))
        elif warnings:
            for warn in warnings:
                self.stdout.write(self.style.WARNING(f"  - {warn}"))
        else:
            self.stdout.write(self.style.SUCCESS("  [OK] 無異常，系統運作正常"))
        
        self.stdout.write("=" * 60)
        
        # 寫入日誌檔
        health_log_path = 'logs/health_check.log'
        try:
            with open(health_log_path, 'a', encoding='utf-8') as f:
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"\n[{timestamp}] 健康檢查完成\n")
                f.write(f"覆蓋率：{coverage_rate:.1f}%\n")
                f.write(f"問題數：{len(issues)}, 警告數：{len(warnings)}\n")
                if issues:
                    f.write(f"問題清單：{', '.join(issues)}\n")
                if warnings:
                    f.write(f"警告清單：{', '.join(warnings)}\n")
            logger.info(f"健康檢查報告已寫入 {health_log_path}")
        except Exception as e:
            logger.error(f"寫入健康檢查日誌失敗：{e}")
        
        # 如果有嚴重問題，回傳非零退出碼
        if issues:
            self.stdout.write(self.style.ERROR("\n發現嚴重問題，請立即處理！"))
            exit(1)
