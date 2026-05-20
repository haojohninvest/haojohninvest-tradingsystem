import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from apps.market_data.models import DailyPrice, Stock

# 讀取 1519 所有歷史價格
s = Stock.objects.filter(code="1519").first()
print(f"Stock: {s}")
print(f"Total price records: {DailyPrice.objects.filter(stock__code='1519').count()}")
print()

# 顯示 2025 年的資料
prices = DailyPrice.objects.filter(
    stock__code="1519",
    date__gte="2025-01-01",
    date__lte="2025-12-31"
).order_by("date")

print("=== 2025 年 1519 華城 股價資料 ===")
for p in prices:
    print(f"{p.date}: {p.close}")
