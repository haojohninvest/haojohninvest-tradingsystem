import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from apps.market_data.models import DailyPrice, Stock
from datetime import timedelta

# 驗證多支熱門股票最近的正確性
stocks_to_check = ["2317", "2330", "2454", "2881", "2891", "1519", "2404"]

print("=== 交叉驗證：最近一個週五 vs 週一 ===")
from datetime import date

def find_last_friday():
    today = date.today()
    offset = (today.weekday() - 4) % 7
    last_friday = today - timedelta(days=offset)
    return last_friday

def find_next_monday(d):
    return d + timedelta(days=3)

last_fri = find_last_friday()
next_mon = find_next_monday(last_fri)

print(f"檢查週五 {last_fri} vs 週一 {next_mon}")
print()

for code in stocks_to_check:
    fri = DailyPrice.objects.filter(stock__code=code, date=last_fri).first()
    mon = DailyPrice.objects.filter(stock__code=code, date=next_mon).first()
    print(f"{code}: 週五={fri.close if fri else 'N/A'} | 週一={mon.close if mon else 'N/A'}")

# 檢查是否有重複的異常值
print("\n=== 檢查全庫異常收盤價 ===")
for val in [757, 19.30, 1105, 100]:
    cnt = DailyPrice.objects.filter(close=val).count()
    if cnt > 0:
        print(f"close={val}: {cnt} 筆")

# 檢查 2024/5/20 的資料（使用者說多家公司錯）
print("\n=== 2024/5/20 (週一) vs 2024/5/17 (週五) vs API 資料 ===")
for code in ["1101", "2330", "1519", "2404"]:
    fri = DailyPrice.objects.filter(stock__code=code, date="2024-05-17").first()
    mon = DailyPrice.objects.filter(stock__code=code, date="2024-05-20").first()
    print(f"{code}: 5/17(五)={fri.close if fri else 'N/A'} | 5/20(一)={mon.close if mon else 'N/A'}")

# 檢查週末資料是否是前一個交易日的複製
print("\n=== 週末資料是否為前一交易日複製？ ===")
weekend_dates = DailyPrice.objects.filter(date__week_day__in=[1,7]).values_list('date', flat=True).distinct()
for wd in weekend_dates[:5]:
    # 找到前一個交易日
    prev_date = wd - timedelta(days=1)
    while prev_date.weekday() >= 5:
        prev_date -= timedelta(days=1)
    
    # 比對週末與前一交易日的收盤價
    weekend_prices = DailyPrice.objects.filter(date=wd).values_list('stock__code', 'close')
    prev_prices = {p[0]: p[1] for p in DailyPrice.objects.filter(date=prev_date).values_list('stock__code', 'close')}
    
    match_count = 0
    total = 0
    for code, close in weekend_prices:
        if code in prev_prices:
            total += 1
            if abs(close - prev_prices[code]) < 0.01:
                match_count += 1
    
    print(f"{wd}: {match_count}/{total} 股票收盤價與前一交易日完全相同 ({match_count/total*100:.1f}%)")
