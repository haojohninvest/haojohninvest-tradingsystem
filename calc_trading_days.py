import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from datetime import date, timedelta

# 計算交易天數
def count_trading_days(start, end):
    days = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            days += 1
        d += timedelta(days=1)
    return days

start_2020 = date(2020, 1, 1)
start_2023 = date(2023, 1, 1)
today = date(2026, 5, 20)

days_2020 = count_trading_days(start_2020, today)
days_2023 = count_trading_days(start_2023, today)

print(f"2020-01-01 ~ {today}: 約 {days_2020} 個交易日")
print(f"2023-01-01 ~ {today}: 約 {days_2023} 個交易日")
print(f"差異: {days_2020 - days_2023} 天")
print()

# 估算爬取時間：每季一批
time_2020 = days_2020 / 60 * 5 / 60  # 每60交易日=5分鐘，轉小時
time_2023 = days_2023 / 60 * 5 / 60
print(f"2020~today 爬取時間估算: ~{time_2020:.1f} 小時（純爬取）")
print(f"2023~today 爬取時間估算: ~{time_2023:.1f} 小時（純爬取）")
print(f"2020 比 2023 多花: ~{time_2020 - time_2023:.1f} 小時")
