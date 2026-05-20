import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from apps.market_data.models import DailyPrice, Stock
from datetime import datetime

# 檢查 2404 漢唐在 2025/08/11 附近的資料
print("=== 2404 漢唐 2025/08/07 ~ 2025/08/15 資料 ===")
prices = DailyPrice.objects.filter(
    stock__code="2404",
    date__gte="2025-08-07",
    date__lte="2025-08-15"
).order_by("date")

for p in prices:
    weekday_name = ["週一","週二","週三","週四","週五","週六","週日"][p.date.weekday()]
    marker = " *** 週末髒資料 ***" if p.date.weekday() >= 5 else ""
    print(f"{p.date} ({weekday_name}): close={p.close:.2f}, vol={p.volume}{marker}")

print()
# 全面掃描：所有股票的週末資料
print("=== 全面掃描：所有股票的週末（週六/週日）股價資料 ===")
weekend_prices = DailyPrice.objects.filter(date__week_day__in=[1, 7]).select_related('stock').order_by('date', 'stock__code')

count = 0
for p in weekend_prices[:50]:  # 只看前50筆
    weekday_name = ["週一","週二","週三","週四","週五","週六","週日"][p.date.weekday()]
    print(f"{p.date} ({weekday_name}) | {p.stock.code} {p.stock.name} | close={p.close:.2f}")
    count += 1

total_weekend = DailyPrice.objects.filter(date__week_day__in=[1, 7]).count()
print(f"\n... 總共發現 {total_weekend} 筆週末資料（不應該存在，台股休市）")
if total_weekend > 50:
    print("週末髒資料非常多！建議全面清理。")
