import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from apps.market_data.models import DailyPrice
from datetime import date

# 問題 1: 計算交易日數
def count_trading_days(start, end):
    days = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            days += 1
        d += timedelta(days=1)
    return days

from datetime import timedelta

start_2020 = date(2020, 1, 1)
start_2023 = date(2023, 1, 1)
today = date(2026, 5, 20)

days_2020 = count_trading_days(start_2020, today)
days_2023 = count_trading_days(start_2023, today)

print("=== 問題 1: 重建時間比較 ===")
print(f"2020-01-01 ~ {today}: 約 {days_2020} 交易日")
print(f"2023-01-01 ~ {today}: 約 {days_2023} 交易日")
diff_days = days_2020 - days_2023
pct = (diff_days / days_2023 * 100)
print(f"2020 比 2023 多: {diff_days} 交易日 ({pct:.0f}%)")
print()

# 爬蟲時間估算
time_2020_hr = days_2020 * 5 / 60  # 每天5秒
print(f"2020~today 純爬取: ~{time_2020_hr:.0f} 小時 = {time_2020_hr/24:.1f} 天")
time_2023_hr = days_2023 * 5 / 60
print(f"2023~today 純爬取: ~{time_2023_hr:.0f} 小時 = {time_2023_hr/24:.1f} 天")
print(f"2020 比 2023 多花: ~{time_2020_hr - time_2023_hr:.0f} 小時 = {(time_2020_hr - time_2023_hr)/24:.1f} 天")
print()

# 問題 2: 為什麼還要刪週末？
print("=== 問題 2: 清空前為何還要刪週末？ ===")
weekend_count = DailyPrice.objects.filter(date__week_day__in=[1,7]).count()
print(f"週末資料: {weekend_count} 筆")
print("答案: 不需要特別刪！")
print("直接 DELETE FROM DailyPrice WHERE date >= '2020-01-01'")
print("就會一併清掉平日+週末")
print()

# 問題 3: 爬蟲其他問題
print("=== 問題 3: 爬蟲潛在問題 ===")
print("A. TWSE fetch_twse:")
print("   line 38: 過濾條件 len(split('")) == 17")
print("   除權息日 CSV 會有 18+ 欄位，被過濾掉！")
print()
print("B. OTC fetch_otc:")
print("   line 109: 用 expected_cols 按位置 rename")
print("   除權息日欄位偏移，收盤價抓到錯誤欄位")
print()
print("C. 沒有價格驗證:")
print("   - 沒檢查 close > 0")
print("   - 沒檢查 low <= close <= high")
print("   - 沒與前日比較異常跳動")

# 檢查 2024/5/20
print()
print("=== 除權息檢查: 2024/5/20 ===")
prices = DailyPrice.objects.filter(date="2024-05-20", stock__code="1101").first()
if prices:
    print(f"1101 台泥 2024/5/20: close={prices.close}")
prev_price = DailyPrice.objects.filter(date="2024-05-17", stock__code="1101").first()
if prev_price:
    print(f"1101 台泥 2024/5/17(前日): close={prev_price.close}")
    change_pct = (prices.close - prev_price.close) / prev_price.close * 100 if prices else 0
    print(f"跳動: {change_pct:.1f}%")
    if abs(change_pct) > 20:
        print("*** 異常跳動 > 20%，很可能是除權息導致")
