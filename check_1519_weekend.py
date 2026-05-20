import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from apps.market_data.models import DailyPrice, Stock
from datetime import datetime

# 檢查所有週末（週六、週日）的 1519 股價資料
prices = DailyPrice.objects.filter(stock__code="1519").order_by("date")

print("=== 檢查 1519 華城 週末資料 ===")
print("(台股休市，週六/週日不應有資料)")
print()

weekend_prices = []
for p in prices:
    weekday = p.date.weekday()
    if weekday >= 5:  # 週六=5, 週日=6
        weekend_prices.append(p)
        day_name = "週六" if weekday == 5 else "週日"
        print(f"{p.date} ({day_name}): {p.close:.2f}")

print()
print(f"總共發現 {len(weekend_prices)} 筆週末資料（不應該存在）")

# 檢查 2025/7/24 附近的資料（使用者說這之前錯）
print()
print("=== 2025/07/14 ~ 2025/07/25 區間 ===")
for p in prices:
    if "2025-07-14" <= str(p.date) <= "2025-07-25":
        weekday_name = ["週一","週二","週三","週四","週五","週六","週日"][p.date.weekday()]
        marker = " *** 週末髒資料 ***" if p.date.weekday() >= 5 else ""
        print(f"{p.date} ({weekday_name}): {p.close:.2f}{marker}")
