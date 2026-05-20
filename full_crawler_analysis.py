import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from apps.market_data.models import DailyPrice
from datetime import date

# 問題 1: 2020 vs 2023 重建時間
start_2020 = date(2020, 1, 1)
start_2023 = date(2023, 1, 1)
today = date(2026, 5, 20)

def count_trading_days(start, end):
    days = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            days += 1
        d += timedelta(days=1)
    return days

from datetime import timedelta
days_2020 = count_trading_days(start_2020, today)
days_2023 = count_trading_days(start_2023, today)

print("=== 問題 1: 重建時間比較 ===")
print(f"2020-01-01 ~ {today}: 約 {days_2020} 交易日")
print(f"2023-01-01 ~ {today}: 約 {days_2023} 交易日")
print(f"2020 比 2023 多: {days_2020 - days_2023} 交易日（{((days_2020-days_2023)/days_2023*100):.0f}%）")
print()

# 爬蟲時間估算（含 rate limit）
time_2020_hr = days_2020 * 5 / 60  # 每天5秒delay + 1秒處理
print(f"2020~today 純爬取時間: ~{time_2020_hr/24:.1f} 天（若連續跑）")
time_2023_hr = days_2023 * 5 / 60
print(f"2023~today 純爬取時間: ~{time_2023_hr/24:.1f} 天（若連續跑）")
print()

# 問題 2: 為什麼要清空前還要刪週末？
print("=== 問題 2: 清空前為何還要刪週末？ ===")
print("答案: 不需要！")
print("只要執行: DELETE FROM DailyPrice WHERE date >= '2020-01-01'")
print("就會一併刪除 2020~today 的所有平日+週末資料")
print(f"週末資料 {DailyPrice.objects.filter(date__week_day__in=[1,7]).count()} 筆也會被清掉")
print("所以只需要一個指令：清空 2020~today，不用特別先刪週末")
print()

# 問題 3: 爬蟲還有什麼其他問題？
print("=== 問題 3: 爬蟲潛在問題全面檢查 ===")
print()
print("3A. TWSE fetch_twse 問題分析:")
print("   - line 38: cleaned_lines = [... if len(i.split('",')) == 17 ...]")
print("   - 問題: 除權息日欄位會變成 18 或更多，此行過濾掉除權息資料！")
print("   - 結果: 除權息日抓到的資料可能缺少部分股票")
print()
print("3B. OTC fetch_otc 問題分析:")
print("   - line 109-118: 用 expected_cols 按位置 rename")
print("   - 問題: OTC 也有除權息參考價欄位，位置會偏移")
print("   - 結果: 除權息日收盤價可能抓到錯的欄位")
print()
print("3C. run_daily_crawl 問題:")
print("   - line 225: DailyPrice.objects.filter(date=target_date).delete()")
print("   - 問題: 每次覆蓋前會先刪除當天所有資料")
print("   - 結果: 若新資料有有誤，舊的正確資料也沒了，無法回滾")
print()
print("3D. 沒有價格合理性驗證:")
print("   - 沒有檢查 close 是否為負數或 0")
print("   - 沒有檢查 open/high/low/close 的邏輯關係（low <= close <= high）")
print("   - 沒有與前一日收盤價比較（異常跳動 > 50%）")
print()
print("3E. 沒有交易日曆檢查:")
print("   - 直接傳日期給 API，沒有先查是否為交易日")
print("   - 結果: 非交易日會回傳空，但浪費一次 API call")

# 檢查實際案例：除權息日前後
print()
print("=== 檢查除權息日案例 ===")
# 2024/5/20 多家公司錯誤（可能是除權息日）
test_date = date(2024, 5, 20)
prices = DailyPrice.objects.filter(date=test_date).select_related('stock')[:5]
for p in prices:
    print(f"{p.stock.code} {p.stock.name}: {p.close}")

# 檢查 2024/5/20 前一天和後一天
prev_day = DailyPrice.objects.filter(date='2024-05-17', stock__code='1101').first()
next_day = DailyPrice.objects.filter(date='2024-05-21', stock__code='1101').first()
if prev_day:
    print(f"\n1101 台泥 2024/5/17: {prev_day.close}")
if next_day:
    print(f"1101 台泥 2024/5/21: {next_day.close}")
print("如果 5/20 收盤價 25.50，而 5/17 是 33.90，跳動 -25%，很可能是除權息影響")
