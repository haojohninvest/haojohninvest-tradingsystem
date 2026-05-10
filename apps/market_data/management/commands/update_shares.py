from django.core.management.base import BaseCommand
import requests
import urllib3
from apps.market_data.models import Stock

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class Command(BaseCommand):
    help = '從公開資訊觀測站抓取所有上市櫃公司的發行股數'

    def handle(self, *args, **options):
        self.stdout.write("開始抓取上市/上櫃公司發行股數...")
        
        # 1. 抓取上市
        self.stdout.write("抓取上市 (TWSE)...")
        try:
            r = requests.get('https://openapi.twse.com.tw/v1/opendata/t187ap03_L', verify=False, timeout=10)
            twse_data = r.json()
            updated_count = 0
            for item in twse_data:
                code = item.get('公司代號', '').strip()
                if not code:
                    # 如果用 get 抓不到，試著用欄位位置抓 (第2個欄位通常是代號，最後一個是股數)
                    values = list(item.values())
                    if len(values) > 2:
                        code = str(values[1]).strip()
                        
                # 為了避開中文亂碼，直接取 JSON 字典的最後一個值 (政府 API 最後一欄就是股數)
                shares_str = str(list(item.values())[-1])
                try:
                    shares = int(shares_str)
                    Stock.objects.filter(code=code).update(outstanding_shares=shares)
                    updated_count += 1
                except:
                    pass
            self.stdout.write(f"成功更新 {updated_count} 檔上市股票的股數。")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"上市股數抓取失敗: {e}"))

        # 2. 抓取上櫃
        self.stdout.write("抓取上櫃 (TPEX)...")
        try:
            r = requests.get('https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O', verify=False, timeout=10)
            tpex_data = r.json()
            updated_count = 0
            for item in tpex_data:
                code = item.get('SecuritiesCompanyCode', '').strip()
                shares_str = item.get('IssueShares', '0')
                try:
                    shares = int(shares_str)
                    Stock.objects.filter(code=code).update(outstanding_shares=shares)
                    updated_count += 1
                except:
                    pass
            self.stdout.write(f"成功更新 {updated_count} 檔上櫃股票的股數。")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"上櫃股數抓取失敗: {e}"))
            
        self.stdout.write(self.style.SUCCESS("全部股數更新完畢！"))